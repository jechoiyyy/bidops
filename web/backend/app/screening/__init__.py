"""Qwen 기반 판정 실행 경계와 불변 입력 저장소.

screening은 core와 lifecycle 공개 이름만 import하고 deep_review를 알지 못한다
(명세 §4). 이 `__init__`이 screening의 **공개 표면**이다. 조립 계층은 여기 있는
이름만 쓰고, deep_review는 §6.3이 정한 읽기 전용 seam 함수
(`current_judgment`·`current_judgments`·`latest_corrected_grade`)만 쓴다.

이름은 lifecycle과 같은 방식으로 **지연 해석**한다. 패키지 초기화가 아무것도
import하지 않으므로 `python -m app.screening.cli` 같은 진입점이 모듈 전체를 지고
시작하지 않고, router 인스턴스를 공개 이름으로 올려도 import 순환이 생기지
않는다. 공개 이름과 동작은 그대로다.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

#: 공개 이름 → (구현 모듈, 그 모듈 안의 이름).
#:
#: 표는 **모듈 밖에 실제 소비자가 있는 이름만** 담는다. 구역마다 왜 공개인지를
#: 적어 두었다. 여기 없는 것은 screening 내부이며, 모듈 밖에서 쓰고 싶으면 표에
#: 올리는 것이 곧 그 결정이다. 특히 정책 활성화·seed·모델 호출처럼 **상태를 바꾸는
#: 이름은 공개하지 않는다** — 공개하면 조립 계층이 startup에서 부를 수 있게 되고
#: 그것은 §9가 금지한 일이다(`tests/app/test_module_boundaries.py`의 startup 검사).
_EXPORTS: dict[str, tuple[str, str]] = {
    # === 형제 모듈이 쓴다 ==================================================
    # deep_review가 §6.3의 읽기 전용 seam으로만 판정에 닿는다. 판정 ORM·service는
    # 모듈 밖으로 나가지 않는다.
    "current_judgment": (".projection", "current_judgment"),
    "current_judgments": (".projection", "current_judgments"),
    "latest_corrected_grade": (".projection", "latest_corrected_grade"),
    # 목록 projection과 자격 재평가는 공고 수백 건을 한 번에 다룬다. 명세 §8이
    # 그 자리에 N+1을 금지하므로 단건 판과 나란히 batch 판도 seam에 둔다.
    "latest_corrected_grades": (".projection", "latest_corrected_grades"),
    # === 확장점 구현과 그 seam 자료형 (§6.1·§6.2) ==========================
    # `register_lifecycle_extensions`가 만드는 객체와 seam 함수가 돌려주는 값의
    # 형이다. 모듈 밖 검사(`tests/screening/`)가 이 이름으로 확장점 계약을 본다.
    "CorrectedGrade": (".projection", "CorrectedGrade"),
    "JudgmentSummary": (".projection", "JudgmentSummary"),
    "ScreeningJudgmentProjection": (".projection", "ScreeningJudgmentProjection"),
    "ScreeningWorkloadProjection": (".projection", "ScreeningWorkloadProjection"),
    "ScreeningRunIngestHook": (".ingest", "ScreeningRunIngestHook"),
    # === 일회성 SQLite 이전 도구가 쓴다 ====================================
    # legacy 개정 행을 지금의 payload 계약으로 다시 쓸 때 같은 정규화를 복제하지
    # 않으려고 screening이 공개한다(`app/migrations/import_sqlite.py`).
    "JUDGMENT_PAYLOAD_SCHEMA": (".services.revisions", "JUDGMENT_PAYLOAD_SCHEMA"),
    "REVIEW_PAYLOAD_SCHEMA": (".services.revisions", "REVIEW_PAYLOAD_SCHEMA"),
    "canonical_payload_and_hash": (".services.revisions", "canonical_payload_and_hash"),
    "review_revision_payload": (".services.reviews", "review_revision_payload"),
    # === 조립이 쓴다 — router 인스턴스 (routers/*.py) ======================
    # `app/main.py`가 `getattr(<모듈>, <router 이름>)`로 가져간다. 정적 import가
    # 없어도 조립에 반드시 필요하다.
    # `notice_reviews_router`와 `screening_run_router`는 다른 모듈의 경로
    # 접두사(`/api/notices`, `/api/runs`)를 쓰지만 제공 모듈은 screening이다
    # (§5.3). screening을 끄면 그 경로도 404다.
    "notice_reviews_router": (".routers.reviews", "notice_router"),
    "order_plan_daily_trigger_router": (".routers.order_plan_daily_trigger", "router"),
    "order_plan_policies_router": (".routers.order_plan_policies", "router"),
    "order_plans_router": (".routers.order_plans", "router"),
    "policies_router": (".routers.policies", "router"),
    "profile_router": (".routers.profile", "router"),
    "quality_gates_router": (".routers.quality_gates", "router"),
    "reviews_router": (".routers.reviews", "router"),
    "schedule_router": (".routers.schedule", "router"),
    "screening_router": (".routers.screening", "router"),
    "screening_run_router": (".routers.screening", "run_router"),
    # === 조립이 쓴다 — in-process runtime (runtime.py) =====================
    # `app/runtime.py`가 `package.build_runtime(...)`로 가져간다. runtime 객체의
    # **형**은 조립이 쓰지 않으므로 공개하지 않는다.
    "build_runtime": (".runtime", "build_runtime"),
    # === 별도 worker 진입점이 쓴다 (workers/order_plan.py) =================
    # 조립 계층의 합성 analysis worker가 C-2 claim을 먼저 시도할 때 쓴다.
    "C2ScreeningWorker": (".workers.order_plan", "C2ScreeningWorker"),
}


#: registry에 자기 등록을 표시하는 키. lifecycle은 이 문자열의 의미를 해석하지
#: 않고 "같은 등록자인가"만 본다. 같은 키로 다시 등록하면 제자리 교체이므로
#: `create_app()`을 한 프로세스에서 두 번 불러도 hook이 두 번 붙지 않는다.
EXTENSION_OWNER = __name__


def register_lifecycle_extensions(registry=None):
    """screening 구현으로 lifecycle 확장점을 채운다 (명세 §6).

    조립 계층이 앱 객체를 만들 때 부른다. import와 객체 생성일 뿐이며
    migration·seed·정책 활성화·모델 호출을 하지 않는다(§9). 같은 registry에 두 번
    불러도 결과가 같다 — 등록은 `EXTENSION_OWNER` 키로 제자리 교체된다.
    """

    from .ingest import ScreeningRunIngestHook
    from .projection import ScreeningJudgmentProjection, ScreeningWorkloadProjection

    if registry is None:
        from ..lifecycle import extension_registry

        registry = extension_registry()
    registry.register_judgment_projection(
        ScreeningJudgmentProjection(), owner=EXTENSION_OWNER
    )
    registry.register_run_ingest_hook(ScreeningRunIngestHook(), owner=EXTENSION_OWNER)
    registry.register_workload_projection(ScreeningWorkloadProjection(), owner=EXTENSION_OWNER)
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
    from .ingest import ScreeningRunIngestHook
    from .projection import (
        CorrectedGrade,
        JudgmentSummary,
        ScreeningJudgmentProjection,
        ScreeningWorkloadProjection,
        current_judgment,
        current_judgments,
        latest_corrected_grade,
        latest_corrected_grades,
    )
    from .runtime import build_runtime
    from .services.reviews import review_revision_payload
    from .services.revisions import (
        JUDGMENT_PAYLOAD_SCHEMA,
        REVIEW_PAYLOAD_SCHEMA,
        canonical_payload_and_hash,
    )
    from .workers.order_plan import C2ScreeningWorker
