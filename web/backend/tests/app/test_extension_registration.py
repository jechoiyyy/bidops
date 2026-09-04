"""조립 계층이 앱 객체를 만들 때 확장점을 등록한다 (명세 §6·§9).

등록은 **소유 모듈(owner)** 단위이므로 같은 조립을 두 번 해도 자리는 하나다.
이 파일은 그 두 가지를 함께 본다 — 등록이 실제로 일어나는가, 그리고 `create_app()`을
한 프로세스에서 두 번 불러도 예외 없이 같은 상태로 끝나는가.
"""

from __future__ import annotations

import pytest

from app.lifecycle import extension_registry, reset_extension_registry, restore_extension_registry
from app.main import app, create_app  # noqa: F401 — import 자체가 등록 시점이다
from app.deep_review import (
    PreSpecAttachmentEligibilityHook,
    PreSpecOverviewDocumentProjection,
)


def test_app_assembly_registers_the_overview_document_projection():
    registry = extension_registry()

    assert registry.overview_filters_supported is True
    assert isinstance(registry.overview_document_projection, PreSpecOverviewDocumentProjection)


def test_app_assembly_registers_the_prespec_attachment_hooks():
    registry = extension_registry()

    assert registry.run_ingest_hook_count >= 1
    assert registry.tracking_decision_hook_count >= 1
    assert any(
        isinstance(hook, PreSpecAttachmentEligibilityHook) for hook in registry._run_ingest_hooks.values()
    )
    assert any(
        isinstance(hook, PreSpecAttachmentEligibilityHook) for hook in registry._tracking_hooks.values()
    )


# --- `create_app()`을 두 번 부를 수 있다 -------------------------------------
#
# 전역 registry에 등록하므로, 두 번 조립하면 같은 owner가 같은 자리에 다시
# 등록한다. 그것이 예외가 되면 `uvicorn --factory app.main:create_app`이 죽고,
# 반대로 가드를 그냥 없애면 hook이 두 번 붙어 회차 적재가 두 번 실행된다.
# 아래 검사들이 두 실패 모드를 함께 막는다.


def _paths(application) -> set[str]:
    """등록된 경로 집합. `application.routes`가 아니라 OpenAPI 문서에서 읽는다."""

    return set(application.openapi()["paths"])


@pytest.fixture()
def isolated_registry():
    """검사가 쓰고 버릴 registry. 끝나면 조립 시점의 객체를 되돌린다."""

    previous = extension_registry()
    try:
        yield reset_extension_registry()
    finally:
        restore_extension_registry(previous)


def test_create_app_can_be_called_twice_in_one_process(isolated_registry):
    """factory 방식(`uvicorn --factory`)이 쓰는 경로다. 두 번째 호출이 죽지 않는다."""

    first = create_app(mount_frontend=False)
    second = create_app(mount_frontend=False)

    assert first is not second
    # 두 앱 모두 같은 경로 집합을 갖는다 — 두 번째가 반쯤 조립되지 않는다.
    assert _paths(first) == _paths(second)
    assert "/api/health" in _paths(first)


def test_a_second_assembly_does_not_stack_hooks(isolated_registry):
    """이번 수정의 핵심 회귀 방지 — 두 번 조립해도 hook이 두 번 붙지 않는다.

    붙으면 `ingest_run`이 hook을 두 번 실행해 판정·리뷰 건수가 두 배가 된다.
    옛 중복 등록 가드는 그것을 막은 것이 아니라 예외로 가리고 있었다.
    """

    create_app(mount_frontend=False)
    registry = extension_registry()
    once = (registry.run_ingest_hook_count, registry.tracking_decision_hook_count)

    create_app(mount_frontend=False)

    assert (registry.run_ingest_hook_count, registry.tracking_decision_hook_count) == once
    assert registry.run_ingest_hook_count == 2  # screening + deep_review
    assert registry.tracking_decision_hook_count == 1  # deep_review


def test_both_apps_still_see_the_registered_projections(isolated_registry):
    """두 번 조립한 뒤에도 projection이 비지 않는다 (격리 API 테스트의 전제)."""

    create_app(mount_frontend=False)
    create_app(mount_frontend=False)
    registry = extension_registry()

    assert registry.judgment_filters_supported is True
    assert registry.overview_filters_supported is True
    assert isinstance(registry.overview_document_projection, PreSpecOverviewDocumentProjection)


def test_a_different_owner_still_conflicts(isolated_registry):
    """진짜 충돌 — 다른 모듈이 이미 찬 자리를 채우려 하면 그대로 조립 오류다."""

    from app.screening import register_lifecycle_extensions

    register_lifecycle_extensions(isolated_registry)

    with pytest.raises(RuntimeError):
        isolated_registry.register_judgment_projection(object(), owner="somebody-else")


def test_create_app_is_usable_as_a_factory(isolated_registry):
    """`uvicorn --factory`가 하는 일 — 호출 가능한 factory로 앱을 얻는다."""

    factory = create_app

    application = factory(mount_frontend=False)

    assert callable(factory)
    assert "/api/health" in _paths(application)
