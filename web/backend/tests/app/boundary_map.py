"""모듈 경계 검사가 쓰는 매핑 데이터 (명세 §4·§5.1·§5.2·§6.1).

`app/core`·`app/lifecycle`·`app/deep_review` 폴더가 아직 없는 이주 초기에는
이 파일의 명시적 매핑표가 각 파일의 *목표* 모듈을 결정한다. 폴더가 생기는
task마다 `FILE_MODULES`·`MIXED_FILES`의 해당 항목을 지우면 되고, 마지막에는
`MODULE_FOLDERS`(폴더 규칙)만 남는다.
"""

from __future__ import annotations

CORE = "core"
LIFECYCLE = "lifecycle"
SCREENING = "screening"
DEEP_REVIEW = "deep_review"
ASSEMBLY = "assembly"

DOMAIN_MODULES = (CORE, LIFECYCLE, SCREENING, DEEP_REVIEW)

# --- 명세 §4 의존 규칙: 허용 방향은 왼쪽으로만 ---------------------------------
# 값은 "이 모듈이 모듈 전체를 import해도 되는 다른 모듈"이다. 자기 모듈은 항상
# 허용한다. 이름을 가려 받는 방향(deep_review → screening)은 여기 넣지 않고
# `SEAM_IMPORTS`가 맡는다.
ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    CORE: frozenset(),
    LIFECYCLE: frozenset({CORE}),
    SCREENING: frozenset({CORE, LIFECYCLE}),
    # deep_review는 screening을 통째로 쓰지 못한다. §4는 "screening 공개 이름 중
    # 읽기 전용 seam 함수"만 허용하고 "screening 내부 ORM·service"를 금지한다.
    DEEP_REVIEW: frozenset({CORE, LIFECYCLE}),
    ASSEMBLY: frozenset({CORE, LIFECYCLE, SCREENING, DEEP_REVIEW}),
}

# 방향 자체는 금지지만 지정된 이름만은 허용하는 seam (§6.3).
# deep_review → screening은 읽기 전용 seam 함수 두 개뿐이다. 두 함수는 T5a가
# 만들기 전까지 존재하지 않으므로, 지금 이 seam은 사실상 비어 있는 상태로
# 동작한다 — 즉 오늘의 deep_review → screening 접근은 모두 위반으로 잡힌다.
SEAM_IMPORTS: dict[tuple[str, str], frozenset[str]] = {
    (DEEP_REVIEW, SCREENING): frozenset(
        {
            "current_judgment",
            "latest_corrected_grade",
        }
    ),
}

# 방향은 허용이지만 **모듈 공개 이름으로만** 받아야 하는 조합 (§3·§4).
# 값은 그 모듈의 공개 표면 파일이다. 조립 계층은 모듈 내부 경로를 import하지
# 못하고 `__init__.py`에 올린 이름만 쓴다. T3가 app/core/__init__.py를 만들어
# core에 대해서만 켠 상태이며, lifecycle·deep_review는 폴더가 생기는 task가
# 같은 방식으로 켠다.
PUBLIC_NAME_IMPORTS: dict[tuple[str, str], str] = {
    ("assembly", "core"): "app/core/__init__.py",
    # T4가 app/lifecycle/__init__.py를 만들면서 조립 계층 몫을 켰다. screening·
    # deep_review 몫은 켤 수 없다 — §4 세부 규칙이 "lifecycle의 모델 클래스는
    # 공개 이름이다"라고 못박았고, 그 모델은 T6이 app/lifecycle/models.py를
    # 만들 때 비로소 공개 표면과 구분된다. 지금 켜면 §4가 허용한 읽기·join
    # 100여 곳이 모두 거짓 위반이 된다.
    ("assembly", "lifecycle"): "app/lifecycle/__init__.py",
}

