"""수집 회차·기회 identity·첨부 메타·포털·추적 결정.

lifecycle은 core만 import하고 screening·deep_review의 존재를 알지 못한다(명세 §4).
자기 화면·흐름이 그 모듈들의 결과를 함께 써야 하는 자리는 `extensions`의 확장점으로
뒤집혀 있다.

이 `__init__`이 lifecycle의 **공개 표면**이다. screening·deep_review는 lifecycle
테이블에 쓰거나 잠글 때 여기 있는 함수만 쓰고, 조립 계층은 여기 있는 이름만 쓴다.
읽기·join은 `lifecycle.models`의 모델 클래스로 직접 해도 된다(§4 세부 규칙). 같은
이유로 선언적 계약인 `lifecycle.schemas`의 DTO와 `lifecycle.ingest.contracts`의
회차 산출물 계약도 형제 모듈이 직접 받는다. **동작**(loader·service·router)은 여기
있는 이름으로만 받는다.

이름은 **지연 해석**한다. 모듈 수준에서 `.api`를 곧바로 import하면
`app.lifecycle` → `api` → `ingest.loader` → `lifecycle.models` 순환이 생겨
`python -m app.screening.cli` 같은 진입점이 죽는다(T6의 models 분할이 만든 회귀).
지연 해석은 패키지 초기화를 즉시 끝내므로 어떤 import 순서로 들어와도 순환이
성립하지 않는다. 공개 이름과 동작은 그대로다.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

#: 공개 이름 → (구현 모듈, 그 모듈 안의 이름).
#: 이름이 같으면 두 번째 값을 생략한다.
#:
#: 표는 **모듈 밖에 실제 소비자가 있는 이름만** 담는다. 구역마다 왜 공개인지를
#: 적어 두었다. 여기 없는 것은 lifecycle 내부이며, 형제 모듈이나 조립이 쓰고 싶으면
#: 표에 올리는 것이 곧 그 결정이다. 상태를 바꾸는 이름을 근거 없이 올리면 조립
#: 계층이 startup에서 부를 수 있게 된다 — 그것은 §9가 금지한 일이고
#: `tests/app/test_module_boundaries.py`의 startup 검사가 막는다.
_EXPORTS: dict[str, tuple[str, str]] = {
    # === 형제 모듈이 쓴다 — 회차·공고·첨부 메타 쓰기와 잠금 (api.py) =======
    # lifecycle 테이블에 쓰거나 잠그는 일은 형제 모듈이 직접 하지 않고 반드시
    # 이 함수들을 거친다(경계 검사 5의 실체).
    "attachment_download_url": (".api", "attachment_download_url"),
    "delete_manual_attachment": (".api", "delete_manual_attachment"),
    "delete_run": (".api", "delete_run"),
    "ingest_run": (".api", "ingest_run"),
    "load_order_plan_artifact": (".api", "load_order_plan_artifact"),
    "lock_active_attachments": (".api", "lock_active_attachments"),
    "lock_attachment": (".api", "lock_attachment"),
    "lock_notice": (".api", "lock_notice"),
    "mirror_notice_observation": (".api", "mirror_notice_observation"),
    "record_ingest_warning": (".api", "record_ingest_warning"),
    "register_attachment": (".api", "register_attachment"),
    "register_manual_attachment": (".api", "register_manual_attachment"),
    # === 조립이 쓴다 — router 인스턴스 (routers/*.py) ======================
    # `app/main.py`가 `getattr(<모듈>, <router 이름>)`로 가져간다. 정적 import가
    # 없어도 조립에 반드시 필요하다. 이름은 "무엇의 router인가"로 짓는다 —
    # 조립 계층은 이 이름만 보고 등록 순서를 정하며 router 파일 경로를 알지
    # 못한다(§4).
    "metrics_router": (".routers.metrics", "router"),
    "notices_router": (".routers.notices", "router"),
    "opportunities_router": (".routers.opportunities", "router"),
    "portals_router": (".routers.portals", "router"),
    "pre_specs_router": (".routers.pre_specs", "router"),
    "runs_router": (".routers.runs", "router"),
    "workload_router": (".routers.workload", "router"),
    # === 조립이 쓴다 — in-process runtime (runtime.py) =====================
    # `app/runtime.py`가 `package.build_runtime(...)`로 가져간다. runtime 객체의
    # **형**은 조립이 쓰지 않으므로 공개하지 않는다.
    "build_runtime": (".runtime", "build_runtime"),
    # === 확장점 정의와 registry (extensions.py) ============================
    # 형제 모듈이 확장점을 구현하고, 조립이 registry에 등록하며, 테스트가 그
    # 계약을 검사한다. `ClaimedDirectoryLoad`는 `RunDirectoryClaim.load`의 형일
    # 뿐이라 밖에서 이름으로 받지 않는다 — 공개하지 않는다.
    "EffectiveGradeChangedHook": (".extensions", "EffectiveGradeChangedHook"),
    "ExtensionRegistry": (".extensions", "ExtensionRegistry"),
    "JudgmentProjection": (".extensions", "JudgmentProjection"),
    "OverviewDocumentProjection": (".extensions", "OverviewDocumentProjection"),
    "PreSpecDocumentCounts": (".extensions", "PreSpecDocumentCounts"),
    "RunDirectoryClaim": (".extensions", "RunDirectoryClaim"),
    "RunIngestCounts": (".extensions", "RunIngestCounts"),
    "RunIngestHook": (".extensions", "RunIngestHook"),
    "TrackingDecisionHook": (".extensions", "TrackingDecisionHook"),
    "WorkloadCount": (".extensions", "WorkloadCount"),
    "WorkloadProjection": (".extensions", "WorkloadProjection"),
    "extension_registry": (".extensions", "extension_registry"),
    "reset_extension_registry": (".extensions", "reset_extension_registry"),
    "restore_extension_registry": (".extensions", "restore_extension_registry"),
    # === 형제 모듈이 쓴다 — 추적 관계 판정 =================================
    "active_opportunity_predicate": (".services.opportunity_integrity", "active_opportunity_predicate"),
    "authoritative_link_predicate": (".services.opportunity_integrity", "authoritative_link_predicate"),
    "tracked_order_plan_connections": (
        ".services.opportunity_connections",
        "tracked_order_plan_connections",
    ),
    # === 형제 모듈이 쓴다 — 응답 helper (routers/common.py) ================
    # `get_run_or_404`은 사람이 쓰는 회차 디렉터리 이름까지 풀고 없으면 404를
    # 낸다. 잠그지도 404를 내지도 않는 단순 조회(`api.get_run`)는 밖에서 쓰는
    # 곳이 없으므로 공개하지 않는다.
    "get_run_or_404": (".routers.common", "get_run"),
    "notice_list_item": (".routers.common", "notice_list_item"),
    # === 형제 모듈이 쓴다 — 회차 산출물을 읽는 공통 helper (ingest/loader.py)
    # 판정 적재를 맡은 모듈이 **같은 바이트를 같은 규칙으로** 읽어야 하므로
    # 복제하지 않고 lifecycle이 공개한다(§4의 허용 방향). loader 안에서는
    # 이름 앞에 `_`가 붙은 것이 있지만, 공개 표면에서는 밑줄 없는 이름으로
    # 낸다. 값과 동작은 loader의 정의 그대로다.
    "EXECUTION_ID_RE": (".ingest.loader", "EXECUTION_ID_RE"),
    "ORDER_PLAN_FILE": (".ingest.loader", "ORDER_PLAN_FILE"),
    "ORDER_PLAN_FIELD_ALIASES": (".ingest.loader", "_ORDER_PLAN_FIELD_ALIASES"),
    "SCREENING_COMMON_NOTICE_KEYS": (".ingest.loader", "_SCREENING_COMMON_NOTICE_KEYS"),
    "SCREENING_INPUT_KEYS": (".ingest.loader", "_SCREENING_INPUT_KEYS"),
    "SHA256_RE": (".ingest.loader", "SHA256_RE"),
    "V3_GENERATION_SCHEMAS": (".ingest.loader", "V3_GENERATION_SCHEMAS"),
    "artifact_unknown_fields": (".ingest.loader", "_artifact_unknown_fields"),
    "is_aware_iso": (".ingest.loader", "_is_aware_iso"),
    "normalize_v3_generation_binding": (
        ".ingest.loader",
        "_normalize_v3_generation_binding",
    ),
    "order_plan_items": (".ingest.loader", "_order_plan_items"),
    "plan_text": (".ingest.loader", "_plan_text"),
    "raw_list": (".ingest.loader", "_raw_list"),
    "read_optional_json": (".ingest.loader", "_read_optional_json"),
    "read_screening_input": (".ingest.loader", "_read_screening_input"),
    "screening_input_error": (".ingest.loader", "_screening_input_error"),
}


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


__all__ = sorted(_EXPORTS)


if TYPE_CHECKING:  # pragma: no cover - 정적 분석용 이름 노출
    from .api import (
        attachment_download_url,
        delete_manual_attachment,
        delete_run,
        ingest_run,
        load_order_plan_artifact,
        lock_active_attachments,
        lock_attachment,
        lock_notice,
        mirror_notice_observation,
        record_ingest_warning,
        register_attachment,
        register_manual_attachment,
    )
    from .runtime import build_runtime
    from .extensions import (
        EffectiveGradeChangedHook,
        ExtensionRegistry,
        JudgmentProjection,
        OverviewDocumentProjection,
        PreSpecDocumentCounts,
        RunDirectoryClaim,
        RunIngestCounts,
        RunIngestHook,
        TrackingDecisionHook,
        WorkloadCount,
        WorkloadProjection,
        extension_registry,
        reset_extension_registry,
        restore_extension_registry,
    )
