"""`BIDOPS_MODULES`가 고르는 것과 고르지 않는 것 (명세 §7).

명세 §7은 다음을 못박는다.

- `BIDOPS_MODULES`는 `lifecycle`·`screening`·`deep_review`의 부분집합이고 기본값은
  셋 전부다. core는 항상 포함된다. **알 수 없는 이름이나 빈 값은 기동 실패**다.
- **의존은 import만, 등록은 지정한 모듈만.** 지정한 모듈이 의존하는 모듈의
  models·seam 함수는 여전히 import되어 동작하지만, router·runtime·확장점 등록은
  지정한 모듈에만 한다.
- `/api/health`는 core가 제공하므로 어떤 조합에서도 있다.
- `runtime.py`는 모듈별 runtime의 조립이다. `app.state`에 올리는 이름 일곱 개는
  router가 쓰므로 유지한다.

이 파일은 그 문장들을 그대로 검사한다. 기본값으로 세운 앱이 분할 전과 같은
경로 집합을 갖는지도 함께 본다 — 그것이 이 이주의 REST 불변 조건이다.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import Base, MODULE_NAMES, Settings, get_db
from app.lifecycle import (
    extension_registry,
    reset_extension_registry,
    restore_extension_registry,
)

# 조립 계층 전체를 한 번 import해 네 모듈의 선언 테이블이 모두 `Base.metadata`에
# 등록되게 한다. 아래 픽스처가 그 metadata로 SQLite 스키마를 만든다.
from app.main import app as assembled_app, create_app
from app.runtime import ApplicationRuntime


BACKEND_ROOT = Path(__file__).resolve().parents[2]

#: 모듈마다 하나씩 고른 대표 경로. 모듈이 켜져 있으면 `expected`가 나오고
#: 꺼져 있으면 404다. deep_review 대표는 본문이 필수인 POST라 DB에 닿기 전에
#: 422가 나므로, "route가 있다"와 "route가 없다"를 확실히 가른다.
LIVE_PROBES: dict[str, tuple[str, str, int]] = {
    "lifecycle": ("GET", "/api/runs", 200),
    "screening": ("GET", "/api/screening/executions", 200),
    "deep_review": ("POST", "/api/notices/1/deep-reviews", 422),
}

#: 명세 §5.3이 말한 "다른 모듈의 경로 접두사를 쓰는 router". 접두사를 소유한
#: 모듈이 아니라 **제공 모듈**이 꺼질 때 사라져야 한다.
CROSS_PREFIX_ROUTES: dict[str, str] = {
    "/api/runs/{run_id}/pipeline/judgment": "screening",
    "/api/notices/{notice_pk}/review": "screening",
    "/api/pre-specs/{notice_id}/company-fit": "deep_review",
    "/api/companies/{company_id}/profile": "deep_review",
    "/api/companies/{company_id}/knowledge-graph": "deep_review",
    "/api/companies/{company_id}/profile-evidence/{evidence_id}": "deep_review",
}


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


@pytest.fixture()
def build_app(session_factory):
    """지정한 모듈만 등록한 앱을 만든다.

    확장점 registry는 프로세스 전역 단일 객체이므로 검사마다 비우고 되돌린다.
    `get_db` override를 걸어 lifespan이 runtime을 만들지 않게 하고(격리 API
    테스트와 같은 경로다), SPA mount는 붙이지 않아 등록되지 않은 `/api` 경로가
    catch-all이 아니라 진짜 404로 떨어지게 한다.
    """

    created: list = []

    def factory(*modules: str):
        previous = extension_registry()
        reset_extension_registry()
        try:
            application = create_app(modules=modules, mount_frontend=False)
        except BaseException:
            restore_extension_registry(previous)
            raise
        registry = extension_registry()
        restore_extension_registry(previous)

        def override():
            with session_factory() as session:
                yield session

        application.dependency_overrides[get_db] = override
        created.append(application)
        return application, registry

    return factory


# --- 설정 파싱과 fail closed ------------------------------------------------


def test_default_modules_are_all_three() -> None:
    assert MODULE_NAMES == ("lifecycle", "screening", "deep_review")
    assert Settings().modules == MODULE_NAMES


def test_modules_are_parsed_in_the_given_order_with_whitespace_trimmed() -> None:
    assert Settings(modules_setting=" deep_review , lifecycle ").modules == (
        "deep_review",
        "lifecycle",
    )
    assert Settings(modules_setting="screening").modules == ("screening",)


@pytest.mark.parametrize("value", ["", "   ", ",", " , "])
def test_an_empty_module_list_fails_closed(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(modules_setting=value)


@pytest.mark.parametrize("value", ["billing", "lifecycle,billing", "core", "Lifecycle"])
def test_an_unknown_module_name_fails_closed(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(modules_setting=value)


def test_create_app_rejects_an_unknown_module_name(build_app) -> None:
    with pytest.raises(ValueError):
        build_app("lifecycle", "billing")


def test_create_app_rejects_an_empty_module_list(build_app) -> None:
    with pytest.raises(ValueError):
        build_app()


@pytest.mark.parametrize("value", ["", "billing", "lifecycle,screening,billing"])
def test_the_process_refuses_to_start_with_a_bad_module_list(
    value: str, tmp_path: Path
) -> None:
    """실제 기동 경로에서의 fail closed.

    `app.core.db`가 import 시점에 `get_settings()`를 부르므로, 잘못된 값은 앱
    객체가 만들어지기 전에 프로세스를 죽인다.
    """

    environment = dict(os.environ)
    environment.pop("BIDOPS_ROOT", None)
    environment.update(
        {
            "BIDOPS_DATA_DIR": str(tmp_path / "data"),
            "BIDOPS_ATTACHMENTS_DIR": str(tmp_path / "attachments"),
            "BIDOPS_DATABASE_URL": f"sqlite:///{tmp_path / 'modules.db'}",
            "PYTHONPATH": str(BACKEND_ROOT),
            "BIDOPS_MODULES": value,
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode != 0, (
        f"BIDOPS_MODULES={value!r} 로 기동이 성공했다. fail closed 여야 한다.\n"
        f"--- stdout ---\n{completed.stdout}"
    )
    assert "BIDOPS_MODULES" in completed.stderr


def test_the_default_process_starts_with_every_module(tmp_path: Path) -> None:
    environment = dict(os.environ)
    environment.pop("BIDOPS_ROOT", None)
    environment.pop("BIDOPS_MODULES", None)
    environment.update(
        {
            "BIDOPS_DATA_DIR": str(tmp_path / "data"),
            "BIDOPS_ATTACHMENTS_DIR": str(tmp_path / "attachments"),
            "BIDOPS_DATABASE_URL": f"sqlite:///{tmp_path / 'modules.db'}",
            "PYTHONPATH": str(BACKEND_ROOT),
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.main; print(len(app.main.app.routes))",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    assert int(completed.stdout.strip()) > 0


# --- 경로 등록 ---------------------------------------------------------------


def _api_paths(application) -> set[str]:
    """등록된 `/api` 경로 템플릿. FastAPI는 `include_router`를 지연 확장하므로
    `application.routes`가 아니라 OpenAPI 문서에서 읽는다."""

    return set(application.openapi()["paths"])


def test_health_is_registered_for_every_module_subset(build_app) -> None:
    for modules in (
        MODULE_NAMES,
        ("lifecycle",),
        ("screening",),
        ("deep_review",),
        ("screening", "deep_review"),
    ):
        application, _ = build_app(*modules)
        with TestClient(application) as client:
            response = client.get("/api/health")
        assert response.status_code == 200, modules
        assert response.json() == {"status": "ok"}


def test_the_default_app_registers_exactly_the_assembled_api_paths(build_app) -> None:
    """기본값으로 만든 앱의 `/api` 경로 집합이 조립된 앱과 같다 (§9 REST 불변)."""

    application, _ = build_app(*MODULE_NAMES)

    assert _api_paths(application) == _api_paths(assembled_app)


def test_module_route_sets_partition_the_default_app(build_app) -> None:
    full, _ = build_app(*MODULE_NAMES)
    parts = {module: _api_paths(build_app(module)[0]) for module in MODULE_NAMES}

    union: set[str] = set()
    for paths in parts.values():
        assert "/api/health" in paths
        union |= paths
    assert union == _api_paths(full)

    # health 말고는 겹치는 경로가 없다.
    for left in MODULE_NAMES:
        for right in MODULE_NAMES:
            if left < right:
                assert parts[left] & parts[right] == {"/api/health"}


@pytest.mark.parametrize("owner", sorted(set(CROSS_PREFIX_ROUTES.values())))
def test_cross_prefix_routes_follow_their_providing_module(build_app, owner) -> None:
    """§5.3: 접두사를 소유한 모듈이 아니라 제공 모듈이 그 경로를 좌우한다."""

    on, _ = build_app(owner)
    off, _ = build_app(*[module for module in MODULE_NAMES if module != owner])

    for path, provider in CROSS_PREFIX_ROUTES.items():
        if provider != owner:
            continue
        assert path in _api_paths(on), path
        assert path not in _api_paths(off), path


@pytest.mark.parametrize("selected", sorted(MODULE_NAMES))
def test_only_the_selected_module_answers(build_app, selected: str) -> None:
    application, _ = build_app(selected)

    with TestClient(application) as client:
        for module, (method, path, expected) in LIVE_PROBES.items():
            response = client.request(method, path)
            if module == selected:
                assert response.status_code == expected, (selected, module, response.text)
            else:
                assert response.status_code == 404, (selected, module, response.text)


def test_the_judgment_route_still_wins_over_the_generic_stage_route(build_app) -> None:
    """등록 순서가 REST 계약의 일부다 (§5.3).

    `/api/runs/{run_id}/pipeline/judgment`(screening)는 회차 router의 일반 단계
    경로 `/api/runs/{run_id}/pipeline/{stage}`(lifecycle)보다 먼저 등록돼야 한다.
    screening 쪽은 본문이 필수라 DB에 닿기 전에 422를 내고, lifecycle의 일반
    단계 경로는 본문이 없어도 되므로 없는 회차에 404를 낸다. 두 응답이 갈리는
    것으로 어느 route가 잡았는지 알 수 있다.
    """

    both, _ = build_app("lifecycle", "screening")
    lifecycle_only, _ = build_app("lifecycle")

    with TestClient(both) as client:
        assert client.post("/api/runs/no-such-run/pipeline/judgment").status_code == 422
    with TestClient(lifecycle_only) as client:
        assert client.post("/api/runs/no-such-run/pipeline/judgment").status_code == 404


def test_every_module_answers_under_the_default_selection(build_app) -> None:
    application, _ = build_app(*MODULE_NAMES)

    with TestClient(application) as client:
        for method, path, expected in LIVE_PROBES.values():
            response = client.request(method, path)
            assert response.status_code == expected, (path, response.text)


# --- 확장점 등록 -------------------------------------------------------------


def test_lifecycle_alone_registers_no_extension_provider(build_app) -> None:
    _, registry = build_app("lifecycle")

    assert registry.judgment_filters_supported is False
    assert registry.overview_filters_supported is False
    assert registry.run_ingest_hook_count == 0
    assert registry.tracking_decision_hook_count == 0


def test_screening_registers_only_its_own_extensions(build_app) -> None:
    _, registry = build_app("screening")

    assert registry.judgment_filters_supported is True
    assert registry.overview_filters_supported is False
    assert registry.run_ingest_hook_count == 1
    assert registry.tracking_decision_hook_count == 0


def test_deep_review_registers_only_its_own_extensions(build_app) -> None:
    _, registry = build_app("deep_review")

    assert registry.judgment_filters_supported is False
    assert registry.overview_filters_supported is True
    assert registry.run_ingest_hook_count == 1
    assert registry.tracking_decision_hook_count == 1


def test_the_default_selection_registers_both_providers(build_app) -> None:
    _, registry = build_app(*MODULE_NAMES)

    assert registry.judgment_filters_supported is True
    assert registry.overview_filters_supported is True
    assert registry.run_ingest_hook_count == 2
    assert registry.tracking_decision_hook_count == 1


# --- 모듈별 runtime ----------------------------------------------------------

#: `app.state`에 올리는 이름과 그것을 소유한 모듈 (§7).
STATE_OWNERS: dict[str, str] = {
    "pipeline_service": "lifecycle",
    "screening_store": "screening",
    "screening_orchestrator": "screening",
    "screening_worker": "screening",
    "scheduler_service": "screening",
    "scheduled_pipeline": "screening",
    "dispatch_schedule": "screening",
}

#: runtime 객체 위의 이름 (`app.state` 이름과 다른 세 개가 있다).
RUNTIME_ATTRIBUTES: dict[str, str] = {
    "pipeline_service": "lifecycle",
    "store": "screening",
    "orchestrator": "screening",
    "worker": "screening",
    "scheduler_service": "screening",
    "scheduled_pipeline": "screening",
    "dispatch_schedule": "screening",
}


@pytest.mark.parametrize("selected", sorted(MODULE_NAMES))
def test_only_the_selected_module_builds_its_runtime(
    selected: str, session_factory, tmp_path: Path
) -> None:
    settings = Settings(
        bidops_root=tmp_path,
        data_dir=tmp_path / "data",
        attachments_dir=tmp_path / "attachments",
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
    )
    runtime = ApplicationRuntime(
        settings, session_factory=session_factory, modules=(selected,)
    )
    try:
        for name, owner in RUNTIME_ATTRIBUTES.items():
            assert hasattr(runtime, name) is (owner == selected), (selected, name)
    finally:
        runtime.shutdown()


def test_the_default_runtime_exposes_every_state_name(
    session_factory, tmp_path: Path
) -> None:
    settings = Settings(
        bidops_root=tmp_path,
        data_dir=tmp_path / "data",
        attachments_dir=tmp_path / "attachments",
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
    )
    runtime = ApplicationRuntime(settings, session_factory=session_factory)
    try:
        for name in RUNTIME_ATTRIBUTES:
            assert hasattr(runtime, name), name
        assert runtime.modules == MODULE_NAMES
    finally:
        runtime.shutdown()


def test_state_names_are_published_for_the_selected_modules_only(
    session_factory, tmp_path: Path, monkeypatch
) -> None:
    """lifespan이 `app.state`에 올리는 이름이 선택을 그대로 따른다 (§7)."""

    settings = Settings(
        bidops_root=tmp_path,
        data_dir=tmp_path / "data",
        attachments_dir=tmp_path / "attachments",
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
    )
    # runtime factory를 주면 lifespan은 격리 테스트가 아니라고 보므로, 이 검사가
    # 실제 DB를 건드리지 않도록 startup의 DB 확인만 비운다.
    monkeypatch.setattr("app.main.init_db", lambda: None)

    for selected in MODULE_NAMES:
        previous = extension_registry()
        reset_extension_registry()
        try:
            application = create_app(modules=(selected,), mount_frontend=False)
        finally:
            restore_extension_registry(previous)

        def factory(selected: str = selected):
            runtime = ApplicationRuntime(
                settings, session_factory=session_factory, modules=(selected,)
            )
            screening_runtime = runtime.runtime_for("screening")
            if screening_runtime is not None:
                # worker 스레드를 실제로 돌리지 않는다. 이 검사가 보는 것은
                # `app.state`에 어떤 이름이 올라가는가뿐이다.
                screening_runtime.worker.run_forever = lambda stop_event: stop_event.wait()
            return runtime

        application.state.runtime_factory = factory
        with TestClient(application):
            for name, owner in STATE_OWNERS.items():
                assert hasattr(application.state, name) is (owner == selected), (
                    selected,
                    name,
                )
        for name in STATE_OWNERS:
            assert not hasattr(application.state, name)


def test_the_scheduler_stays_off_unless_enabled(session_factory, tmp_path: Path) -> None:
    """기본 비활성 (§9). screening runtime이 켜져도 scheduler는 start되지 않는다."""

    settings = Settings(
        bidops_root=tmp_path,
        data_dir=tmp_path / "data",
        attachments_dir=tmp_path / "attachments",
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
    )
    assert settings.scheduler_enabled is False
    runtime = ApplicationRuntime(
        settings, session_factory=session_factory, modules=("screening",)
    )
    started: list[str] = []
    runtime.scheduler_service.start = lambda: started.append("start")  # type: ignore[method-assign]
    runtime.worker.run_forever = lambda stop_event: stop_event.wait()  # type: ignore[method-assign]
    try:
        runtime.start()
        assert started == []
    finally:
        runtime.shutdown()
