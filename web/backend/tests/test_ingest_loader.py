from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, init_db
from app.lifecycle.ingest.loader import (
    ORDER_PLAN_OBSERVATION_SNAPSHOT_SCHEMA,
    ingest_run,
    parse_order_plan_unty_no,
)
from app.screening.judgment_revisions import judgment_revision_payload
from app.core.generation_config import legacy_generation_config
from app.lifecycle.models import (
    IngestWarning,
    Notice,
    NoticeObservation,
    Opportunity,
    OpportunityLink,
    OrderPlan,
    OrderPlanObservation,
    Run,
)
from app.screening.models import (
    Counterargument,
    Judgment,
    JudgmentRevision,
    OrderPlanScreeningArtifact,
    OrderPlanScreeningBatchAttempt,
    OrderPlanScreeningExecution,
    OrderPlanScreeningResult,
    Perspective,
    Review,
    VerificationItem,
)
from app.screening.services.revisions import RevisionConflictError
from tests.postgres import migrated_engine, requires_postgres
from tests.screening.test_screening_orchestrator import _notice as screening_notice


def make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def notice(notice_id: str = "bid:TEST001:000") -> dict:
    return {
        "notice_id": notice_id,
        "source_type": "bid_notice",
        "title": "테스트 공고",
        "agency": "테스트 기관",
        "published_at": "2026-08-24T09:00:00",
        "deadline_at": "2026-08-31T18:00:00",
        "budget": "1000000",
        "estimated_price": "900000",
        "method": "일반경쟁",
        "url": "https://example.test/notice",
        "procurement_class": {"large": "ICT 서비스"},
        "region_limit": {},
        "lifecycle": {},
        "qualification_flags": {},
        "focus_matches": [],
        "performance_matches": [],
        "performance_top_score": 0,
        "candidate_sources": [],
        "collection_bucket": "candidate_pool",
        "unknown_fields": [],
        "raw_source": "raw/test.json",
        "sample_role": "analysis",
        "sample_stratum": "AI/데이터",
    }


def judgment(
    notice_id: str = "bid:TEST001:000",
    *,
    perspectives: list[dict] | None = None,
    grade: str | None = "우선 검토",
    readiness: str | None = "부분 확인 필요",
    counterarguments: list | None = None,
    verification_items: list | None = None,
) -> dict:
    value = {
        "notice_id": notice_id,
        "grade": grade,
        "readiness": readiness,
        "primary_focus": "AI/데이터",
        "summary": "요약",
        "next_action": "다음 행동",
    }
    if perspectives is not None:
        value["perspectives"] = perspectives
    if counterarguments is not None:
        value["counterarguments"] = counterarguments
    if verification_items is not None:
        value["verification_items"] = verification_items
    return value


def write_run(
    root: Path,
    *,
    directory_name: str = "20260817-20260823",
    validation: dict | None = None,
    screening: dict | None = None,
    decisions: dict | None = None,
    order_plans: dict | None = None,
    feedback: str | None = None,
) -> Path:
    run_dir = root / "runs" / directory_name
    run_dir.mkdir(parents=True, exist_ok=True)
    if validation is not None:
        (run_dir / "validation-set.json").write_text(
            json.dumps(validation, ensure_ascii=False), encoding="utf-8"
        )
    if screening is not None:
        (run_dir / "screening-results.json").write_text(
            json.dumps(screening, ensure_ascii=False), encoding="utf-8"
        )
    if decisions is not None:
        (run_dir / "screening-decisions.json").write_text(
            json.dumps(decisions, ensure_ascii=False), encoding="utf-8"
        )
    if order_plans is not None:
        (run_dir / "collected-order-plans.json").write_text(
            json.dumps(order_plans, ensure_ascii=False), encoding="utf-8"
        )
    if feedback is not None:
        report_dir = root / "reports" / run_dir.name
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "review-feedback.yaml").write_text(feedback, encoding="utf-8")
    return run_dir


def base_artifacts(*, generated_at: str = "2026-08-24T00:00:00+00:00") -> tuple[dict, dict, dict]:
    item = notice()
    validation = {
        "schema_version": "bidops.validation-set.v2",
        "source_window": {
            "from": "2026-08-17",
            "to": "2026-08-23",
            "timezone": "Asia/Seoul",
        },
        "notices": [item],
    }
    result_judgment = judgment(
        perspectives=[{"name": "기술 적합성", "assessment": "적합", "reason": "이유", "evidence": []}],
        counterarguments=[],
        verification_items=[],
    )
    screening = {
        "schema_version": "bidops.screening.v2",
        "generated_at": generated_at,
        "screening_basis": "메타데이터",
        "source_window": validation["source_window"],
        "results": [{"notice": item, "judgment": {k: v for k, v in result_judgment.items() if k != "notice_id"}}],
    }
    decisions = {
        "schema_version": "bidops.decisions.v2",
        "screening_basis": "메타데이터",
        "judgments": [result_judgment],
    }
    return validation, screening, decisions


