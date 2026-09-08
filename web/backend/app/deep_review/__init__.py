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
#:
#: 표는 **모듈 밖에 실제 소비자가 있는 이름만** 담는다. 구역마다 왜 공개인지를
#: 적어 두었다. 여기 없는 것은 deep_review 내부이며, 상태를 바꾸거나 모델을 부르는
#: 이름은 공개하지 않는다 — 공개하면 조립 계층이 startup에서 부를 수 있게 되고
#: 그것은 §9가 금지한 일이다(`tests/app/test_module_boundaries.py`의 startup 검사).
_EXPORTS: dict[str, tuple[str, str]] = {
    # === 조립이 쓴다 — router 인스턴스 (routers/*.py) ======================
    # `app/main.py`가 `getattr(<모듈>, <router 이름>)`로 가져간다. 정적 import가
    # 없어도 조립에 반드시 필요하다.
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
    # === 확장점 구현 (§6.1·§6.2) ===========================================
    # `register_lifecycle_extensions`가 만드는 객체다. 조립 계층의 등록 검사
    # (`tests/app/test_extension_registration.py`)가 이 이름으로 등록 결과를 본다.
    "PreSpecAttachmentEligibilityHook": (
        ".services.deep_review_hooks",
        "PreSpecAttachmentEligibilityHook",
    ),
    "PreSpecOverviewDocumentProjection": (
        ".services.prespec_projection",
        "PreSpecOverviewDocumentProjection",
    ),
    # === 밖에서 상태를 만든다 — 개요 검토 결과 (models.py) =================
    # 개요 검토 행은 사전규격 화면의 계약이며 두 모듈 조합 테스트가 이 이름으로
    # 상태를 만든다. 그 밖의 deep_review ORM은 모듈 밖으로 나가지 않는다.
    "PreSpecOverviewReview": (".models", "PreSpecOverviewReview"),
    # === 조립이 쓴다 — in-process runtime (runtime.py) =====================
    # `app/runtime.py`가 `package.build_runtime(...)`로 가져간다. runtime 객체의
    # **형**은 조립이 쓰지 않으므로 공개하지 않는다.
    "build_runtime": (".runtime", "build_runtime"),
    # === 별도 worker 진입점이 쓴다 (workers/deep_review.py) ================
    # 조립 계층의 합성 analysis worker가 C-2 claim이 없을 때 부른다.
    "run_deep_review_once": (".workers.deep_review", "run_once"),
    # 개요 실행은 합성 analysis worker의 세 번째 슬롯이다. 개요 전용 process
    # 진입점은 만들지 않는다 — 그러면 모델 슬롯 1개 보장이 깨진다 (§6.3).
    "run_prespec_overview_once": (".workers.prespec_overview", "run_once"),
    "PreSpecCompanyFitRunner": (".services.company_fit_runner", "PreSpecCompanyFitRunner"),
    # 조립 계층이 poll loop **밖에서** 한 번 만들어 들고 있는다. 매 poll 새로
    # 만들면 binding 해석 캐시가 살아남지 못해 idle worker가 poll마다 policy를
    # 다시 읽고 `/models`를 부른다 (§6.3).
    "PreSpecOverviewRunner": (
        ".services.prespec_overview_runner",
        "PreSpecOverviewRunner",
    ),
}


#: registry에 자기 등록을 표시하는 키. lifecycle은 이 문자열의 의미를 해석하지
#: 않고 "같은 등록자인가"만 본다. 같은 키로 다시 등록하면 제자리 교체이므로
#: `create_app()`을 한 프로세스에서 두 번 불러도 hook이 두 번 붙지 않는다.
EXTENSION_OWNER = __name__


def register_lifecycle_extensions(registry=None):
    """deep_review 구현으로 lifecycle 확장점을 채운다 (명세 §6).

    조립 계층이 앱 객체를 만들 때 부른다. import와 객체 생성일 뿐이며
    migration·seed·정책 활성화·모델 호출을 하지 않는다(§9). 같은 registry에 두 번
    불러도 결과가 같다 — 등록은 `EXTENSION_OWNER` 키로 제자리 교체된다.

    - 사전규격 개요·문서 projection (§6.1)
    - 첨부 fetch 자격을 다시 세는 회차 적재·추적 결정·등급 변경 hook (§6.2)
    """

    from .services.deep_review_hooks import PreSpecAttachmentEligibilityHook
    from .services.prespec_projection import PreSpecOverviewDocumentProjection

    if registry is None:
        from ..lifecycle import extension_registry

        registry = extension_registry()
    registry.register_overview_document_projection(
        PreSpecOverviewDocumentProjection(), owner=EXTENSION_OWNER
    )
    hook = PreSpecAttachmentEligibilityHook()
    registry.register_run_ingest_hook(hook, owner=EXTENSION_OWNER)
    registry.register_tracking_decision_hook(hook, owner=EXTENSION_OWNER)
    # 사람 리뷰가 정정 등급을 바꾼 뒤 선별이 registry로 부르는 확장점 (§6.2).
    registry.register_effective_grade_changed_hook(hook, owner=EXTENSION_OWNER)
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
    from .runtime import build_runtime
    from .workers.deep_review import run_once as run_deep_review_once
    from .workers.prespec_overview import run_once as run_prespec_overview_once
    from .services.prespec_overview_runner import PreSpecOverviewRunner
    from .services.deep_review_hooks import PreSpecAttachmentEligibilityHook
    from .services.prespec_projection import PreSpecOverviewDocumentProjection
