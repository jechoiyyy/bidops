"""문서 준비·사전규격 개요 검토·심층 검토·입찰 delta와 최종 결정.

deep_review는 core와 lifecycle을 import하고, screening은 §6.3의 읽기 전용 seam
함수(`current_judgment`·`current_judgments`·`latest_corrected_grade`)로만 본다.

이 `__init__`이 deep_review의 **공개 표면**이다. 조립 계층은 여기 있는 이름만
쓰고 `app.deep_review.<하위 경로>`를 직접 들지 않는다(명세 §4).

이름은 lifecycle·screening과 같은 방식으로 **지연 해석**한다. 패키지 초기화가
아무것도 import하지 않으므로 `python -m app.deep_review.workers.document` 같은
worker 진입점이 router·service 전체를 지고 시작하지 않고, router 인스턴스를
공개 이름으로 올려도 import 순환이 생기지 않는다.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

#: 공개 이름 → (구현 모듈, 그 모듈 안의 이름).
_EXPORTS: dict[str, tuple[str, str]] = {
    # --- 조립 계층이 등록하는 router 인스턴스 (routers/*.py) ---------------
    # `attachments_router`·`document_bundles_router`·`deep_reviews_router`와
    # `pre_spec_overview_router`는 lifecycle의 경로 접두사(`/api/notices`,
    # `/api/pre-specs`)를 쓰지만 제공 모듈은 deep_review다(§5.3).
    # deep_review를 끄면 그 경로도 404다.
    "attachments_router": (".routers.attachments", "router"),
    "bid_delta_router": (".routers.bid_delta", "router"),
    "deep_reviews_router": (".routers.deep_reviews", "router"),
    "document_bundles_router": (".routers.document_bundles", "router"),
    "pre_spec_overview_router": (".routers.deep_reviews", "pre_spec_overview_router"),
    "reports_router": (".routers.reports", "router"),
    # --- lifecycle 확장점 구현 (§6.1·§6.2) ---------------------------------
    "PreSpecAttachmentEligibilityHook": (
        ".services.deep_review_hooks",
        "PreSpecAttachmentEligibilityHook",
    ),
    "PreSpecOverviewDocumentProjection": (
        ".services.prespec_projection",
        "PreSpecOverviewDocumentProjection",
    ),
    # --- 개요 검토 결과 (models.py) ----------------------------------------
    # 개요 검토 행은 사전규격 화면의 계약이며 두 모듈 조합 테스트가 이 이름으로
    # 상태를 만든다. 그 밖의 deep_review ORM은 모듈 밖으로 나가지 않는다.
    "PreSpecOverviewReview": (".models", "PreSpecOverviewReview"),
    # --- in-process runtime (runtime.py) -----------------------------------
    "DeepReviewRuntime": (".runtime", "DeepReviewRuntime"),
    "build_runtime": (".runtime", "build_runtime"),
    # --- 별도 worker 프로세스가 쓰는 심층 검토 1건 처리 --------------------
    # 조립 계층의 합성 analysis worker가 C-2 claim이 없을 때 부른다.
    "run_deep_review_once": (".workers.deep_review", "run_once"),
}


def register_lifecycle_extensions(registry=None):
    """deep_review 구현으로 lifecycle 확장점을 채운다 (명세 §6).

    조립 계층이 앱 객체를 만들 때 한 번 부른다. import와 객체 생성일 뿐이며
    migration·seed·정책 활성화·모델 호출을 하지 않는다(§9).

    - 사전규격 개요·문서 projection (§6.1)
    - 첨부 fetch 자격을 다시 세는 회차 적재·추적 결정 hook (§6.2)
    """

    from .services.deep_review_hooks import PreSpecAttachmentEligibilityHook
    from .services.prespec_projection import PreSpecOverviewDocumentProjection

    if registry is None:
        from ..lifecycle import extension_registry

        registry = extension_registry()
    registry.register_overview_document_projection(PreSpecOverviewDocumentProjection())
    hook = PreSpecAttachmentEligibilityHook()
    registry.register_run_ingest_hook(hook)
    registry.register_tracking_decision_hook(hook)
    return registry


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    # 한 번 푼 이름은 모듈에 심어 다음부터 `__getattr__`을 거치지 않게 한다.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = sorted(set(_EXPORTS) | {"register_lifecycle_extensions"})


if TYPE_CHECKING:  # pragma: no cover - 정적 분석용 이름 노출
    from .models import PreSpecOverviewReview
    from .runtime import DeepReviewRuntime, build_runtime
    from .services.deep_review_hooks import PreSpecAttachmentEligibilityHook
    from .services.prespec_projection import PreSpecOverviewDocumentProjection
