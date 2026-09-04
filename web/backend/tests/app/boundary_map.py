"""모듈 경계 검사가 쓰는 매핑 데이터 (명세 §4·§5.1·§5.2·§6.1).

네 모듈 폴더(`app/core`·`app/lifecycle`·`app/screening`·`app/deep_review`)는
모두 생겼지만 아직 대부분의 service·router·worker가 폴더 밖에 있다. 그 파일들의
*목표* 모듈은 이 파일의 명시적 매핑표가 결정한다. 폴더 이주 task마다
`FILE_MODULES`·`MIXED_FILES`의 해당 항목을 지우면 되고, 마지막에는
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
            # 목록 화면이 공고마다 조회를 내지 않도록 T5a가 더한 batch 판이다.
            # 방향은 §4 그대로이며 이름만 하나 늘었다.
            "current_judgments",
            "latest_corrected_grade",
        }
    ),
}

# 방향은 허용이지만 **모듈 공개 이름으로만** 받아야 하는 조합 (§3·§4).
# 값은 그 모듈의 공개 표면 파일들이다. 이 조합에서는 여기 적힌 파일에서 받은
# 이름만 허용하고 그 밖의 모듈 내부 경로는 위반으로 잡는다.
#
# lifecycle의 공개 표면은 두 파일이다. `__init__.py`가 올린 함수·타입과,
# **모델 클래스**다 — §4 세부 규칙이 "lifecycle의 모델 클래스는 공개 이름이다.
# screening·deep_review는 `lifecycle.models`의 `Notice`·`Run`... 을 import해
# ORM으로 읽고 join해도 된다"고 못박았다. 쓰기와 잠금만 `__init__.py`의 함수로
# 제한된다(그 제한은 이 검사가 아니라 `api.py`의 공개 함수 설계가 진다).
# T6이 `app/lifecycle/models.py`를 만들면서 screening·deep_review 몫을 켰다.
PUBLIC_NAME_IMPORTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("assembly", "core"): ("app/core/__init__.py",),
    # T4가 app/lifecycle/__init__.py를 만들면서 조립 계층 몫을 켰다.
    ("assembly", "lifecycle"): ("app/lifecycle/__init__.py",),
    ("screening", "lifecycle"): (
        "app/lifecycle/__init__.py",
        "app/lifecycle/models.py",
    ),
    ("deep_review", "lifecycle"): (
        "app/lifecycle/__init__.py",
        "app/lifecycle/models.py",
    ),
}

# 규칙을 적용할 대상 경로 범위. `None`이면 그 모듈이 소유한 파일 전부다.
#
# screening·deep_review → lifecycle은 **lifecycle 패키지 안**으로 한정해 켠다.
# lifecycle 소유 파일 상당수(app/ingest, app/services, app/routers, app/schemas)가
# 아직 `app/lifecycle/` 밖에 있고, 그 파일들의 공개 표면은 T7의 폴더 이주가
# 정한다. 지금 전 범위로 켜면 아직 설계되지 않은 표면에 대한 위반 수십 건이
# 한꺼번에 허용 목록으로 들어가야 하고, 허용 목록은 줄어드는 방향만 허용한다.
# 파일이 `app/lifecycle/`로 들어오는 순간 이 규칙이 자동으로 그 파일까지
# 강제하므로 부채는 사라지지 않는다. 남은 범위는
# `UNIMPLEMENTED_PUBLIC_NAME_RULES`와 `REMAINING_PUBLIC_NAME_DEBT`가 센다.
PUBLIC_NAME_SCOPES: dict[tuple[str, str], str | None] = {
    ("assembly", "core"): None,
    ("assembly", "lifecycle"): None,
    ("screening", "lifecycle"): "app/lifecycle/",
    ("deep_review", "lifecycle"): "app/lifecycle/",
}

# §3의 유일한 예외: "`alembic/env.py`와 migration revision 파일이 각 모듈의
# `models` 하위 모듈을 import하는 것". 이 파일들은 선언 테이블을 모두 등록해야
# `Base.metadata`가 완전해지므로 공개 표면 제한을 받지 않는다.
MODELS_SUBMODULE_IMPORTERS: tuple[str, ...] = (
    "alembic/env.py",
    "alembic/versions/",
    # 같은 성격의 조립 계층 migration 도구다. 일회성 SQLite 이전 입력이
    # legacy·Lean v1 대상 테이블을 모두 만들려면 네 모듈의 models가 필요하다.
    "app/migrations/import_sqlite.py",
)

# --- 아직 구현하지 않은 §8-1의 절 (부채) --------------------------------------
# §4의 허용 표는 방향뿐 아니라 "공개 이름 대 모듈 내부"도 가른다. T3가 core를,
# T4가 조립 계층 → lifecycle을, T6이 screening·deep_review → lifecycle(패키지
# 범위)을 켰다. 남은 두 절은 아래와 같고, 각 절이 아직 필요한 이유는
# `REMAINING_PUBLIC_NAME_DEBT`가 실제 코드에서 센다.
UNIMPLEMENTED_PUBLIC_NAME_RULES: tuple[str, ...] = (
    "조립 계층 → screening·deep_review: 모듈 공개 이름만 (지금은 모듈 전체를 "
    "허용). main.py·runtime.py·workers/analysis.py·migrations/import_sqlite.py가 "
    "app.screening.{execution_store,ollama,orchestrator,worker,routers.*,"
    "services.*,workers.order_plan}과 app.deep_review.{routers,services,workers}."
    "* 같은 모듈 내부 경로를 직접 들고 있다. 두 모듈의 파일은 이제 모두 자기 "
    "폴더 안에 있으므로 남은 일은 모듈 진입점(__init__)에 공개 이름을 올리는 "
    "것이고, T8에서 켠다.",
    "screening·deep_review → lifecycle: `app/lifecycle/` **밖에** 남은 lifecycle "
    "소유 파일(app/ingest/{loader,contracts}.py, app/services의 lifecycle 파일, "
    "app/routers/common.py, app/schemas의 lifecycle 이름)까지 공개 이름으로 "
    "제한하는 부분. T6은 lifecycle 패키지 안(PUBLIC_NAME_SCOPES)만 켰다. "
    "T7 3단계가 그 파일들을 app/lifecycle/로 옮기면 같은 규칙이 그대로 "
    "적용되므로, 그때 각 파일의 공개 표면을 정하면서 이 절이 닫힌다.",
)

# 위 두 절이 아직 필요한 이유를 실제 코드에서 센 것이다. 값은 "그 절이 켜져
# 있었다면 위반이었을 import"의 개수이며, 허용 목록과 같은 계약을 따른다:
# 정확히 일치해야 하고 이주 task는 **줄이기만** 한다. 0이 되면 그 절을 검사 1에
# 넣을 수 있다는 신호이므로 테스트가 실패한다.
#
# 모듈 패키지 존재 여부는 더 이상 신호가 아니다. 네 패키지가 모두 생겼고
# (app/core·app/lifecycle·app/screening·app/deep_review), 남은 조건은 파일이
# 있느냐가 아니라 조립 계층·형제 모듈이 아직 모듈 밖 경로를 들고 있느냐다.
# T7 2단계 실측: 조립 계층 몫은 33 그대로다(경로만 app/screening/... 로 바뀌었다).
# lifecycle 몫은 77 → 80으로 세 건 늘었는데, 제품 코드의 import는 하나도 바뀌지
# 않았고 선별 테스트 두 개(tests/screening/test_quality_gate.py의 두 건,
# test_screening_orchestrator.py의 한 건)가 tests/ 루트에서 tests/screening/으로
# 들어오면서 비로소 검사 대상이 된 것뿐이다. 셋 다 `app/ingest/loader.py`를
# 가리키며, 3단계가 그 파일을 app/lifecycle/로 옮기면 함께 정리된다.
REMAINING_PUBLIC_NAME_DEBT: dict[str, int] = {
    "assembly->screening|deep_review": 33,
    "screening|deep_review->lifecycle(패키지 밖)": 80,
}

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
    # T5a가 판정·리뷰·C-2 적재와 C-2 계약을 screening으로 옮겼다. 남은 본체는
    # 회차 적재와 회차 산출물 계약이므로 lifecycle이다.
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
    # 두 router의 본체는 lifecycle이다. 갈라져 나간 endpoint는 각각 소유 모듈이
    # 같은 경로로 제공한다 — 판정 pipeline은 screening router로, 개요 리뷰는
    # routers/deep_reviews.py로 옮겼다(§5.3).
    "app/routers/pre_specs.py": LIFECYCLE,
    "app/routers/runs.py": LIFECYCLE,
    "app/schemas/opportunities.py": LIFECYCLE,
    # schemas/pre_specs는 목록·추적 부분이 lifecycle, 개요 부분이 deep_review다.
    "app/schemas/pre_specs.py": LIFECYCLE,
    # T5b가 services/prespec_attachments.py에서 갈라낸 lifecycle 몫
    # (parse_attachment_key, tracked_order_plan_connection*).
    "app/services/opportunity_connections.py": LIFECYCLE,
    # screening
    # T7 2단계가 screening 소유 service·router·worker·cli·schemas를 모두
    # app/screening/로 옮겼다. 이제 폴더 규칙(MODULE_FOLDERS)이 판정하므로
    # 여기 남은 항목이 없다.
    # deep_review
    # T7 1단계가 deep_review 소유 service·router·worker·agent·document_mcp·
    # contracts·policies·cli·schemas를 모두 app/deep_review/로 옮겼다. 이제
    # 폴더 규칙(MODULE_FOLDERS)이 판정하므로 여기 남은 항목이 없다. 이름 하나만
    # 예외로 남았고 그것은 SPLIT_FILE_NAME_MODULES가 든다.
}

# 디렉터리 단위로 통째로 한 모듈에 속하는 경로 (§5.2).
DIRECTORY_MODULES: dict[str, str] = {
    # 조립 계층. alembic은 §4에 따라 models까지 import해도 된다.
    "alembic": ASSEMBLY,
}

# 한 파일에 네 모듈이 섞여 있어 파일 단위로 배정할 수 없는 파일 (T7이 나눈다).
# import 하는 쪽(출발지)으로는 검사하지 않고, import 되는 쪽(도착지)일 때만
# 이름 단위로 소유 모듈을 판정한다. T6이 `app/models.py`를 네 모듈의
# `models.py`로 나눠 없앴으므로 남은 것은 schemas뿐이다.
MIXED_FILES: frozenset[str] = frozenset(
    {
        "app/schemas/__init__.py",
    }
)

# --- 명세 §5.2가 이름 단위로 쪼갠 service 파일 --------------------------------
# 파일은 본체가 가는 모듈에 배정하되(FILE_MODULES), §5.2가 다른 모듈로 옮길
# 이름을 명시적으로 열거한 곳은 그 이름만 따로 소유를 준다. 그러지 않으면
# "이미 다른 모듈로 가기로 정해진 이름"을 참조한 것이 거짓 위반이 된다.
# 열거되지 않은 이름은 파일 본체의 모듈(각 항목의 두 번째 값)로 본다.
SPLIT_FILE_NAME_MODULES: dict[str, tuple[dict[str, str], str]] = {
    # §5.2 lifecycle: "services/attachments.py의 attachment_download_url".
    # T7 1단계가 파일을 app/deep_review/services/로 옮겼고, 이 이름 하나만은
    # 아직 lifecycle 몫이다 (lifecycle 폴더 이주 때 실제로 옮긴다).
    "app/deep_review/services/attachments.py": (
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
    # screening 이름 59개는 T7 2단계가 `app/screening/schemas/__init__.py`로
    # 옮겼다. 그 파일은 폴더 규칙이 판정하므로 여기 남길 것이 없다. 남은
    # `_validate_profile_*` 검증기는 core 이름이라 이 파일에 그대로 있다.
}

# `tests/` 루트에 두는 공용 helper. conftest·postgres 처럼 어느 모듈의 테스트든
# 쓸 수 있어야 하므로 core로 본다. 여기 없으면 기본값(조립 계층)이 되어 모듈
# 테스트가 helper를 쓰는 것 자체가 위반으로 잡힌다.
FILE_MODULES["tests/c2_fixtures.py"] = CORE
FILE_MODULES["tests/postgres.py"] = CORE
# `tests/fakes/`도 같은 성격의 루트 공용 helper다(§5.4가 루트에 남긴다).
# T7 2단계가 선별 테스트를 tests/screening/으로 옮기면서 실제로 필요해졌다.
DIRECTORY_MODULES["tests/fakes"] = CORE


# --- 테스트 폴더 (§5.4) --------------------------------------------------------
TEST_FOLDER_MODULES: dict[str, str] = {
    "tests/core": CORE,
    "tests/lifecycle": LIFECYCLE,
    "tests/screening": SCREENING,
    "tests/deep_review": DEEP_REVIEW,
    "tests/app": ASSEMBLY,
}