# --- 아직 구현하지 않은 §8-1의 절 (부채) --------------------------------------
# §4의 허용 표는 방향뿐 아니라 "공개 이름 대 모듈 내부"도 가른다. 그 절은 각
# 모듈의 `__init__.py`가 공개 표면을 정하기 전에는 판정할 수 없어 아직 검사에
# 들어 있지 않다. 잊히지 않도록 `MODULE_PACKAGE_INITS` 중 하나라도 생기면
# 실패하는 테스트를 두었다(test_module_boundaries.py).
UNIMPLEMENTED_PUBLIC_NAME_RULES: tuple[str, ...] = (
    "조립 계층 → screening·deep_review: 모듈 공개 이름만 (지금은 모듈 전체를 "
    "허용). core는 T3가, lifecycle은 T4가 PUBLIC_NAME_IMPORTS로 켰다. 남은 것은 "
    "app/runtime.py가 app.screening.{execution_store,mock_transport,ollama,"
    "orchestrator,worker}·app.services.scheduled_pipeline 같은 모듈 내부를 직접 "
    "들고 있는 자리다. 두 모듈의 공개 표면(app/screening/__init__.py의 정리, "
    "app/deep_review/__init__.py)이 생기는 T7·T8에서 켠다.",
    "screening → lifecycle: lifecycle 공개 이름만 (지금은 모듈 전체를 허용). "
    "§4 세부 규칙이 lifecycle 모델 클래스를 공개 이름으로 인정하므로, "
    "app/lifecycle/models.py가 생겨 모델과 내부 service가 구분되는 T6에서 켠다.",
    "deep_review → lifecycle: 위와 같은 이유로 T6에서 켠다. 방향이 아니라 "
    "이름으로 갈리는 deep_review → screening seam만 SEAM_IMPORTS로 강제한다.",
)

# 이 중 하나라도 생기면 위 규칙을 켤 수 있다는 신호다. app/screening/__init__.py는
# 이주 전부터 있으므로 신호가 아니다. app/core/__init__.py(T3)와
# app/lifecycle/__init__.py(T4)는 만들면서 규칙을 켰으므로 뺐다.
# app/lifecycle/models.py는 남은 두 규칙(screening·deep_review → lifecycle)의
# 전제이므로 신호로 둔다 — T6이 만들 때 켜야 한다.
MODULE_PACKAGE_INITS: tuple[str, ...] = (
    "app/lifecycle/models.py",
    "app/deep_review/__init__.py",
)

# --- 폴더 규칙 (경로 판정에서 가장 먼저 본다) ----------------------------------
MODULE_FOLDERS: dict[str, str] = {
    "app/core": CORE,
    "app/lifecycle": LIFECYCLE,
    "app/screening": SCREENING,
    "app/deep_review": DEEP_REVIEW,
}

# 폴더 규칙의 예외. T3가 generation_config를 app/core로 옮겨 지금은 비어 있다.
FOLDER_EXCEPTIONS: dict[str, str] = {}

# 검사 대상에서 제외하는 파일. 여기 적힌 경로가 실제로 없으면 실패한다
# (허용 목록의 stale 항목을 막는 것과 같은 취지). codex-exec provider는 T1이
# 실제로 삭제했으므로 더 이상 제외할 것이 없다.
EXCLUDED_FILES: frozenset[str] = frozenset()

