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
            # 여러 공고의 판정을 한 번에 읽는 batch 판. 지금은 screening 안에서만
            # 쓰이고(`projection.py`의 단건 조회가 이것을 부른다) deep_review는
            # 부르지 않는다. 목록 화면의 등급·판정 표시는 projection이 자기 쿼리로
            # 채운다. 밖으로 나갈 때 다른 이름을 새로 만들지 않도록 seam에 남긴다.
            "current_judgments",
            "latest_corrected_grade",
            # 그 batch 판. 사전규격 목록 projection과 첨부 자격 재평가는 공고
            # 수백~수천 건의 effective grade를 한 번에 필요로 하고, 명세 §8이
            # 그 자리에 N+1을 금지한다. 단건 판만 seam에 두면 호출부가 공고당
            # 조회를 만들 수밖에 없으므로 같은 읽기 전용 seam으로 함께 둔다.
            "latest_corrected_grades",
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
# 쓰기와 잠금 역시 `__init__.py`의 함수로 제한된다. 그 제한은 이 검사(1번)가
# 아니라 **검사 5**(`check_lifecycle_table_writes`)가 진다 — 모델 클래스가 공개
# 이름인 이상 import 방향만 봐서는 `session.add(Notice(...))`와
# `select(Notice).with_for_update()`를 구분할 수 없기 때문이다.
_LIFECYCLE_PUBLIC_SURFACE: tuple[str, ...] = (
    "app/lifecycle/__init__.py",
    "app/lifecycle/ingest/contracts.py",
    "app/lifecycle/models.py",
    "app/lifecycle/schemas/__init__.py",
    # DEMO-02 회사 지식 읽기 DTO가 CompanyDTO를 재사용한다(데모 계약 §8).
    "app/lifecycle/schemas/companies.py",
    # RL-02 활동 피드 hook의 `ActivityItem`. RL-03·04 제공자가 이 DTO를 만들어 돌려준다.
    "app/lifecycle/schemas/opportunity_activity.py",
    "app/lifecycle/schemas/opportunities.py",
    "app/lifecycle/schemas/pre_specs.py",
)

PUBLIC_NAME_IMPORTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("assembly", "core"): ("app/core/__init__.py",),
    # T4가 app/lifecycle/__init__.py를 만들면서 조립 계층 몫을 켰다.
    ("assembly", "lifecycle"): ("app/lifecycle/__init__.py",),
    # T8 1단계가 screening·deep_review의 공개 표면(__init__)을 만들면서 마지막
    # 조합 둘을 켰다. 조립 계층은 이제 네 모듈 모두를 `__init__`의 이름으로만
    # 받는다 — router 인스턴스도, 모듈 runtime도, worker 진입 함수도 그렇다.
    # 형제 모듈에게 열어 둔 models·schemas·contracts는 조립 계층 몫이 아니다
    # (그 파일들은 §4에서 lifecycle → screening·deep_review 방향의 계약이다).
    ("assembly", "screening"): ("app/screening/__init__.py",),
    ("assembly", "deep_review"): ("app/deep_review/__init__.py",),
    ("screening", "lifecycle"): _LIFECYCLE_PUBLIC_SURFACE,
    ("deep_review", "lifecycle"): _LIFECYCLE_PUBLIC_SURFACE,
}

# --- 검사 6: 앱 startup이 해서는 안 되는 일 -----------------------------------
#
# "앱 startup은 migration·seed·정책 활성화·모델 호출을 수행하지 않는다"는 경계는
# 검사 1~5 어느 것도 지키지 못한다. 조립 계층 → 모듈 **공개 이름**은 허용 방향
# 이므로, `app/main.py`가 `from .screening import activate_policy, seed_policy`를
# 하고 startup에서 부르면 경계가 깨지는데도 위반이 하나도 잡히지 않는다.
#
# 그래서 "무엇을 import할 수 있는가"가 아니라 **어느 파일이 어떤 이름을 받을 수
# 있는가**로 못박는다. 아래 두 값이 그 데이터다.

#: startup 경로에 있는 조립 계층 파일. 여기 있는 파일의 import는 서비스되는 앱이
#: 뜰 때 실행된다.
#:
#: `app/workers/analysis.py`와 `app/migrations/import_sqlite.py`는 조립 계층이지만
#: **별도 프로세스 진입점**이다. 그 둘은 모델을 부르고 행을 쓰는 것이 하는 일
#: 자체이므로 이 검사의 대상이 아니다 — 대상으로 삼으면 정당한 일을 막는다.
#: `alembic/`도 migration을 실행하는 것이 그 존재 이유라 대상이 아니다.
STARTUP_FILES: tuple[str, ...] = (
    "app/__init__.py",
    "app/main.py",
    "app/runtime.py",
)

