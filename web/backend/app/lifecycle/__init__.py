"""수집 회차·기회 identity·첨부 메타·포털·추적 결정.

lifecycle은 core만 import하고 screening·deep_review의 존재를 알지 못한다(명세 §4).
자기 화면·흐름이 그 모듈들의 결과를 함께 써야 하는 자리는 `extensions`의 확장점으로
뒤집혀 있다.

이 `__init__`이 lifecycle의 **공개 표면**이다. screening·deep_review는 lifecycle
테이블에 쓰거나 잠글 때 여기 있는 함수만 쓰고, 조립 계층은 여기 있는 이름만 쓴다.
읽기·join은 `lifecycle.models`의 모델 클래스로 직접 해도 된다(§4 세부 규칙).
"""

from __future__ import annotations

from .api import (
    ATTACHMENT_ORIGINS,
    IngestResult,
    delete_manual_attachment,
    get_notice,
    get_run,
    ingest_run,
    list_agency_portals,
    list_attachments_for_notice,
    list_order_plans_for_run,
    lock_notice,
    lock_opportunity,
    match_agency_portal,
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
)

__all__ = [
    "ATTACHMENT_ORIGINS",
    "ClaimedDirectoryLoad",
    "ExtensionRegistry",
    "IngestResult",
    "JudgmentProjection",
    "OverviewDocumentProjection",
    "PreSpecDocumentCounts",
    "RunDirectoryClaim",
    "RunIngestCounts",
    "RunIngestHook",
    "TrackingDecisionHook",
    "delete_manual_attachment",
    "extension_registry",
    "get_notice",
    "get_run",
    "ingest_run",
    "list_agency_portals",
    "list_attachments_for_notice",
    "list_order_plans_for_run",
    "lock_notice",
    "lock_opportunity",
    "match_agency_portal",
    "register_attachment",
    "register_manual_attachment",
    "reset_extension_registry",
]