# --- 명세 §5.2 "현재 위치 → 이주" 대응표 ---------------------------------------
FILE_MODULES: dict[str, str] = {
    # 조립 계층
    "app/__init__.py": ASSEMBLY,
    "app/main.py": ASSEMBLY,
    "app/runtime.py": ASSEMBLY,
    "app/workers/__init__.py": ASSEMBLY,
    "app/workers/analysis.py": ASSEMBLY,
    "app/migrations/__init__.py": ASSEMBLY,
    "app/migrations/import_sqlite.py": ASSEMBLY,
    "app/routers/__init__.py": ASSEMBLY,
    "app/services/__init__.py": ASSEMBLY,
    "app/cli/__init__.py": ASSEMBLY,
    # core
    # lifecycle
    "app/ingest/__init__.py": LIFECYCLE,
    "app/ingest/cli.py": LIFECYCLE,
    # loader/contracts는 판정·리뷰·C-2 적재 부분이 screening으로 갈라지지만
    # 본체는 회차 적재이므로 lifecycle로 본다 (T5b에서 분리).
    "app/ingest/contracts.py": LIFECYCLE,
    "app/ingest/loader.py": LIFECYCLE,
    "app/services/metrics.py": LIFECYCLE,
    "app/services/opportunity_integrity.py": LIFECYCLE,
    "app/services/opportunity_tracking.py": LIFECYCLE,
    "app/services/pipeline.py": LIFECYCLE,
    "app/routers/common.py": LIFECYCLE,
    "app/routers/metrics.py": LIFECYCLE,
    "app/routers/notices.py": LIFECYCLE,
    "app/routers/opportunities.py": LIFECYCLE,
    "app/routers/portals.py": LIFECYCLE,
    # runs router는 판정 pipeline endpoint가 screening으로 갈라진다. pre_specs
    # router의 개요 리뷰 endpoint는 T5b가 routers/deep_reviews.py로 옮겼다.
    "app/routers/pre_specs.py": LIFECYCLE,
    "app/routers/runs.py": LIFECYCLE,
    "app/schemas/opportunities.py": LIFECYCLE,
    # schemas/pre_specs는 목록·추적 부분이 lifecycle, 개요 부분이 deep_review다.
    "app/schemas/pre_specs.py": LIFECYCLE,
    # T5b가 services/prespec_attachments.py에서 갈라낸 lifecycle 몫
    # (parse_attachment_key, tracked_order_plan_connection*).
    "app/services/opportunity_connections.py": LIFECYCLE,
    # screening
    "app/ingest/feedback.py": SCREENING,
    "app/ingest/judgment_revisions.py": SCREENING,
    "app/services/candidate_quality.py": SCREENING,
    "app/services/order_plan_screening.py": SCREENING,
    "app/services/profile.py": SCREENING,
    # 범용 client는 core로 갔고 남은 것은 C-2 어댑터뿐이다 (T7에서 screening 폴더로).
    "app/services/vllm_client.py": SCREENING,
    "app/services/reviews.py": SCREENING,
    "app/services/revisions.py": SCREENING,
    "app/services/scheduled_pipeline.py": SCREENING,
    "app/services/scheduler.py": SCREENING,
    "app/routers/order_plans.py": SCREENING,
    "app/routers/policies.py": SCREENING,
    "app/routers/profile.py": SCREENING,
    "app/routers/quality_gates.py": SCREENING,
    "app/routers/reviews.py": SCREENING,
    "app/routers/schedule.py": SCREENING,
    "app/routers/screening.py": SCREENING,
    "app/schemas/order_plans.py": SCREENING,
    "app/schemas/revisions.py": SCREENING,
    "app/workers/order_plan_screening.py": SCREENING,
    "app/cli/score_candidate_quality.py": SCREENING,
    # deep_review
    "app/services/agent_e2e.py": DEEP_REVIEW,
    "app/services/assets.py": DEEP_REVIEW,
    # attachments는 lifecycle로 갈 함수(attachment_download_url)를 하나 갖는다.
    "app/services/attachments.py": DEEP_REVIEW,
    "app/services/prespec_attachments.py": DEEP_REVIEW,
    "app/services/bc_e2e.py": DEEP_REVIEW,
    "app/services/bid_delta.py": DEEP_REVIEW,
    "app/services/deep_review_validation.py": DEEP_REVIEW,
    "app/services/deep_review_vllm.py": DEEP_REVIEW,
    "app/services/deep_reviews.py": DEEP_REVIEW,
    "app/services/document_bundles.py": DEEP_REVIEW,
    "app/services/document_converter.py": DEEP_REVIEW,
    "app/services/document_structures.py": DEEP_REVIEW,
    "app/services/evidence.py": DEEP_REVIEW,
    "app/services/input_versions.py": DEEP_REVIEW,
    "app/services/mock_analysis_client.py": DEEP_REVIEW,
    "app/services/prespec_overview.py": DEEP_REVIEW,
    "app/services/reports.py": DEEP_REVIEW,
    "app/routers/attachments.py": DEEP_REVIEW,
    "app/routers/bid_delta.py": DEEP_REVIEW,
    "app/routers/deep_reviews.py": DEEP_REVIEW,
    "app/routers/document_bundles.py": DEEP_REVIEW,
    "app/routers/reports.py": DEEP_REVIEW,
    "app/schemas/bid_delta.py": DEEP_REVIEW,
    "app/schemas/document_bundles.py": DEEP_REVIEW,
    "app/schemas/reports.py": DEEP_REVIEW,
    "app/workers/deep_review.py": DEEP_REVIEW,
    "app/workers/document.py": DEEP_REVIEW,
    "app/workers/document_protocol.py": DEEP_REVIEW,
    "app/workers/prespec_attachment.py": DEEP_REVIEW,
    "app/cli/import_profile_policy.py": DEEP_REVIEW,
    "app/cli/run_bc_e2e.py": DEEP_REVIEW,
    # T5b: lifecycle 확장점(§6.1 개요·문서 projection, §6.2 hook)의 deep_review 구현과
    # router·agent가 함께 쓰는 심층 검토 view.
    "app/services/prespec_projection.py": DEEP_REVIEW,
    "app/services/deep_review_hooks.py": DEEP_REVIEW,
    "app/schemas/deep_reviews.py": DEEP_REVIEW,
}