@pytest.fixture(autouse=True)
def _screening_registered(screening_extensions):
    """이 파일의 회차 적재는 판정·리뷰까지 확인한다.

    판정 적재는 screening이 등록한 회차 적재 hook의 몫이므로(명세 §6.2), 전역
    registry에 그 등록이 남아 있는지에 기대지 않고 여기서 명시적으로 요구한다.
    """


@pytest.fixture
def db_session():
    engine = make_engine()
    init_db(engine)
    with Session(engine) as session:
        yield session


def test_loader_records_contract_gaps_and_keeps_available_rows(tmp_path, db_session):
    validation, screening, decisions = base_artifacts()
    run_dir = write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)

    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert result.notices == 1
    assert result.judgments == 1
    stored_notice = db_session.scalar(select(Notice))
    assert stored_notice is not None
    assert stored_notice.published_at.tzinfo is not None
    assert db_session.scalar(select(func.count()).select_from(Perspective)) == 1
    assert db_session.scalar(select(func.count()).select_from(Counterargument)) == 0
    assert db_session.scalar(select(func.count()).select_from(VerificationItem)) == 0
    codes = [warning["code"] for warning in result.warnings]
    assert "perspectives_below_contract" in codes
    assert "counterarguments_missing" in codes
    assert "verification_items_missing" in codes


def test_judgment_revision_payload_is_id_free_ordered_and_preserves_unknowns():
    raw = {
        "grade": "검토 권장",
        "readiness": "부분 확인 필요",
        "primary_focus": None,
        "exclusion_category": None,
        "summary": None,
        "next_action": "확인",
        "perspectives": [
            {
                "name": "기술 적합성",
                "assessment": "확인 불가",
                "reason": None,
                "evidence": [
                    {"source": "first", "status": "unknown", "fact": None},
                    {"source": "second", "status": "confirmed", "fact": "사실"},
                ],
            },
            {
                "position": 9,
                "name": "실적 정합성",
                "assessment": None,
                "reason": "대기",
                "evidence": [],
            },
        ],
        "counterarguments": ["첫 반론", {"position": 7, "text": None}],
        "counterargument_resolutions": [
            {
                "counterargument": "첫 반론",
                "status": "추가 확인",
                "reflection": "첫 반론을 확인 항목에 반영",
            },
            {
                "counterargument": None,
                "status": "수용",
                "reflection": "두 번째 반론 값도 그대로 보존",
            },
        ],
        "verification_items": [
            {"item": "자격", "why": None, "blocking": True, "status": "미확인"}
        ],
        "matched_performances": [
            {
                "project_name": "과거 사업",
                "match_reason": None,
                "mismatch_or_limit": "unknown",
                "source_page": "p.1",
                "legal_qualification_status": "unknown",
            }
        ],
    }

    payload = judgment_revision_payload(raw, schema_version="bidops.decisions.v2")

    assert list(payload) == [
        "schema_version",
        "grade",
        "readiness",
        "primary_focus",
        "exclusion_category",
        "summary",
        "next_action",
        "perspectives",
        "counterarguments",
        "counterargument_resolutions",
        "verification_items",
        "matched_performances",
    ]
    assert payload["primary_focus"] is None and payload["summary"] is None
    assert [item["source"] for item in payload["perspectives"][0]["evidence"]] == [
        "first",
        "second",
    ]
    assert payload["perspectives"][0]["position"] == 1
    assert payload["perspectives"][1]["position"] == 9
    assert payload["counterarguments"] == [
        {"position": 1, "text": "첫 반론"},
        {"position": 7, "text": None},
    ]
    assert payload["counterargument_resolutions"] == raw[
        "counterargument_resolutions"
    ]
    assert payload["matched_performances"][0]["status"] == "unknown"

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert "id" not in keys(payload)


