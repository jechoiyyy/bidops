"""수집 회차·기회 identity·첨부 메타·포털·추적 결정.

lifecycle은 core만 import하고 screening·deep_review의 존재를 알지 못한다(명세 §4).
자기 화면·흐름이 그 모듈들의 결과를 함께 써야 하는 자리는 `extensions`의 확장점으로
뒤집혀 있다.

이 `__init__`이 lifecycle의 **공개 표면**이다. screening·deep_review는 lifecycle
테이블에 쓰거나 잠글 때 여기 있는 함수만 쓰고, 조립 계층은 여기 있는 이름만 쓴다.
읽기·join은 `lifecycle.models`의 모델 클래스로 직접 해도 된다(§4 세부 규칙).

이름은 **지연 해석**한다. 모듈 수준에서 `.api`를 곧바로 import하면
`app.lifecycle` → `api` → `ingest.loader` → `lifecycle.models` → `app.lifecycle`
순환이 생겨 `python -m app.screening.cli`·`python -m app.ingest.cli`가 죽는다
(T6의 models 분할이 만든 회귀. conftest가 다른 순서로 import하는 pytest에서는
전체 suite가 녹색인 채로 이 명령만 죽었다). 지연 해석은 패키지 초기화를 즉시
끝내므로 어떤 import 순서로 들어와도 순환이 성립하지 않는다. **공개 이름 목록과
동작은 그대로다** — `from app.lifecycle import ingest_run`은 전과 같이 된다.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

#: 공개 이름 → (구현 모듈, 그 모듈 안의 이름).
_EXPORTS: dict[str, tuple[str, str]] = {
    # --- 회차·공고·첨부 메타 쓰기와 잠금 (api.py) --------------------------
    "ATTACHMENT_ORIGINS": (".api", "ATTACHMENT_ORIGINS"),
    "IngestResult": (".api", "IngestResult"),
    "attachment_download_url": (".api", "attachment_download_url"),
    "delete_manual_attachment": (".api", "delete_manual_attachment"),
    "get_notice": (".api", "get_notice"),
    "get_run": (".api", "get_run"),
    "ingest_run": (".api", "ingest_run"),
    "list_agency_portals": (".api", "list_agency_portals"),
    "list_attachments_for_notice": (".api", "list_attachments_for_notice"),
    "list_order_plans_for_run": (".api", "list_order_plans_for_run"),
    "load_order_plan_artifact": (".api", "load_order_plan_artifact"),
    "lock_notice": (".api", "lock_notice"),
    "lock_opportunity": (".api", "lock_opportunity"),
    "match_agency_portal": (".api", "match_agency_portal"),
    "mirror_notice_observation": (".api", "mirror_notice_observation"),
    "record_ingest_warning": (".api", "record_ingest_warning"),
    "register_attachment": (".api", "register_attachment"),
    "register_manual_attachment": (".api", "register_manual_attachment"),
    # --- 확장점 정의와 registry (extensions.py) ----------------------------
    "ClaimedDirectoryLoad": (".extensions", "ClaimedDirectoryLoad"),
    "ExtensionRegistry": (".extensions", "ExtensionRegistry"),
    "JudgmentProjection": (".extensions", "JudgmentProjection"),
    "OverviewDocumentProjection": (".extensions", "OverviewDocumentProjection"),
    "PreSpecDocumentCounts": (".extensions", "PreSpecDocumentCounts"),
    "RunDirectoryClaim": (".extensions", "RunDirectoryClaim"),
    "RunIngestCounts": (".extensions", "RunIngestCounts"),
    "RunIngestHook": (".extensions", "RunIngestHook"),
    "TrackingDecisionHook": (".extensions", "TrackingDecisionHook"),
    "extension_registry": (".extensions", "extension_registry"),
    "reset_extension_registry": (".extensions", "reset_extension_registry"),
    "restore_extension_registry": (".extensions", "restore_extension_registry"),
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
        ATTACHMENT_ORIGINS,
        IngestResult,
        attachment_download_url,
        delete_manual_attachment,
        get_notice,
        get_run,
        ingest_run,
        list_agency_portals,
        list_attachments_for_notice,
        list_order_plans_for_run,
        load_order_plan_artifact,
        lock_notice,
        lock_opportunity,
        match_agency_portal,
        mirror_notice_observation,
        record_ingest_warning,
        register_attachment,
        register_manual_attachment,
    )
    from .extensions import (
        ClaimedDirectoryLoad,
        ExtensionRegistry,
        JudgmentProjection,
        OverviewDocumentProjection,
        PreSpecDocumentCounts,
        RunDirectoryClaim,
        RunIngestCounts,
        RunIngestHook,
        TrackingDecisionHook,
        extension_registry,
        reset_extension_registry,
        restore_extension_registry,
    )
