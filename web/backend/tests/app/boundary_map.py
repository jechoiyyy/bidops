"""모듈 경계 검사가 쓰는 매핑 데이터 (명세 §4·§5.1·§5.2·§6.1).

네 모듈 폴더(`app/core`·`app/lifecycle`·`app/screening`·`app/deep_review`)가
모두 생겼고, T7 1·2·3단계가 소유 파일을 전부 자기 폴더로 옮겼다. 그래서
경로 판정은 이제 `MODULE_FOLDERS`(폴더 규칙)와, 폴더 밖에 남은 조립 계층
파일 목록(`FILE_MODULES`)만으로 끝난다. `MIXED_FILES`·`SPLIT_FILE_NAME_MODULES`는
비어 있고, 새 파일이 모듈 폴더 밖에 생기면 배정을 강제하는 검사가 걸린다.
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
# lifecycle의 공개 표면은 `__init__.py`가 올린 함수·타입과 **선언적 계약 파일**
# 이다. §4 세부 규칙이 "lifecycle의 모델 클래스는 공개 이름이다. screening·
# deep_review는 `lifecycle.models`의 `Notice`·`Run`... 을 import해 ORM으로 읽고
# join해도 된다"고 못박았고, 같은 성격의 선언 파일이 `schemas`의 응답 DTO와
# `ingest/contracts.py`의 회차 산출물 계약이다(둘 다 `docs/contracts.md`가 정본
# 으로 삼는 계약이며 테이블에 닿지 않는다). T7 3단계가 그 파일들을 lifecycle
# 폴더로 들여오면서 함께 켰다.
#
# **동작**(loader·service·router)은 예외 없이 `__init__.py`의 이름으로만 받는다.
# 쓰기와 잠금 역시 `__init__.py`의 함수로 제한된다(그 제한은 이 검사가 아니라
# `api.py`의 공개 함수 설계가 진다).
_LIFECYCLE_PUBLIC_SURFACE: tuple[str, ...] = (
    "app/lifecycle/__init__.py",
    "app/lifecycle/ingest/contracts.py",
    "app/lifecycle/models.py",
    "app/lifecycle/schemas/__init__.py",
    "app/lifecycle/schemas/opportunities.py",
    "app/lifecycle/schemas/pre_specs.py",
)

PUBLIC_NAME_IMPORTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("assembly", "core"): ("app/core/__init__.py",),
    # T4가 app/lifecycle/__init__.py를 만들면서 조립 계층 몫을 켰다.
    ("assembly", "lifecycle"): ("app/lifecycle/__init__.py",),
    ("screening", "lifecycle"): _LIFECYCLE_PUBLIC_SURFACE,
    ("deep_review", "lifecycle"): _LIFECYCLE_PUBLIC_SURFACE,
}

# 규칙을 적용할 대상 경로 범위. `None`이면 그 모듈이 소유한 파일 전부다.
#
# T6은 screening·deep_review → lifecycle을 `app/lifecycle/` 안으로만 켰다.
# lifecycle 소유 파일 상당수(app/ingest, app/services, app/routers, app/schemas)가
# 아직 폴더 밖에 있었기 때문이다. T7 3단계가 그 파일을 모두 들여오면서 범위를
# 전 범위(`None`)로 올렸다. lifecycle 소유 파일은 이제 하나도 폴더 밖에 없으므로
# 두 값은 같은 집합을 가리키고, 남아 있던 부채 항목은 0이 되어 원장에서 빠졌다.
PUBLIC_NAME_SCOPES: dict[tuple[str, str], str | None] = {
    ("assembly", "core"): None,
    ("assembly", "lifecycle"): None,
    ("screening", "lifecycle"): None,
    ("deep_review", "lifecycle"): None,
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
)

# 위 절이 아직 필요한 이유를 실제 코드에서 센 것이다. 값은 "그 절이 켜져
# 있었다면 위반이었을 import"의 개수이며, 허용 목록과 같은 계약을 따른다:
# 정확히 일치해야 하고 이주 task는 **줄이기만** 한다. 0이 되면 그 절을 검사 1에
# 넣을 수 있다는 신호이므로 테스트가 실패한다.
#
# T7 3단계 실측: 조립 계층 몫은 33 그대로다(경로가 바뀐 것도 없다 — 조립 계층이
# 직접 드는 것은 screening·deep_review 내부이고 그 둘은 2단계·1단계에 이미
# 옮겨졌다). "screening|deep_review->lifecycle(패키지 밖)" 80건은 0이 되어
# 항목째 사라졌다. lifecycle 소유 파일이 모두 `app/lifecycle/`로 들어왔고,
# 형제 모듈의 참조는 전부 공개 표면(`__init__`·`models`·`schemas`·
# `ingest/contracts`)이나 core로 옮겨졌기 때문이다. 그래서
# `PUBLIC_NAME_SCOPES`의 lifecycle 두 조합을 전 범위(None)로 켰다.
REMAINING_PUBLIC_NAME_DEBT: dict[str, int] = {
    "assembly->screening|deep_review": 33,
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
    # core·lifecycle·screening·deep_review
    # T7 1·2·3단계가 네 모듈의 소유 파일을 모두 자기 폴더로 옮겼다. 이제
    # 폴더 규칙(MODULE_FOLDERS)이 판정하므로 여기 남은 항목이 없다.
}

# 디렉터리 단위로 통째로 한 모듈에 속하는 경로 (§5.2).
DIRECTORY_MODULES: dict[str, str] = {
    # 조립 계층. alembic은 §4에 따라 models까지 import해도 된다.
    "alembic": ASSEMBLY,
}

# 한 파일에 네 모듈이 섞여 있어 파일 단위로 배정할 수 없는 파일.
# T6이 `app/models.py`를, T7 3단계가 `app/schemas/__init__.py`를 소유 모듈로
# 나눠 없앴으므로 비어 있다.
MIXED_FILES: frozenset[str] = frozenset()

# --- 명세 §5.2가 이름 단위로 쪼갠 service 파일 --------------------------------
# 파일은 본체가 가는 모듈에 배정하되(FILE_MODULES), §5.2가 다른 모듈로 옮길
# 이름을 명시적으로 열거한 곳은 그 이름만 따로 소유를 준다. 그러지 않으면
# "이미 다른 모듈로 가기로 정해진 이름"을 참조한 것이 거짓 위반이 된다.
# 열거되지 않은 이름은 파일 본체의 모듈(각 항목의 두 번째 값)로 본다.
SPLIT_FILE_NAME_MODULES: dict[str, tuple[dict[str, str], str]] = {
    # T7 3단계가 마지막 항목을 없앴다. §5.2 lifecycle의
    # "services/attachments.py의 attachment_download_url"은 이제
    # `app/lifecycle/api.py`에 있고, "services/prespec_attachments.py의
    # parse_attachment_key와 tracked_order_plan_connection*"은 T5b가
    # `services/opportunity_connections.py`로 옮겨 파일 단위로 lifecycle이 됐다.
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