def test_optional_order_plan_linkage_does_not_rewrite_old_notice_identity(tmp_path, db_session):
    validation, _screening, _decisions = base_artifacts()
    run_dir = write_run(tmp_path, validation=validation)

    ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    stored_notice = db_session.scalar(select(Notice))
    assert stored_notice is not None
    assert "order_plan_no" not in stored_notice.lifecycle_json


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"{malformed",
        b"{\n  \"schema_version\": \"bidops.screening-input.v1\"\n}",
    ],
)
def test_present_invalid_screening_input_never_falls_back_to_validation(tmp_path, db_session, raw: bytes):
    validation, _screening, _decisions = base_artifacts()
    run_dir = write_run(tmp_path, validation=validation)
    (run_dir / "screening-input.json").write_bytes(raw)
    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    assert result.notices == 0 and result.judgments == 0
    assert any(item["code"] == "screening_input_invalid" for item in result.warnings)
    assert db_session.scalar(select(func.count(Notice.id))) == 0


def test_loader_v3_input_is_fail_closed_for_duplicate_and_invalid_identity(tmp_path, db_session):
    run_dir = tmp_path / "runs" / "screen-run"
    run_dir.mkdir(parents=True)
    first = screening_notice("candidate-1")
    first.update({"judgment_mode": "신규", "carry_over_from": None, "rejudge_reason": None})
    value = {
        "schema_version": "bidops.screening-input.v1",
        "execution_id": "scr-" + "a" * 32,
        "run_id": "source-run",
        "generated_at": "2026-08-26T01:00:00+00:00",
        "source_window": {"from": "2026-08-25", "to": "2026-08-26", "timezone": "Asia/Seoul"},
        "policy_version": "policy-v1", "prompt_version": "prompt-v1",
        "company_profile_version": "company-profile.sha256:" + "b" * 64,
        "company_profile_digest": "b" * 64,
        "candidate_count": 2,
        "notices": [first, {**first}],
    }
    (run_dir / "screening-input.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    assert result.notices == 0
    assert db_session.scalar(select(func.count()).select_from(Notice)) == 0
    assert any(item["code"] == "screening_input_invalid" for item in result.warnings)


def test_legacy_v3_generation_binding_is_normalized_in_memory_and_run_projection(tmp_path, db_session):
    raw_notice = screening_notice("candidate-legacy")
    raw_notice.update({"judgment_mode": "신규", "carry_over_from": None, "rejudge_reason": None})
    source_window = {"from": "2026-08-25", "to": "2026-08-26", "timezone": "Asia/Seoul"}
    common = {
        "execution_id": "scr-" + "a" * 32,
        "run_id": "source-run",
        "generated_at": "2026-08-26T01:00:00+00:00",
        "prompt_version": "prompt-v1",
        "policy_version": "policy-v1",
        "company_profile_version": "company-profile.sha256:" + "b" * 64,
        "company_profile_digest": "b" * 64,
    }
    input_value = {
        "schema_version": "bidops.screening-input.v1",
        **common,
        "source_window": source_window,
        "candidate_count": 1,
        "notices": [raw_notice],
    }
    decisions_value = {
        "schema_version": "bidops.decisions.v3",
        **common,
        "screening_basis": "legacy",
        "model_name": "qwen-test",
        "model_digest": "c" * 64,
        "judgments": [],
    }
    results_value = {
        "schema_version": "bidops.screening.v3",
        "execution_id": common["execution_id"],
        "generated_at": common["generated_at"],
        "screening_basis": "legacy",
        "source_window": source_window,
        "model_name": "qwen-test",
        "model_digest": "c" * 64,
        "prompt_version": common["prompt_version"],
        "policy_version": common["policy_version"],
        "company_profile_version": common["company_profile_version"],
        "company_profile_digest": common["company_profile_digest"],
        "candidate_count": 1,
        "result_count": 0,
        "failure_count": 1,
        "partial_artifact": True,
        "failure_artifact": "screening-failures.json",
        "results": [],
    }
    run_dir = tmp_path / "runs" / "legacy-v3"
    run_dir.mkdir(parents=True)
    (run_dir / "screening-input.json").write_bytes(
        json.dumps(input_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    (run_dir / "screening-decisions.json").write_text(json.dumps(decisions_value), encoding="utf-8")
    (run_dir / "screening-results.json").write_text(json.dumps(results_value), encoding="utf-8")

    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    legacy = legacy_generation_config()
    assert result.generation_config == legacy.canonical_value()
    assert result.generation_config_digest == legacy.digest()
    stored_run = db_session.scalar(select(Run).where(Run.id == result.run_id))
    assert stored_run is not None
    assert stored_run.counts_json["generation_config"] == legacy.canonical_value()
    assert stored_run.counts_json["generation_config_digest"] == legacy.digest()
    assert b"generation_config" not in (run_dir / "screening-input.json").read_bytes()


def test_v3_generation_binding_partial_input_is_rejected_without_projection(tmp_path, db_session):
    run_dir = tmp_path / "runs" / "partial-v3"
    run_dir.mkdir(parents=True)
    value = {
        "schema_version": "bidops.screening-input.v1",
        "execution_id": "scr-" + "a" * 32,
        "run_id": "source-run",
        "generated_at": "2026-08-26T01:00:00+00:00",
        "source_window": {"from": "2026-08-25", "to": "2026-08-26", "timezone": "Asia/Seoul"},
        "policy_version": "policy-v1", "prompt_version": "prompt-v1",
        "company_profile_version": "company-profile.sha256:" + "b" * 64,
        "company_profile_digest": "b" * 64,
        "candidate_count": 0, "notices": [],
        "generation_config_digest": "f" * 64,
    }
    (run_dir / "screening-input.json").write_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )
    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    assert result.notices == 0
    assert any(item["code"] == "screening_input_invalid" for item in result.warnings)


def test_loader_preserves_long_screening_basis_without_truncation(tmp_path, db_session):
    validation, screening, decisions = base_artifacts()
    long_basis = "메타데이터와 공고 원문을 바탕으로 자격, 지역 제한, 수행 실적, 예산, 마감일을 교차 검토한 기준 " * 3
    screening["screening_basis"] = long_basis
    decisions["screening_basis"] = long_basis
    run_dir = write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)

    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    stored = db_session.get(Run, result.run_id)
    assert stored is not None
    assert stored.screening_basis == long_basis
    assert len(stored.screening_basis) > 64


def test_v1_schema_gap_is_a_warning_and_legacy_judgment_is_loaded(tmp_path, db_session):
    validation, screening, decisions = base_artifacts()
    decisions["schema_version"] = "bidops.decisions.v1"
    run_dir = write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)

    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert result.judgments == 1
    schema_warning = next(item for item in result.warnings if item["code"] == "decisions_schema_gap")
    assert schema_warning["context"] == {
        "actual": "bidops.decisions.v1",
        "expected": "bidops.decisions.v2",
    }
    perspective_warning = next(
        item for item in result.warnings if item["code"] == "perspectives_below_contract"
    )
    assert perspective_warning["context"]["schema_version"] == "bidops.decisions.v1"