# 디렉터리 단위로 통째로 한 모듈에 속하는 경로 (§5.2).
DIRECTORY_MODULES: dict[str, str] = {
    # 조립 계층. alembic은 §4에 따라 models까지 import해도 된다.
    "alembic": ASSEMBLY,
    "app/agents": DEEP_REVIEW,
    "app/contracts/deep_review": DEEP_REVIEW,
    "app/document_mcp": DEEP_REVIEW,
}

# 한 파일에 네 모듈이 섞여 있어 파일 단위로 배정할 수 없는 파일 (T6·T7이 나눈다).
# import 하는 쪽(출발지)으로는 검사하지 않고, import 되는 쪽(도착지)일 때만
# 이름 단위로 소유 모듈을 판정한다.
MIXED_FILES: frozenset[str] = frozenset(
    {
        "app/models.py",
        "app/schemas/__init__.py",
    }
)

# --- 명세 §5.2가 이름 단위로 쪼갠 service 파일 --------------------------------
# 파일은 본체가 가는 모듈에 배정하되(FILE_MODULES), §5.2가 다른 모듈로 옮길
# 이름을 명시적으로 열거한 곳은 그 이름만 따로 소유를 준다. 그러지 않으면
# "이미 다른 모듈로 가기로 정해진 이름"을 참조한 것이 거짓 위반이 된다.
# 열거되지 않은 이름은 파일 본체의 모듈(각 항목의 두 번째 값)로 본다.
SPLIT_FILE_NAME_MODULES: dict[str, tuple[dict[str, str], str]] = {
    # §5.2 lifecycle: "services/attachments.py의 attachment_download_url"
    "app/services/attachments.py": (
        {
            "attachment_download_url": LIFECYCLE,
        },
        DEEP_REVIEW,
    ),
    # §5.2 lifecycle의 "services/prespec_attachments.py의 parse_attachment_key와
    # tracked_order_plan_connection*"은 T5b가 services/opportunity_connections.py로
    # 옮겨 파일 단위로 lifecycle이 됐다.
}


