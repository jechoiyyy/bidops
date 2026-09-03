"""도입 시점(T2)의 경계 위반 허용 목록.

항목은 `(파일, 위반 종류, 대상)`이다. 목록에 없는 새 위반은 즉시 실패하고,
목록에 있는데 더 이상 위반이 아닌 항목이 남아 있어도 실패한다. 그래서 목록은
이주 task마다 줄어드는 방향으로만 바뀐다.
"""

from __future__ import annotations


#: 검사 1 — 명세 §4 허용 표에 없는 방향의 모듈 간 import.
#:
#: `app/models.py`·`app/schemas/__init__.py`가 대상일 때는 `모듈:이름` 형태로,
#: 그 밖에는 대상 모듈 경로로 적는다. 이주 task마다 이 목록은 줄어들기만 한다.
CROSS_MODULE_IMPORT_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("app/ingest/loader.py", "cross_module_import", "app.ingest.feedback:load_feedback"),
        ("app/ingest/loader.py", "cross_module_import", "app.ingest.judgment_revisions:judgment_revision_payload"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:Counterargument"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:Evidence"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:Judgment"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:JudgmentRevision"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:MatchedPerformance"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:OrderPlanScreeningArtifact"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:OrderPlanScreeningBatchAttempt"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:OrderPlanScreeningExecution"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:OrderPlanScreeningFeedback"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:OrderPlanScreeningPolicy"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:OrderPlanScreeningResult"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:Perspective"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:Review"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:ScreeningExecution"),
        ("app/ingest/loader.py", "cross_module_import", "app.models:VerificationItem"),
        ("app/ingest/loader.py", "cross_module_import", "app.screening.contracts:ContractViolation"),
        ("app/ingest/loader.py", "cross_module_import", "app.screening.contracts:add_two_axis_metadata"),
        ("app/ingest/loader.py", "cross_module_import", "app.screening.contracts:validate_judgment"),
        ("app/ingest/loader.py", "cross_module_import", "app.services.prespec_attachments:refresh_fetch_eligibility"),
        ("app/ingest/loader.py", "cross_module_import", "app.services.revisions:RevisionValidationError"),
        ("app/ingest/loader.py", "cross_module_import", "app.services.revisions:append_judgment_revision"),
        ("app/ingest/loader.py", "cross_module_import", "app.services.revisions:current_judgment_revision"),
        ("app/ingest/loader.py", "cross_module_import", "app.services.revisions:require_carry_origin_run"),
        ("app/routers/common.py", "cross_module_import", "app.models:Judgment"),
        ("app/routers/notices.py", "cross_module_import", "app.models:Judgment"),
        ("app/routers/notices.py", "cross_module_import", "app.models:Perspective"),
        ("app/routers/notices.py", "cross_module_import", "app.models:Review"),
        ("app/routers/opportunities.py", "cross_module_import", "app.services.prespec_attachments:refresh_fetch_eligibility"),
        ("app/routers/pre_specs.py", "cross_module_import", "app.models:AttachmentFetch"),
        ("app/routers/pre_specs.py", "cross_module_import", "app.models:PreSpecOverviewReview"),
        ("app/routers/pre_specs.py", "cross_module_import", "app.services.prespec_overview:OverviewPreparationError"),
        ("app/routers/pre_specs.py", "cross_module_import", "app.services.prespec_overview:OverviewReviewNotFound"),
        ("app/routers/pre_specs.py", "cross_module_import", "app.services.prespec_overview:OverviewScopeError"),
        ("app/routers/pre_specs.py", "cross_module_import", "app.services.prespec_overview:get_overview_reviews"),
        ("app/routers/pre_specs.py", "cross_module_import", "app.services.prespec_overview:get_overview_reviews_v2"),
        ("app/routers/runs.py", "cross_module_import", "app.models:Judgment"),
        ("app/routers/runs.py", "cross_module_import", "app.models:ScreeningExecution"),
        ("app/routers/runs.py", "cross_module_import", "app.models:ScreeningPolicy"),
        ("app/routers/runs.py", "cross_module_import", "app.routers.screening:execution_response"),
        ("app/routers/runs.py", "cross_module_import", "app.schemas:JudgmentExecutionCreateRequest"),
        ("app/routers/runs.py", "cross_module_import", "app.schemas:ScreeningExecutionResponse"),
        ("app/routers/runs.py", "cross_module_import", "app.screening.ollama:ModelInspectionError"),
        ("app/routers/runs.py", "cross_module_import", "app.screening.orchestrator:ScreeningCreationError"),
        ("app/routers/runs.py", "cross_module_import", "app.screening.orchestrator:ScreeningOrchestrator"),
        ("app/services/document_bundles.py", "cross_module_import", "app.models:Judgment"),
        ("app/services/document_bundles.py", "cross_module_import", "app.models:Review"),
        ("app/services/input_versions.py", "cross_module_import", "app.models:Review"),
        ("app/services/metrics.py", "cross_module_import", "app.models:Judgment"),
        ("app/services/metrics.py", "cross_module_import", "app.models:Review"),
    }
)