def test_missing_core_judgment_field_is_not_loaded(tmp_path, db_session):
    validation, screening, decisions = base_artifacts()
    screening["results"][0]["judgment"]["grade"] = None
    decisions["judgments"][0]["grade"] = None
    run_dir = write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)

    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert result.notices == 1
    assert result.judgments == 0
    warning = next(item for item in result.warnings if item["code"] == "judgment_required_field_missing")
    assert warning["level"] == "error"
    assert warning["context"]["fields"] == ["grade"]


def test_missing_validation_stops_after_recording_error(tmp_path, db_session):
    run_dir = write_run(tmp_path)
    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert result.notices == 0
    assert result.judgments == 0
    assert any(item["code"] == "validation_missing" for item in result.warnings)
    assert db_session.scalar(select(func.count()).select_from(Run)) == 1


def test_order_plan_ingest_resolves_bid_first_waiting_reference(tmp_path, db_session):
    """A plan arriving in a later run reuses the bid-first opportunity."""

    reference = "R26DD20999999"
    bid_validation = {
        "schema_version": "bidops.validation-set.v2",
        "source_window": {
            "from": "2026-08-25",
            "to": "2026-08-26",
            "timezone": "Asia/Seoul",
        },
        "notices": [
            {
                **notice("bid:R26BK01696186:000"),
                "lifecycle": {
                    "pre_spec_no": None,
                    "re_notice": None,
                    "changed_at": None,
                    "change_reason": None,
                    "unified_notice_no": None,
                    "previous_failed_notice_no": None,
                    "order_plan_no": reference,
                },
            }
        ],
    }
    first_run_dir = write_run(
        tmp_path,
        directory_name="bid-first-run",
        validation=bid_validation,
    )
    first = ingest_run(first_run_dir, db_session, reports_root=tmp_path / "reports")
    assert first.notices == 1

    plan_artifact = {
        "schema_version": "bidops.collected-order-plans.v1",
        "generated_at": "2026-08-29T01:00:00+00:00",
        "source_window": {
            "from": "2026-08-25",
            "to": "2026-08-26",
            "timezone": "Asia/Seoul",
        },
        "counts": {"total": 1},
        "warnings": [],
        "order_plans": [
            {
                "order_plan_unty_no": reference,
                "title": "늦게 도착한 계획",
                "agency_code": "7430073",
                "agency_name": "테스트 기관",
                "supervising_agency_name": "상위 기관",
                "business_division": "일반용역",
                "business_division_code": "03",
                "service_type": "신규(단기)",
                "service_type_code": "신120001",
                "budget_amount": "100000000",
                "contract_amount": "0",
                "planned_order_year": "2027",
                "planned_order_month": "2027-09",
                "procurement_method": "자체조달",
                "contract_method": "제한경쟁",
                "sw_business_status": None,
                "published_at": "2026-08-25T18:56:27+09:00",
                "changed_at": None,
                "bid_ntice_no_list": "R26BK01696186000",
                "notice_posted": "Y",
                "rcrit_rgst_no": None,
                "source_url": "https://www.g2b.go.kr/link/plan",
                "first_discovered_at": "2026-08-25T18:56:27+09:00",
                "last_discovered_at": "2026-08-29T01:00:00+00:00",
                "source_sha256": "a" * 64,
                "unknown_fields": ["sw_business_status"],
                "raw_source": "raw/order-plan-page-00001.json",
            }
        ],
    }
    second_run_dir = write_run(
        tmp_path,
        directory_name="plan-later-run",
        order_plans=plan_artifact,
    )
    second = ingest_run(second_run_dir, db_session, reports_root=tmp_path / "reports")

    assert second.order_plans == 1
    plan = db_session.scalar(select(OrderPlan).where(OrderPlan.order_plan_unty_no == reference))
    assert plan is not None
    assert plan.title == "늦게 도착한 계획"
    assert plan.bid_ntice_no_list == "R26BK01696186000"
    assert plan.raw_source["unprojected_fields"] == {
        "sw_business_status": None,
        "rcrit_rgst_no": None,
    }
    assert db_session.scalar(select(func.count()).select_from(OrderPlanObservation)) == 1

    links = db_session.scalars(select(OpportunityLink)).all()
    plan_link = next(link for link in links if link.order_plan_id == plan.id)
    bid_link = next(link for link in links if link.notice_id is not None)
    assert plan_link.opportunity_id == bid_link.opportunity_id
    assert plan_link.evidence_bid_no == "R26BK01696186"
    assert plan_link.status == "확정"
    assert plan_link.notice_id is None
    assert db_session.scalar(select(func.count()).select_from(Opportunity)) == 1