#: startup 파일이 모듈 공개 표면에서 받아서는 안 되는 이름. 실제 코드에서 골랐다.
#:
#: 두 부류다.
#: - **상태를 바꾼다**: 정책을 만들거나 후보로 지정하거나 활성화하는 것, 기본 행을
#:   심는 것(seed), 회사 프로필 스냅샷을 새로 쓰는 것, 회차를 적재하거나 지우는 것.
#: - **모델을 부른다**: 모델 클라이언트와 그것을 돌리는 실행기.
#:
#: 이 이름들이 지금 모듈 공개 표면에 없더라도 목록에 남긴다. 검사는 "지금 위반이
#: 있는가"가 아니라 "이 이름이 startup으로 들어오면 실패한다"를 고정하는 것이고,
#: 다시 공개하면서 startup에서 부르는 것이 정확히 막고 싶은 변경이다.
STARTUP_FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        # 상태 변경 — 판정 정책 (app/screening/policy.py)
        "activate_policy",
        "create_policy",
        "designate_policy_candidate",
        "seed_policy",
        # 상태 변경 — 기본 행 seed (app/lifecycle/api.py)
        "seed_default_portals",
        # 상태 변경 — 회사 프로필 스냅샷 (app/screening/profile_snapshot.py)
        "create_profile_snapshot",
        # 상태 변경 — 회차 적재·삭제 (app/lifecycle/api.py)
        "ingest_run",
        "delete_run",
        # 모델 호출 (app/screening/model_adapter.py, app/screening/worker.py)
        "ScreeningModelClient",
        "ScreeningOrchestrator",
        "ScreeningWorker",
    }
)


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
    # T8 1단계가 전 범위로 켰다. screening·deep_review의 소유 파일은 T7이 모두
    # 자기 폴더로 들여왔으므로 좁힐 범위가 없다.
    ("assembly", "screening"): None,
    ("assembly", "deep_review"): None,
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

# §8-1이 열거한 "공개 이름 대 모듈 내부" 절은 이제 전부 켜져 있다. T3가 core를,
# T4가 조립 계층 → lifecycle을, T6·T7 3단계가 screening·deep_review → lifecycle을,
# T8 1단계가 조립 계층 → screening·deep_review를 켰다. 남은 부채가 없으므로
# 미구현 절 목록과 그것을 세던 원장(`REMAINING_PUBLIC_NAME_DEBT`)은 지웠다.
# 네 조합 모두 검사 1이 직접 강제한다.

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
    # gpu_rest.py는 app/core/ 폴더 안에 있어 폴더 규칙으로도 CORE로 판정되지만,
    # S11 회귀(원래 app/workers/gpu_rest.py였고 FILE_MODULES에 없어 미배정으로
    # 잡혔다)를 명시적으로 남기기 위해 여기에도 적어 둔다.
    "app/core/gpu_rest.py": CORE,
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
    # lifecycle (19)
    "run": LIFECYCLE,
    "notice": LIFECYCLE,
    "notice_observation": LIFECYCLE,
    "order_plan": LIFECYCLE,
    "order_plan_observation": LIFECYCLE,
    "opportunity": LIFECYCLE,
    "opportunity_link": LIFECYCLE,
    "company": LIFECYCLE,
    "company_opportunity_tracking": LIFECYCLE,
    "company_tracking_event": LIFECYCLE,
    "attachment": LIFECYCLE,
    "agency_portal": LIFECYCLE,
    "ingest_warning": LIFECYCLE,
    "collected_record_index": LIFECYCLE,
    "collected_record_token": LIFECYCLE,
    "briefing": LIFECYCLE,
    "briefing_item": LIFECYCLE,
    "briefing_reaction_event": LIFECYCLE,
    "opportunity_note": LIFECYCLE,
    # screening (32)
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
    "order_plan_screening_quality_gate": SCREENING,
    "order_plan_screening_quality_evaluation": SCREENING,
    "order_plan_screening_audit_sample": SCREENING,
    "order_plan_screening_daily_trigger": SCREENING,
    # deep_review (51)
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
    "knowledge_ontology_version": DEEP_REVIEW,
    "company_knowledge_source": DEEP_REVIEW,
    "company_knowledge_version": DEEP_REVIEW,
    "company_knowledge_node": DEEP_REVIEW,
    "company_knowledge_edge": DEEP_REVIEW,
    "company_knowledge_binding": DEEP_REVIEW,
    "company_knowledge_binding_event": DEEP_REVIEW,
    "company_fit_policy_version": DEEP_REVIEW,
    "analysis_policy_version": DEEP_REVIEW,
    "work_job": DEEP_REVIEW,
    "deep_review": DEEP_REVIEW,
    "deep_review_attempt": DEEP_REVIEW,
    "deep_review_stage": DEEP_REVIEW,
    "deep_review_preview": DEEP_REVIEW,
    "deep_review_approval": DEEP_REVIEW,
    # RL-03 card analysis (0040).
    "transfer_policy_approval": DEEP_REVIEW,
    "card_analysis_stage": DEEP_REVIEW,
    "verdict_request": DEEP_REVIEW,
    "verdict_feedback": DEEP_REVIEW,
    "assumption_input_version": DEEP_REVIEW,
    "assumption_run": DEEP_REVIEW,
    "assumption_stage": DEEP_REVIEW,
    "claim": DEEP_REVIEW,
    "evidence_ref": DEEP_REVIEW,
    "claim_evidence": DEEP_REVIEW,
    "report_revision": DEEP_REVIEW,
    "report_revision_evidence": DEEP_REVIEW,
    "validation_run": DEEP_REVIEW,
    "validation_check": DEEP_REVIEW,
    "final_opinion": DEEP_REVIEW,
    "prespec_overview_run": DEEP_REVIEW,
    "prespec_company_fit_attempt": DEEP_REVIEW,
    "prespec_v4_pdf_snapshot": DEEP_REVIEW,
    "bid_delta_comparison": DEEP_REVIEW,
    "bid_delta_attempt": DEEP_REVIEW,
    "bid_delta_item": DEEP_REVIEW,
    "bid_delta_evidence": DEEP_REVIEW,
    "bid_final_decision": DEEP_REVIEW,
    "document_segment_manifest": DEEP_REVIEW,
    "document_segment": DEEP_REVIEW,
    "requirement_inventory_item": DEEP_REVIEW,
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