# --- 명세 §5.1 테이블 소유 -----------------------------------------------------
TABLE_OWNER: dict[str, str] = {
    # core (2)
    "audit_event": CORE,
    "idempotency_record": CORE,
    # lifecycle (10)
    "run": LIFECYCLE,
    "notice": LIFECYCLE,
    "notice_observation": LIFECYCLE,
    "order_plan": LIFECYCLE,
    "order_plan_observation": LIFECYCLE,
    "opportunity": LIFECYCLE,
    "opportunity_link": LIFECYCLE,
    "attachment": LIFECYCLE,
    "agency_portal": LIFECYCLE,
    "ingest_warning": LIFECYCLE,
    # screening (28)
    "judgment": SCREENING,
    "judgment_revision": SCREENING,
    "perspective": SCREENING,
    "screening_evidence": SCREENING,
    "counterargument": SCREENING,
    "verification_item": SCREENING,
    "matched_performance": SCREENING,
    "review": SCREENING,
    "review_revision": SCREENING,
    "verification_answer": SCREENING,
    "screening_execution": SCREENING,
    "screening_attempt": SCREENING,
    "company_profile_snapshot": SCREENING,
    "quality_gate": SCREENING,
    "quality_gate_evaluation": SCREENING,
    "quality_gate_review": SCREENING,
    "screening_policy": SCREENING,
    "schedule_setting": SCREENING,
    "schedule_reservation": SCREENING,
    "schedule_execution": SCREENING,
    "always_on_state": SCREENING,
    "screening_audit_event": SCREENING,
    "order_plan_screening_policy": SCREENING,
    "order_plan_screening_execution": SCREENING,
    "order_plan_screening_batch_attempt": SCREENING,
    "order_plan_screening_result": SCREENING,
    "order_plan_screening_artifact": SCREENING,
    "order_plan_screening_feedback": SCREENING,
    # deep_review (34)
    "attachment_fetch": DEEP_REVIEW,
    "content_object": DEEP_REVIEW,
    "content_object_location": DEEP_REVIEW,
    "content_scan": DEEP_REVIEW,
    "document_version": DEEP_REVIEW,
    "document_structure": DEEP_REVIEW,
    "document_block": DEEP_REVIEW,
    "document_bundle": DEEP_REVIEW,
    "document_bundle_item": DEEP_REVIEW,
    "profile_version": DEEP_REVIEW,
    "profile_evidence": DEEP_REVIEW,
    "analysis_policy_version": DEEP_REVIEW,
    "work_job": DEEP_REVIEW,
    "deep_review": DEEP_REVIEW,
    "deep_review_attempt": DEEP_REVIEW,
    "deep_review_stage": DEEP_REVIEW,
    "claim": DEEP_REVIEW,
    "evidence_ref": DEEP_REVIEW,
    "claim_evidence": DEEP_REVIEW,
    "report_revision": DEEP_REVIEW,
    "report_revision_evidence": DEEP_REVIEW,
    "validation_run": DEEP_REVIEW,
    "validation_check": DEEP_REVIEW,
    "final_opinion": DEEP_REVIEW,
    "prespec_overview_review": DEEP_REVIEW,
    "prespec_overview_snapshot": DEEP_REVIEW,
    "prespec_overview_attempt": DEEP_REVIEW,
    "prespec_overview_result": DEEP_REVIEW,
    "prespec_overview_attempt_event": DEEP_REVIEW,
    "bid_delta_comparison": DEEP_REVIEW,
    "bid_delta_attempt": DEEP_REVIEW,
    "bid_delta_item": DEEP_REVIEW,
    "bid_delta_evidence": DEEP_REVIEW,
    "bid_final_decision": DEEP_REVIEW,
}

# `app/models.py`의 테이블이 아닌 공개 이름. 테이블 클래스는 `__tablename__`에서
# 자동으로 유도하므로 여기 적지 않는다.
MODELS_EXTRA_NAMES: dict[str, str] = {
    "AwareDateTime": CORE,
    "Base": CORE,
    "JSONB_COMPAT": CORE,
    "JSONB_NULL_COMPAT": CORE,
    "app_uuid": CORE,
    "utc_now": CORE,
    "ScreeningEvidence": SCREENING,  # Evidence(screening_evidence)의 별칭
    "ATTACHMENT_FETCH_TABLES": ASSEMBLY,
    "BID_DELTA_TABLES": ASSEMBLY,
    "IDENTITY_TABLES": ASSEMBLY,
    "LEGACY_TABLES": ASSEMBLY,
    "NEW_TABLES": ASSEMBLY,
    "OPPORTUNITY_TABLES": ASSEMBLY,
    "ORDER_PLAN_SCREENING_TABLES": ASSEMBLY,
    "PRESPEC_OVERVIEW_TABLES": ASSEMBLY,
    "REVISION_TABLES": ASSEMBLY,
    "SCREENING_RUNTIME_TABLES": ASSEMBLY,
    "PRESPEC_OVERVIEW_ATTEMPT_TRANSITIONS": DEEP_REVIEW,
}

