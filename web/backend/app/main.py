"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from .core import (
    ObjectStoreError,
    assert_object_store_runtime,
    assert_postgresql_runtime,
    configure,
    get_db,
    get_settings,
    health_router,
    init_db,
    isolated_test_boundary_active,
)
from .routers.attachments import router as attachments_router
from .routers.metrics import router as metrics_router
from .routers.notices import router as notices_router
from .routers.pre_specs import router as pre_specs_router
from .routers.opportunities import router as opportunities_router
from .routers.portals import router as portals_router
from .routers.profile import router as profile_router
from .routers.policies import router as policies_router
from .routers.quality_gates import router as quality_gates_router
from .routers.reviews import notice_router as notice_reviews_router
from .routers.reviews import router as reviews_router
from .routers.runs import router as runs_router
from .routers.schedule import router as schedule_router
from .routers.screening import router as screening_router
from .routers.document_bundles import router as document_bundles_router
from .routers.deep_reviews import router as deep_reviews_router
from .routers.bid_delta import router as bid_delta_router
from .routers.reports import router as reports_router
from .routers.order_plans import router as order_plans_router
from .runtime import ApplicationRuntime


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Validate the migrated DB and object store, then own runtime resources.

    Startup is deliberately not an administrator: it never runs Alembic, never
    calls ``create_all`` against the configured database, never seeds portal or
    policy rows, and never contacts a model provider.  It only verifies that
    the ordered postgres-init -> migrate gate already completed.
    """

    configure()

    # The explicit dependency-override escape hatch is for isolated API tests
    # that provide their own in-memory fixture.  It cannot affect the
    # production process because overrides are only installed by callers of
    # the FastAPI application object.  T9 tests inject a runtime factory when
    # they want to exercise the migrated worker lifecycle.
    injected_runtime_factory = getattr(_app.state, "runtime_factory", None)
    using_test_db = get_db in _app.dependency_overrides and not callable(injected_runtime_factory)

    # The process serving production traffic must never silently accept a file
    # database or an unconfigured object store.  Isolated pytest dependency
    # overrides do not reach these preflight checks.
    if not using_test_db and not isolated_test_boundary_active():
        assert_postgresql_runtime()
        try:
            assert_object_store_runtime()
        except ObjectStoreError as error:
            raise RuntimeError(
                "BidOps application runtime requires configured MinIO object storage"
            ) from error

    if not using_test_db:
        init_db()

    runtime = injected_runtime_factory() if callable(injected_runtime_factory) else (
        None if using_test_db else ApplicationRuntime()
    )
    if runtime is not None:
        try:
            runtime.start()
        except Exception:
            runtime.shutdown()
            raise
        _app.state.runtime = runtime
        for name in (
            "pipeline_service",
            "store",
            "orchestrator",
            "worker",
            "scheduler_service",
            "scheduled_pipeline",
            "dispatch_schedule",
        ):
            if hasattr(runtime, name):
                setattr(_app.state, {
                    "store": "screening_store",
                    "orchestrator": "screening_orchestrator",
                    "worker": "screening_worker",
                }.get(name, name), getattr(runtime, name))
    try:
        yield
    finally:
        if runtime is not None:
            runtime.shutdown()
            # A FastAPI application can be entered more than once by tests
            # and by ASGI lifespan managers.  Do not leave closed runtime
            # objects in app.state for the next lifespan.
            for name in (
                "runtime",
                "pipeline_service",
                "screening_store",
                "screening_orchestrator",
                "screening_worker",
                "scheduler_service",
                "scheduled_pipeline",
                "dispatch_schedule",
            ):
                if hasattr(_app.state, name):
                    delattr(_app.state, name)


app = FastAPI(title="BidOps Admin API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; base-uri 'self'; "
        "frame-ancestors 'none'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


app.include_router(health_router)
app.include_router(runs_router)
app.include_router(notices_router)
app.include_router(pre_specs_router)
app.include_router(opportunities_router)
app.include_router(notice_reviews_router)
app.include_router(reviews_router)
app.include_router(metrics_router)
app.include_router(attachments_router)
app.include_router(portals_router)
app.include_router(profile_router)
app.include_router(screening_router)
app.include_router(quality_gates_router)
app.include_router(policies_router)
app.include_router(schedule_router)
app.include_router(document_bundles_router)
app.include_router(deep_reviews_router)
app.include_router(bid_delta_router)
app.include_router(reports_router)
app.include_router(order_plans_router)


class SPAStaticFiles(StaticFiles):
    """Serve built assets and fall back to index.html for client routes."""

    async def get_response(self, path: str, scope) -> Response:  # type: ignore[no-untyped-def]
        request_path = scope.get("path", "")
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as error:
            if error.status_code == 404 and not request_path.startswith("/api"):
                return await super().get_response("index.html", scope)
            raise


FRONTEND_DIST = get_settings().bidops_root / "web" / "frontend" / "dist"


def install_frontend(application: FastAPI, directory: Path = FRONTEND_DIST) -> None:
    """Attach the built frontend without making a missing build fatal."""

    index_path = directory / "index.html"
    if directory.is_dir() and index_path.is_file():
        # This mount is deliberately last so all /api routes win first.
        application.mount(
            "/",
            SPAStaticFiles(directory=str(directory), html=True),
            name="frontend",
        )
        return

    @application.get("/{path:path}", include_in_schema=False)
    def missing_frontend(path: str) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "빌드된 프론트엔드가 없습니다. web/frontend에서 npm run build를 실행하십시오.",
                "path": path,
            },
        )


install_frontend(app)