# 검사 1(§4 방향·공개 이름)의 **대상 범위**에서 빼는 폴더.
#
# 이것은 검사를 느슨하게 만든 것이 아니라, 명세가 정한 대상 범위로 되돌린
# 것이다. §8-1은 검사 1의 대상을 이렇게 못박았다:
#
#   "1. `app/` 아래 모든 `.py`(조립 계층 포함)와 `tests/<module>/` 아래 모든
#    `.py`의 import를 AST로 읽어 §4의 허용 표와 다른 모듈 간 import가 있으면
#    실패한다. 조립 계층은 모듈 공개 이름만, `alembic/`은 models까지 허용한다."
#
# 여기서 "조립 계층"은 `app/` 안의 파일(`app/main.py`·`app/runtime.py`·
# `app/workers/analysis.py`·`app/migrations/import_sqlite.py`)을 가리키고,
# 대상으로 열거된 테스트는 `tests/<module>/`뿐이다. 그런데 모듈은
# core·lifecycle·screening·deep_review 넷이고, `tests/app/`은 §5.4가
#
#   "앱 조립·migration·runtime 계약·두 모듈 이상이 합쳐지는 통합 검사는
#    `tests/app/`"
#
# 라고 정한 자리다. 즉 `tests/app/`은 `tests/<module>/`이 아니며 §8-1이
# 열거한 대상이 아니다. 검사기가 `tests/app`을 조립 계층으로 함께 묶어 "조립
# 계층은 모듈 공개 이름만" 규칙을 여기까지 적용하면, §5.4가 명시적으로
# `tests/app/`에 두라고 한 통합 검사(두 모듈 이상의 fixture를 심고, migration·
# runtime 계약을 확인하고, 루트 공용 harness를 쓰는 테스트)가 하나도 성립하지
# 못한다. 그 과잉은 §2 완료 기준 1("각 모듈이 자기 테스트를 자기 폴더 안에
# 갖는다")과 §5.4의 배치를 동시에 불가능하게 만든다.
#
# **production 코드의 보장은 한 치도 줄지 않는다.** `app/**`(조립 계층 포함)과
# `alembic/`, 그리고 `tests/core`·`tests/lifecycle`·`tests/screening`·
# `tests/deep_review`에 대한 검사 1은 그대로다. 여기서 빠지는 것은
# `tests/app/`뿐이고, 검사 2·3·4는 `tests/app/`에도 그대로 적용된다.
CHECK_ONE_EXEMPT_FOLDERS: tuple[str, ...] = ("tests/app",)

# §5.4가 `tests/` 루트에 남긴다고 못박은 것: "`conftest.py`, `postgres.py`,
# `fakes/`, `fixtures/`, `c2_fixtures.py`는 `tests/` 루트에 남는다."
# 나머지 테스트는 모두 모듈 폴더나 `tests/app/` 안에 있어야 한다.
TESTS_ROOT_ALLOWED_FILES: frozenset[str] = frozenset(
    {
        "__init__.py",
        "conftest.py",
        "postgres.py",
        "c2_fixtures.py",
    }
)

# 같은 §5.4가 루트에 남긴 디렉터리와, 모듈 폴더 넷 + `tests/app`.
TESTS_ROOT_ALLOWED_DIRS: frozenset[str] = frozenset(
    {"fakes", "fixtures", "core", "lifecycle", "screening", "deep_review", "app"}
)
