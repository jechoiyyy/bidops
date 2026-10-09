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
    parse_modules,
)
from . import deep_review, lifecycle, screening
from .runtime import ApplicationRuntime


#: 모듈 이름 → 그 모듈의 공개 표면. 조립 계층은 이 표를 통해서만 모듈에 닿고
#: 모듈 내부 경로를 알지 못한다(명세 §4).
_MODULE_PACKAGES = {
    "lifecycle": lifecycle,
    "screening": screening,
    "deep_review": deep_review,
}

#: `include_router` 순서 (명세 §5.3·§7).
#:
#: 값은 `(제공 모듈, 그 모듈의 공개 router 이름)`이며 **순서가 REST 계약의
#: 일부**다. `/api/runs/{run_id}/pipeline/judgment`(screening)는 회차 router의
#: 일반 단계 경로 `/api/runs/{run_id}/pipeline/{stage}`(lifecycle)보다 먼저
#: 등록해야 더 구체적인 이 경로가 선택된다. 그래서 등록 순서는 모듈 단위로
#: 묶지 않고 여기서 한 줄씩 못박는다. 고르지 않은 모듈의 줄은 건너뛴다 —
#: 그 모듈의 router는 import조차 되지 않는다.
_ROUTER_REGISTRATION: tuple[tuple[str, str], ...] = (
    ("screening", "screening_run_router"),
    ("lifecycle", "runs_router"),
    ("lifecycle", "companies_router"),
    ("lifecycle", "notices_router"),
    ("lifecycle", "pre_specs_router"),
    ("lifecycle", "opportunities_router"),
    ("lifecycle", "workload_router"),
    ("screening", "notice_reviews_router"),
    ("screening", "reviews_router"),
    ("lifecycle", "metrics_router"),
    ("deep_review", "attachments_router"),
    ("lifecycle", "portals_router"),
    ("screening", "profile_router"),
    ("screening", "screening_router"),
    ("screening", "quality_gates_router"),
    ("screening", "policies_router"),
    ("screening", "schedule_router"),
    ("deep_review", "document_bundles_router"),
    ("deep_review", "deep_reviews_router"),
    ("deep_review", "assumption_analysis_router"),
    ("deep_review", "bid_decision_queue_router"),
    ("deep_review", "bid_delta_router"),
    ("deep_review", "reports_router"),
    ("screening", "order_plans_router"),
    ("screening", "order_plan_policies_router"),
    ("screening", "order_plan_daily_trigger_router"),
    ("screening", "order_plan_quality_gates_router"),
    ("screening", "order_plan_audit_sample_router"),
    # deep_review가 제공하는 사전규격 개요 검토 조회 (§5.3). 경로는 pre_specs다.
    ("deep_review", "pre_spec_overview_router"),
    ("deep_review", "prespec_overviews_router"),
)

#: lifecycle 확장점을 채우는 모듈 (명세 §6). lifecycle 자신은 registry를
#: 소유할 뿐 채우지 않는다.
_EXTENSION_PROVIDERS: tuple[str, ...] = ("screening", "deep_review")


def selected_modules(modules=None) -> tuple[str, ...]:
    """등록할 모듈을 지정 순서대로 낸다 (명세 §7).

    `modules`가 ``None``이면 `BIDOPS_MODULES`(기본값 세 모듈 전부)를 쓴다.
    알 수 없는 이름이나 빈 목록은 예외다 — fail closed.
    """

    if modules is None:
        return get_settings().modules
    return parse_modules(",".join(modules))


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

    # 어떤 모듈의 runtime을 만들지는 앱을 조립할 때 이미 정해졌다(§7).
    runtime = injected_runtime_factory() if callable(injected_runtime_factory) else (
        None
        if using_test_db
        else ApplicationRuntime(modules=getattr(_app.state, "modules", None))
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


def _is_demo_only_path(path: str) -> bool:
    """Paths hidden as absent unless the isolated demo is enabled."""

    if path in {"/companies", "/api/companies"}:
        return True
    if path.startswith(("/companies/", "/api/companies/")):
        return True
    parts = path.strip("/").split("/")
    if parts and parts[0] == "api":
        parts = parts[1:]
    return (
        len(parts) == 3
        and parts[0] == "pre-specs"
        and bool(parts[1])
        and parts[2] == "company-comparison"
    )


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


def create_app(modules=None, *, mount_frontend: bool = True) -> FastAPI:
    """지정한 모듈만 등록한 애플리케이션을 조립한다 (명세 §7).

    `modules`가 ``None``이면 `BIDOPS_MODULES`를 쓴다. core는 항상 포함되므로
    `/api/health`는 어떤 조합에서도 있다. CORS·보안 헤더·SPA mount는 모듈 선택과
    무관하게 그대로다.

    등록은 **import와 객체 생성일 뿐**이다. migration·seed·정책 활성화·모델
    호출을 하지 않고 스레드도 만들지 않는다(§9). 상시 자원은 lifespan이 만드는
    모듈 runtime의 몫이다.
    """

    modules = selected_modules(modules)
    application = FastAPI(title="BidOps Admin API", lifespan=lifespan)
    # lifespan이 어떤 모듈 runtime을 만들지 여기서 정한다.
    application.state.modules = modules

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def security_headers(request, call_next):  # type: ignore[no-untyped-def]
        if not get_settings().demo_enabled and _is_demo_only_path(request.url.path):
            # Behave exactly like an unregistered route. In particular this
            # runs before UUID conversion and before the SPA fallback.
            response = JSONResponse(status_code=404, content={"detail": "Not Found"})
        else:
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

    # `/api/health`는 어느 도메인 모듈에도 속하지 않으므로 core가 제공한다(§7).
    application.include_router(health_router)

    @application.get("/api/demo-config", include_in_schema=False)
    def demo_config() -> dict[str, bool]:
        # This endpoint is always present and intentionally returns one bit.
        # Reading it does not seed, migrate, activate, or enqueue anything.
        return {"enabled": bool(get_settings().demo_enabled)}

    for owner, router_name in _ROUTER_REGISTRATION:
        if owner in modules:
            application.include_router(getattr(_MODULE_PACKAGES[owner], router_name))

    # --- lifecycle 확장점 등록 구역 (명세 §6) --------------------------------
    # lifecycle은 선별·심층 검토 결과를 확장점으로만 본다. 그 구현을 registry에
    # 채우는 것은 조립 계층의 일이며, **앱 객체를 조립하는 이 시점**에 한다 —
    # router 등록과 같은 시점이고 lifespan도 모듈 runtime도 아니다. runtime을
    # 만들지 않는 격리 API 테스트(`get_db` override)에서도 projection이 있어야
    # 하기 때문이다.
    #
    # 등록 순서는 `BIDOPS_MODULES`가 준 순서를 따른다. 같은 hook을 여러 모듈이
    # 등록하면 이 순서대로 실행된다(§6.2).
    #
    # 채워지는 자리: 판정 projection(screening), 개요·문서 projection(deep_review),
    # 회차 적재 hook(screening·deep_review), 추적 결정 hook(deep_review),
    # **등급 변경 hook(deep_review)**. 마지막 것은 사람 리뷰가 `corrected_grade`를
    # 바꾼 뒤 screening이 registry로 부르는 자리이며, 제공자가 없으면 no-op이다.
    registry = lifecycle.extension_registry()
    for name in modules:
        if name in _EXTENSION_PROVIDERS:
            _MODULE_PACKAGES[name].register_lifecycle_extensions(registry)

    if mount_frontend:
        install_frontend(application)
    return application


app = create_app()
