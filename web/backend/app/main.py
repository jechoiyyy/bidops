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
from .lifecycle import extension_registry
from .deep_review.routers.deep_reviews import pre_spec_overview_router
from .screening import register_lifecycle_extensions
from .deep_review.services.deep_review_hooks import PreSpecAttachmentEligibilityHook
from .deep_review.services.prespec_projection import PreSpecOverviewDocumentProjection
from .deep_review.routers.attachments import router as attachments_router
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
from .routers.screening import run_router as screening_run_router
from .deep_review.routers.document_bundles import router as document_bundles_router
from .deep_review.routers.deep_reviews import router as deep_reviews_router
from .deep_review.routers.bid_delta import router as bid_delta_router
from .deep_review.routers.reports import router as reports_router
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
# 판정 실행 endpoint 는 회차 경로 아래 있지만 제공 모듈이 screening 이다(§5.3).
# 회차 router 의 일반 단계 경로(`/pipeline/{stage}`)보다 먼저 등록해야 더 구체적인
# 이 경로가 선택된다.
app.include_router(screening_run_router)
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
# deep_review가 제공하는 사전규격 개요 검토 조회 (명세 §5.3). 경로는 pre_specs다.
app.include_router(pre_spec_overview_router)


# --- lifecycle 확장점 등록 구역 (명세 §6) ------------------------------------
# lifecycle은 선별·심층 검토 결과를 확장점으로만 본다. 그 구현을 registry에
# 채우는 것은 조립 계층의 일이며, **앱 객체를 조립하는 이 시점**에 한다 —
# router 등록과 같은 시점이고 lifespan도 `ApplicationRuntime`도 아니다. runtime을
# 만들지 않는 격리 API 테스트(`get_db` override)에서도 projection이 있어야 하기
# 때문이다. 등록은 import와 객체 생성일 뿐이고 migration·seed·정책 활성화·모델
# 호출을 하지 않는다(§9).
#
# 모듈을 제공하는 task는 **아래에 자기 줄을 덧붙이기만** 한다. 기존 줄을 고치지
# 않는다. T8이 `BIDOPS_MODULES` 조건을 붙일 때까지는 무조건 등록이다.
_extensions = extension_registry()
# (여기에 모듈별 등록을 덧붙인다)
# 등록 순서는 `BIDOPS_MODULES`의 기본 순서(lifecycle,screening,deep_review)를 따른다.
# 같은 hook을 여러 모듈이 등록하면 이 순서대로 실행된다(§6.2).
#
# screening: 공고 판정 projection(§6.1)과 판정·리뷰·C-2 회차 적재 hook(§6.2)
register_lifecycle_extensions(_extensions)
# deep_review: 사전규격 개요·문서 projection(§6.1)과 첨부 fetch 자격 갱신 hook(§6.2)
_extensions.register_overview_document_projection(PreSpecOverviewDocumentProjection())
_prespec_attachment_hook = PreSpecAttachmentEligibilityHook()
_extensions.register_run_ingest_hook(_prespec_attachment_hook)
_extensions.register_tracking_decision_hook(_prespec_attachment_hook)


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