# --- 명세 §6.1 DTO 소유: `app/schemas/__init__.py`의 이름 단위 매핑 -------------
# projection DTO(JudgmentResponse·ReviewResponse·분포 항목 등)는 lifecycle이
# 소유한다. 공용 기반 모델·검증기는 core로 간다(§4: schemas는 상수·검증기를
# core에서 가져온다).
SCHEMAS_NAME_MODULE: dict[str, str] = {
    # core — 공용 기반 모델·타입·검증기
    "APIModel": CORE,
    "PageFilters": CORE,
    "AwareDateTime": CORE,
    "Actor": CORE,
    "NonEmpty": CORE,
    "Digest": CORE,
    "RuntimeContractModel": CORE,
    "_require_aware": CORE,
    "_validate_clock_time": CORE,
    "_validate_relative_source_ref": CORE,
    "_validate_run_key_for_kind": CORE,
    "_validate_profile_binding": CORE,
    "_validate_generation_binding": CORE,
    "_validate_profile_projection_binding_values": CORE,
    "_validate_profile_error_codes": CORE,
    # lifecycle — 회차·공고·첨부·기관 포털·파이프라인 projection DTO
    "AttachmentResponse": LIFECYCLE,
    "AgencyPortalResponse": LIFECYCLE,
    "AgencyPortalCreateRequest": LIFECYCLE,
    "AgencyPortalUpdateRequest": LIFECYCLE,
    "AttachmentProcedureResponse": LIFECYCLE,
    "EvidenceResponse": LIFECYCLE,
    "PerspectiveResponse": LIFECYCLE,
    "CounterargumentResponse": LIFECYCLE,
    "VerificationItemResponse": LIFECYCLE,
    "MatchedPerformanceResponse": LIFECYCLE,
    "ReviewAnswerResponse": LIFECYCLE,
    "ReviewAnswerInput": LIFECYCLE,
    "ReviewUpsertRequest": LIFECYCLE,
    "ReviewResponse": LIFECYCLE,
    "JudgmentResponse": LIFECYCLE,
    "NoticeListItem": LIFECYCLE,
    "AttachmentQueueItem": LIFECYCLE,
    "AttachmentQueueResponse": LIFECYCLE,
    "NoticeDetailResponse": LIFECYCLE,
    "NoticeListResponse": LIFECYCLE,
    "HistoryItemResponse": LIFECYCLE,
    "NoticeHistoryResponse": LIFECYCLE,
    "RelatedNoticeResponse": LIFECYCLE,
    "RelatedNoticeListResponse": LIFECYCLE,
    "WarningResponse": LIFECYCLE,
    "WarningListResponse": LIFECYCLE,
    "RunCounts": LIFECYCLE,
    "RunSummary": LIFECYCLE,
    "RunListResponse": LIFECYCLE,
    "ArtifactValidationResponse": LIFECYCLE,
    "PipelineStageResponse": LIFECYCLE,
    "CollectionScopeResponse": LIFECYCLE,
    "RunDetailResponse": LIFECYCLE,
    "FunnelItem": LIFECYCLE,
    "DistributionItem": LIFECYCLE,
    "VerificationRequest": LIFECYCLE,
    "DeadlineNotice": LIFECYCLE,
    "RunStatsResponse": LIFECYCLE,
    "IngestRequest": LIFECYCLE,
    "IngestResponse": LIFECYCLE,
    "PipelineRunRequest": LIFECYCLE,
    "PipelineLogLineResponse": LIFECYCLE,
    "PipelineExecutionResponse": LIFECYCLE,
    "PipelineLogResponse": LIFECYCLE,
    "MetricBasis": LIFECYCLE,
    "ValidationMetric": LIFECYCLE,
    "ValidationMetricsResponse": LIFECYCLE,
    # screening — 프로필 projection, 판정 실행·품질 게이트·정책·스케줄 런타임 계약
    "ProfileStatus": SCREENING,
    "ProfileSectionState": SCREENING,
    "ProfileItemResponse": SCREENING,
    "ProfileSectionResponse": SCREENING,
    "ProfileSectionsResponse": SCREENING,
    "ProfileUnknownResponse": SCREENING,
    "ProfileUnknownsResponse": SCREENING,
    "CompanyProfileVersion": SCREENING,
    "ScreeningExecutionId": SCREENING,
    "QualityGateId": SCREENING,
    "QualityGateEvaluationId": SCREENING,
    "ScheduleExecutionId": SCREENING,
    "ScreeningTrigger": SCREENING,
    "ScreeningScope": SCREENING,
    "ScreeningStatus": SCREENING,
    "ScreeningStage": SCREENING,
    "AttemptStage": SCREENING,
    "ScreeningFailureType": SCREENING,
    "JudgmentExecutionCreateRequest": SCREENING,
    "ScreeningStopRequest": SCREENING,
    "ScreeningArtifactUrls": SCREENING,
    "ScreeningExecutionResponse": SCREENING,
    "ScreeningAttemptResponse": SCREENING,
    "ScreeningFailureItem": SCREENING,
    "ScreeningExecutionListResponse": SCREENING,
    "ScreeningExecutionDetailResponse": SCREENING,
    "ScreeningExecutionQuery": SCREENING,
    "CompanyProfileSnapshotResponse": SCREENING,
    "CompanyProfileSnapshotListResponse": SCREENING,
    "QualityGatePurpose": SCREENING,
    "QualityGateExecutionStatus": SCREENING,
    "QualityGateResultStatus": SCREENING,
    "QualityGateCreateRequest": SCREENING,
    "QualityGateEvaluationResponse": SCREENING,
    "QualityGateReviewResponse": SCREENING,
    "QualityGateReviewUpsertRequest": SCREENING,
    "QualityGateResponse": SCREENING,
    "QualityGateDetailResponse": SCREENING,
    "QualityGateListResponse": SCREENING,
    "QualityGateQuery": SCREENING,
    "PolicyVersionCreateRequest": SCREENING,
    "PolicyCandidateRequest": SCREENING,
    "PolicyActivationRequest": SCREENING,
    "PolicyStatus": SCREENING,
    "PolicyVersionResponse": SCREENING,
    "PolicyVersionListResponse": SCREENING,
    "PolicyVersionQuery": SCREENING,
    "PolicyActivationResponse": SCREENING,
    "ScheduleSettingsResponse": SCREENING,
    "ScheduleSettingsUpdateRequest": SCREENING,
    "ScheduleJobKind": SCREENING,
    "ScheduleStatus": SCREENING,
    "ScheduleTrigger": SCREENING,
    "ScheduleExecutionCreateRequest": SCREENING,
    "ScheduleExecutionSummary": SCREENING,
    "ScheduleExecutionListResponse": SCREENING,
    "ScheduleExecutionQuery": SCREENING,
    "AlwaysOnSwitchUpdateRequest": SCREENING,
    "AlwaysOnSwitchResponse": SCREENING,
}

# --- 테스트 폴더 (§5.4) --------------------------------------------------------
TEST_FOLDER_MODULES: dict[str, str] = {
    "tests/core": CORE,
    "tests/lifecycle": LIFECYCLE,
    "tests/screening": SCREENING,
    "tests/deep_review": DEEP_REVIEW,
    "tests/app": ASSEMBLY,
}