def test_order_plan_ingest_maps_measured_g2b_fields_without_inference(tmp_path, db_session):
    reference = "R26DD20853714"
    artifact = {
        "schema_version": "bidops.collected-order-plans.v1",
        "generated_at": "2026-08-29T01:00:00+00:00",
        "source_window": {
            "from": "2026-08-25",
            "to": "2026-08-26",
            "timezone": "Asia/Seoul",
        },
        "counts": {"total": 1},
        "order_plans": [
            {
                "orderPlanUntyNo": reference,
                "bizNm": "실측 API 발주계획",
                "orderInsttCd": "1234567",
                "orderInsttNm": "발주기관",
                "totlmngInsttNm": "총괄기관",
                "bsnsDivCd": "03",
                "bsnsDivNm": "일반용역",
                "bsnsTyCd": "신120001",
                "bsnsTyNm": "신규(단기)",
                "sumOrderAmt": "123456789",
                "orderContrctAmt": "0",
                "orderYear": "2027",
                "orderMnth": "09",
                "prcrmntMethd": "자체조달",
                "cntrctMthdNm": "제한경쟁",
                "swBizObjYn": None,
                "nticeDt": "20260825185627",
                "chgDt": "",
                "bidNtceNoList": "R26BK01696186000",
                "ntceNticeYn": "Y",
                "rcritRgstNo": "",
                "orderPlanDtlUrl": "https://www.g2b.go.kr/order-plan",
                "source": {
                    "raw_ref": "raw/page-00001.json#payload.items/0",
                    "source_sha256": "b" * 64,
                },
                "future_field": "warning-only",
            }
        ],
    }
    run_dir = write_run(
        tmp_path,
        directory_name="measured-plan-run",
        order_plans=artifact,
    )

    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert result.order_plans == 1
    plan = db_session.scalar(select(OrderPlan))
    assert plan is not None
    assert plan.order_plan_unty_no == reference
    assert plan.title == "실측 API 발주계획"
    assert plan.budget_amount == 123456789
    assert plan.planned_order_month == "2027-09"
    assert plan.bid_ntice_no_list == "R26BK01696186000"
    assert plan.notice_posted == "Y"
    assert plan.source_url == "https://www.g2b.go.kr/order-plan"
    assert plan.source_sha256 == "b" * 64
    assert plan.raw_source == {
        "raw_ref": "raw/page-00001.json#payload.items/0",
        "unprojected_fields": {
            "swBizObjYn": None,
            "rcritRgstNo": "",
        },
    }
    observation = db_session.scalar(select(OrderPlanObservation))
    assert observation is not None
    assert observation.snapshot_schema_version == ORDER_PLAN_OBSERVATION_SNAPSHOT_SCHEMA
    assert observation.snapshot_jsonb["record"]["order_plan_unty_no"] == reference
    assert observation.snapshot_jsonb["record"]["raw_source"] == plan.raw_source
    assert observation.snapshot_jsonb["record"]["unknown_fields_json"] == plan.unknown_fields_json
    assert len(observation.source_sha256 or "") == 64
    assert any(
        warning["code"] == "unknown_field"
        and warning["context"]["field"] == "order_plan[0].future_field"
        for warning in result.warnings
    )