#: 검사 2 — router 안의 직접 ORM 접근.
#:
#: 명세 §8이 이번 이주의 범위 밖으로 둔 항목이라 마지막 단계까지 남는다.
#: 새 위반만 막는다.
ROUTER_ORM_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("app/routers/attachments.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/common.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/deep_reviews.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/document_bundles.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/notices.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/opportunities.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/policies.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/portals.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/pre_specs.py", "router_orm_access", "Session.execute"),
        ("app/routers/pre_specs.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/profile.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/quality_gates.py", "router_orm_access", "Session.execute"),
        ("app/routers/quality_gates.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/reports.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/reviews.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/runs.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/schedule.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/screening.py", "router_orm_access", "sqlalchemy.select"),
    }
)

#: 검사 3 — `schemas`가 `models`·`services`를 import하는 자리.
SCHEMA_IMPORT_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("app/schemas/__init__.py", "schema_imports_model_or_service", "app.services.profile"),
    }
)

#: 검사 4 — 다른 모듈 모델로 향하는 lifecycle 모델의 `relationship`.
LIFECYCLE_RELATIONSHIP_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("app/models.py", "lifecycle_relationship", "Attachment.fetch"),
        ("app/models.py", "lifecycle_relationship", "Notice.judgment"),
        ("app/models.py", "lifecycle_relationship", "Notice.judgment_revisions"),
        ("app/models.py", "lifecycle_relationship", "Notice.overview_review"),
        ("app/models.py", "lifecycle_relationship", "Notice.review_revisions"),
        ("app/models.py", "lifecycle_relationship", "Notice.reviews"),
        ("app/models.py", "lifecycle_relationship", "Run.judgment_revisions"),
        ("app/models.py", "lifecycle_relationship", "Run.review_revisions"),
        ("app/models.py", "lifecycle_relationship", "Run.reviews"),
    }
)


#: 허용 목록 크기의 상한. 이주 task는 이 값을 **내리기만** 한다.
#: T2 검토에서 한 번 다시 세웠다: deep_review → screening을 seam 이름만 허용하도록
#: 조이면서 §4 위반 3건이 새로 잡혔고(document_bundles→Judgment·Review,
#: input_versions→Review), 동시에 §5.2가 다른 모듈로 옮기기로 열거한 이름들을
#: 이름 단위로 풀면서 거짓 위반 12건이 빠져 66 → 57이 됐다.
#: 위 목록은 실제 위반과 정확히 같아야 하므로(stale 항목도 실패), 이 상한은
#: "새 위반을 허용 목록에 추가해 정당화하는" 경로를 추가로 막는다.
BASELINE_SIZES: dict[str, int] = {
    "cross_module_import": 51,
    "router_orm_access": 18,
    "schema_imports_model_or_service": 1,
    "lifecycle_relationship": 9,
}