def test_collector_artifact_round_trips_through_ingest_run(tmp_path, db_session):
    """The real producer subprocess must create rows in the existing loader."""

    def digest(value):
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    source_item = {
        "orderPlanUntyNo": "R26DD20999999",
        "bizNm": "왕복 검증용 실측 발주계획",
        "orderInsttCd": "1234567",
        "orderInsttNm": "테스트 발주기관",
        "totlmngInsttNm": "테스트 총괄기관",
        "bsnsDivCd": "03",
        "bsnsDivNm": "일반용역",
        "bsnsTyCd": "신120001",
        "bsnsTyNm": "신규(단기)",
        "sumOrderAmt": "123456789",
        "orderContrctAmt": "0",
        "orderYear": "2027",
        "orderMnth": "09",
        "prcrmntMethd": "자체조달",
        "cntrctMthdNm": "제한경쟁",
        "nticeDt": "20260825185627",
        "chgDt": "20260826101010",
        "bidNtceNoList": "R26BK01696186000",
        "ntceNticeYn": "Y",
        "rcritRgstNo": "",
        "orderPlanDtlUrl": "https://www.g2b.go.kr/order-plan",
    }
    source_payload = {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "정상"},
            "body": {
                "totalCount": "1",
                "pageNo": "1",
                "numOfRows": "500",
                "items": [source_item],
            },
        }
    }
    query = {
        "pageNo": "1",
        "numOfRows": "500",
        "type": "json",
        "orderBgnYm": "200412",
        "orderEndYm": "999912",
        "inqryBgnDt": "202608250000",
        "inqryEndDt": "202608262359",
    }
    raw_input = tmp_path / "raw-fixture"
    raw_input.mkdir()
    (raw_input / "page-00001.json").write_text(
        json.dumps(
            {
                "schema_version": "bidops.collected-order-plans-raw-page.v1",
                "endpoint_id": "g2b_order_plan_service_pps_search_v1",
                "query": query,
                "page_no": 1,
                "request_attempts": 1,
                "collected_at": "2026-08-29T12:00:00+09:00",
                "payload_sha256": digest(source_payload),
                "payload": source_payload,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    project_root = Path(__file__).resolve().parents[3]
    producer = project_root / "skills/bidops-collect/scripts/collect_order_plans.py"
    run_dir = tmp_path / "runs" / "order-plan-roundtrip"
    completed = subprocess.run(
        [
            sys.executable,
            str(producer),
            "--from-date",
            "2026-08-25",
            "--to-date",
            "2026-08-27",
            "--from-raw",
            str(raw_input),
            "--output-dir",
            str(run_dir),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    artifact = json.loads(
        (run_dir / "collected-order-plans.json").read_text(encoding="utf-8")
    )
    assert artifact["schema_version"] == "bidops.collected-order-plans.v1"
    assert artifact["order_plans"][0]["rcrit_rgst_no"] is None
    assert artifact["order_plans"][0]["sw_business_status"] is None

    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert result.order_plans == 1
    assert not {
        warning["code"] for warning in result.warnings
    } & {"validation_missing", "screening_results_missing"}
    plan = db_session.scalar(
        select(OrderPlan).where(OrderPlan.order_plan_unty_no == "R26DD20999999")
    )
    assert plan is not None
    assert plan.title == "왕복 검증용 실측 발주계획"
    assert plan.budget_amount == 123456789
    assert plan.planned_order_month == "2027-09"
    assert plan.source_url == "https://www.g2b.go.kr/order-plan"
    assert plan.raw_source["unprojected_fields"] == {
        "sw_business_status": None,
        "rcrit_rgst_no": None,
    }
    assert db_session.scalar(select(func.count()).select_from(OrderPlanObservation)) == 1


# 생애주기 조사에서 입찰공고 1,628건 중 14건(0.9%)이 아래 두 형태를 가졌다.
# 형식을 추측해 억지로 파싱하지 않고, 원문을 링크에 보존해 사람이 볼 수 있게 둔다.
# ADR-0028: "해소 안 된 공식 참조번호는 링크에 보존한다."
@pytest.mark.parametrize(
    "nonstandard_no",
    ["204200-2026-S-01200", "P812026007CB-00"],
)
def test_nonstandard_order_plan_number_is_preserved_not_treated_as_absent(
    tmp_path, db_session, nonstandard_no
):
    validation = {
        "schema_version": "bidops.validation-set.v2",
        "source_window": {"from": "2026-08-24", "to": "2026-08-26", "timezone": "Asia/Seoul"},
        "notices": [
            {
                **notice("bid:R26BK01696190:000"),
                "lifecycle": {"order_plan_no": nonstandard_no},
            }
        ],
    }
    run_dir = write_run(tmp_path, directory_name="nonstandard-plan-no", validation=validation)
    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    assert result.notices == 1

    # 파싱은 실패해야 한다. 임의 추출로 그럴듯한 키를 만들어 내면 안 된다.
    assert parse_order_plan_unty_no(nonstandard_no) is None

    # 그러나 그 사실이 "발주계획 없음"을 뜻하지는 않는다. 원문이 링크에 남는다.
    links = db_session.scalars(select(OpportunityLink)).all()
    preserved = [link for link in links if link.evidence_external_no == nonstandard_no]
    assert preserved, "비표준 계획번호가 링크에 보존되지 않았다"
    assert preserved[0].link_type == "official"
    assert preserved[0].order_plan_id is None

    # 공고 자체는 정확히 하나의 사업기회에 속한다 (ADR-0028).
    assert db_session.scalar(select(func.count()).select_from(Opportunity)) == 1


def test_standard_order_plan_number_still_parses(tmp_path, db_session):
    assert parse_order_plan_unty_no("R26DD20853714") == "R26DD20853714"


def test_missing_screening_loads_notices_only(tmp_path, db_session):
    validation, _, _ = base_artifacts()
    run_dir = write_run(tmp_path, validation=validation)
    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert result.notices == 1
    assert result.judgments == 0
    assert any(item["code"] == "screening_results_missing" for item in result.warnings)


@pytest.mark.parametrize(
    "decisions_schema", ["bidops.decisions.v1", "bidops.decisions.v2"]
)
def test_reingest_is_idempotent_and_cleans_old_warnings(
    tmp_path, db_session, decisions_schema
):
    validation, screening, decisions = base_artifacts()
    decisions["schema_version"] = decisions_schema
    run_dir = write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)
    first = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    first_counts = {
        model.__tablename__: db_session.scalar(select(func.count()).select_from(model))
        for model in (Notice, Judgment, JudgmentRevision, Perspective, Counterargument, VerificationItem, IngestWarning)
    }
    second = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    second_counts = {
        model.__tablename__: db_session.scalar(select(func.count()).select_from(model))
        for model in (Notice, Judgment, JudgmentRevision, Perspective, Counterargument, VerificationItem, IngestWarning)
    }

    assert first.run_id == second.run_id
    assert first_counts == second_counts
    assert second_counts["ingest_warning"] == len(second.warnings)
    revision = db_session.scalar(select(JudgmentRevision))
    assert revision is not None
    assert revision.source_kind == "legacy_import" and revision.run_id == first.run_id


@pytest.mark.parametrize(
    "decisions_schema", ["bidops.decisions.v1", "bidops.decisions.v2"]
)
def test_legacy_replay_conflict_rolls_back_revision_and_current_projection(
    tmp_path, db_session, decisions_schema
):
    validation, screening, decisions = base_artifacts()
    decisions["schema_version"] = decisions_schema
    run_dir = write_run(
        tmp_path, validation=validation, screening=screening, decisions=decisions
    )
    first = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    stored = db_session.scalar(select(Judgment))
    assert stored is not None and stored.grade == "우선 검토"
    revision = db_session.scalar(select(JudgmentRevision))
    assert revision is not None and revision.sequence == 1

    screening["results"][0]["judgment"]["grade"] = "검토 권장"
    decisions["judgments"][0]["grade"] = "검토 권장"
    write_run(
        tmp_path, validation=validation, screening=screening, decisions=decisions
    )

    with pytest.raises(RevisionConflictError, match="legacy import run"):
        ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    db_session.expire_all()
    stored = db_session.scalar(select(Judgment))
    assert stored is not None and stored.grade == "우선 검토"
    revisions = db_session.scalars(select(JudgmentRevision)).all()
    assert len(revisions) == 1 and revisions[0].id == revision.id
    assert db_session.get(Run, first.run_id) is not None


def test_projection_failure_after_append_rolls_back_revision_and_projection(
    tmp_path, db_session, monkeypatch
):
    validation, screening, decisions = base_artifacts()
    first_dir = write_run(
        tmp_path,
        directory_name="revision-transaction-one",
        validation=validation,
        screening=screening,
        decisions=decisions,
    )
    ingest_run(first_dir, db_session, reports_root=tmp_path / "reports")
    stored = db_session.scalar(select(Judgment))
    assert stored is not None
    original_id = stored.id
    original_grade = stored.grade
    original_revision_ids = [
        item.id for item in db_session.scalars(select(JudgmentRevision)).all()
    ]

    screening["generated_at"] = "2026-08-24T01:00:00+00:00"
    screening["results"][0]["judgment"]["grade"] = "검토 권장"
    decisions["judgments"][0]["grade"] = "검토 권장"
    second_dir = write_run(
        tmp_path,
        directory_name="revision-transaction-two",
        validation=validation,
        screening=screening,
        decisions=decisions,
    )

    def fail_after_revision_append(*_args, **_kwargs):
        raise RuntimeError("injected projection failure")

    # 판정 projection 교체는 screening 적재기의 일이다(명세 §6.2).
    monkeypatch.setattr("app.screening.ingest._clear_judgment", fail_after_revision_append)
    with pytest.raises(RuntimeError, match="injected projection failure"):
        ingest_run(second_dir, db_session, reports_root=tmp_path / "reports")

    db_session.expire_all()
    stored = db_session.scalar(select(Judgment))
    assert stored is not None and stored.id == original_id
    assert stored.grade == original_grade
    assert [
        item.id for item in db_session.scalars(select(JudgmentRevision)).all()
    ] == original_revision_ids


def test_feedback_only_creates_nonempty_review_and_does_not_overwrite_it(tmp_path, db_session):
    validation, screening, decisions = base_artifacts()
    feedback = """schema_version: bidops.feedback.v2
reviews:
  - notice_id: bid:TEST001:000
    disposition: 관찰
    system_judgment_review: null
    corrected_grade: null
    corrected_readiness: null
    weakest_perspective: null
    reason: ""
    verification_answers: []
  - notice_id: bid:TEST001:000
    disposition: null
    system_judgment_review: null
    corrected_grade: null
    corrected_readiness: null
    weakest_perspective: null
    reason: ""
    verification_answers: []
"""
    run_dir = write_run(
        tmp_path,
        validation=validation,
        screening=screening,
        decisions=decisions,
        feedback=feedback,
    )
    first = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    review = db_session.scalar(select(Review))
    assert first.reviews == 1
    assert review is not None and review.disposition == "관찰"

    (tmp_path / "reports" / run_dir.name / "review-feedback.yaml").write_text(
        feedback.replace("disposition: 관찰", "disposition: 제외"), encoding="utf-8"
    )
    ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    db_session.refresh(review)
    assert review.disposition == "관찰"
    assert db_session.scalar(select(func.count()).select_from(Review)) == 1


def test_new_generated_at_creates_snapshot_and_supersedes_previous(tmp_path, db_session):
    validation, screening, decisions = base_artifacts()
    run_dir = write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)
    first = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    screening["generated_at"] = "2026-08-24T01:00:00+00:00"
    write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)
    second = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert first.run_id != second.run_id
    runs = db_session.scalars(select(Run).order_by(Run.id)).all()
    assert runs[0].status == "superseded"
    assert runs[0].superseded_by == runs[1].id
    assert db_session.scalar(select(func.count()).select_from(Notice)) == 1
    assert db_session.scalar(select(func.count()).select_from(NoticeObservation)) == 2


def test_real_run_integration_if_artifacts_are_available(tmp_path, db_session):
    project_root = Path(__file__).resolve().parents[3]
    run_dir = project_root / "data" / "runs" / "20260817-20260823"
    if not all((run_dir / name).is_file() for name in ("validation-set.json", "screening-results.json")):
        pytest.skip("실제 회차 산출물이 없습니다")

    result = ingest_run(run_dir, db_session, reports_root=project_root / "reports")

    assert result.notices == 40
    assert result.judgments == 40
    assert db_session.scalar(select(func.count()).select_from(IngestWarning)) >= 0
