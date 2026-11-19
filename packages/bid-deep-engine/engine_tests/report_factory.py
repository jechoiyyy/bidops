"""리포트 테스트용 합성 Analysis·rfp.json·out 디렉터리 빌더(spec M2-05 "테스트 케이스").

M2-04 pydantic 모델(`bid_deep_engine.analysis.schemas`)로 만들고 네트워크·API를 쓰지 않는다.
`created_at`은 `CREATED_AT`으로 고정이다(결정성 테스트).

기본 Analysis(`make_analysis()`)는 9개 섹션이 모두 비어 있지 않게 채워져 있다:
게이트 4개(PASS 2·UNKNOWN 1·RISK 1), 정량 점수 1개(+ 같은 item의 평가 인용), 적합도 2개
(SFR-001 FULL, SFR-002 PARTIAL), 리스크 2개(인력·계약), 체크리스트·확인 필요 항목 각 1개,
권고 CONDITIONAL_GO(score_breakdown = M2-04 고정 키 13개, `SCORE_BREAKDOWN`).

사용법:

    a = make_analysis()                                     # 기본
    a = make_analysis(gates=[], fits=[])                    # Analysis 필드 교체
    a = make_analysis(facts=make_facts(project={"name": None}))   # 사실 일부 교체
    a = make_analysis(recommendation=make_recommendation(decision="GO", fit_score=88))
    g = make_gate("SME_CERT", "UNKNOWN", evidence=[make_evidence(verified=False)])

    slug_dir = write_slug(tmp_path, "a", analysis=a, rfp=make_rfp(title="강원대 홈페이지 구축"))
    write_slug(tmp_path, "x", analysis_text="{broken", report_md="이전 리포트\\n")

`make_facts(**overrides)`의 `project`·`schedule`·`evaluation`·`contract_terms`는 dict면 기본값에
얕게 덮어쓰고(모델이면 그대로), 나머지 RfpFacts 필드는 그대로 교체한다. `make_recommendation`도
같은 방식(필드 교체). 빌더는 pydantic 검증을 거친 모델을 돌려준다.
"""

import html as html_lib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from bid_deep_engine.analysis.schemas import (
    Analysis,
    ChecklistItem,
    CommercialSw,
    ContractTerms,
    DataToConfirm,
    EvalItem,
    Evaluation,
    Evidence,
    GateResult,
    Profitability,
    Project,
    QualItem,
    Recommendation,
    RequirementFit,
    RfpFacts,
    Risk,
    Schedule,
    ScoreEstimate,
    StaffingReq,
    SubmissionDoc,
)
from bid_deep_engine.ingest.models import (
    Format,
    NoticeBundle,
    NoticeMeta,
    Requirement,
    RfpDocument,
    Section,
    SourceFile,
    SourceQuality,
)

CREATED_AT = "2026-01-01T09:00:00+09:00"

# report.html 판단 배너(A안, 2026-10-25): 큰 결정 라벨 + (확실성) + 이유 줄
_VERDICT_RE = re.compile(
    r'<p class="big">([^<]+?)(?: <span class="cert">\(([^<]+)\)</span>)?</p>\n'
    r'<p class="reason">([^<]*)</p>'
)


def html_judgment_line(html: str) -> str | None:
    """report.html 판단 배너를 md 판단 줄 형식(`판단: X (확실성) — 이유`)으로 되돌린다.
    md·html이 같은 판단 값을 보이는지 비교할 때 쓴다. 배너가 없으면 None."""
    m = _VERDICT_RE.search(html)
    if m is None:
        return None
    big, certainty, reason = (html_lib.unescape(g) if g else g for g in m.groups())
    if certainty is None:
        return f"판단: {big.removeprefix('판단 ')} — {reason}"
    return f"판단: {big} ({certainty}) — {reason}"


# M2-04 recommend.py 고정 키 13개(spec M2-05 T13 값; numeric_facts_unconfirmed는 배치 리뷰 B2).
SCORE_BREAKDOWN: dict[str, Any] = {
    "base": 62.5,
    "base_source": "fits",
    "fit_counts": {"FULL": 1, "PARTIAL": 1, "GAP": 0, "UNKNOWN": 0},
    "gate_counts": {"PASS": 2, "FAIL": 0, "UNKNOWN": 1, "RISK": 1},
    "penalty": -15.0,
    "raw": 47.5,
    "fit_score": 48,
    "weights": {"FULL": 100, "PARTIAL": 50, "GAP": 0, "RISK": -10, "UNKNOWN": -5, "EMPTY_BASE": 50},
    "thresholds": {"GO": 70, "CONDITIONAL": 40},
    "policy_unknown": ["seoul_resident_ok"],
    "min_contract": {"budget_krw": 430000000, "min_contract_amount_krw": None, "applied": False},
    "numeric_facts_unconfirmed": False,
    "decision_rule": "guarded",
}


def make_evidence(
    quote: str = "합성 원문 인용",
    section_id: str | None = "S001",
    page: int | None = 1,
    *,
    verified: bool | None = True,
    repaired: bool | None = False,
) -> Evidence:
    """인용 하나. 기본은 검증됨(verified True)·교정 없음."""
    return Evidence(
        quote=quote, section_id=section_id, page=page, verified=verified, repaired=repaired
    )


def make_gate(
    code: str = "G2B_REGISTERED",
    verdict: str = "PASS",
    *,
    rule_text: str = "합성 참가자격",
    company_value: str = "등록",
    evidence: list[Evidence] | None = None,
    action: str | None = None,
    unknown_fields: list[str] | None = None,
) -> GateResult:
    """게이트 하나. evidence 기본은 인용 1건(빈 리스트를 주면 파생 게이트처럼 인용 없음)."""
    return GateResult(
        code=code,  # type: ignore[arg-type]
        rule_text=rule_text,
        company_value=company_value,
        verdict=verdict,  # type: ignore[arg-type]
        evidence=[make_evidence()] if evidence is None else evidence,
        action=action,
        unknown_fields=unknown_fields or [],
    )


def make_score(
    item: str = "신용평가",
    *,
    kind: str = "CREDIT_RATING",
    max_points: float = 10.0,
    est_min: float = 2.5,
    est_max: float = 10.0,
    basis: str = "신용등급 미확인: 최저~최고 구간",
    unknown_inputs: list[str] | None = None,
) -> ScoreEstimate:
    return ScoreEstimate(
        item=item,
        kind=kind,  # type: ignore[arg-type]
        max_points=max_points,
        est_min=est_min,
        est_max=est_max,
        basis=basis,
        unknown_inputs=unknown_inputs or [],
    )


def make_fit(
    req_id: str = "SFR-001",
    fit: str = "FULL",
    *,
    rationale: str = "유사 실적 보유",
    evidence_portfolio_ids: list[str] | None = None,
    evidence_pages: list[str] | None = None,
    gap_action: str | None = None,
    evidence: Evidence | None = None,
    no_evidence: bool = False,
) -> RequirementFit:
    """적합도 하나. evidence 기본은 인용 1건, `no_evidence=True`면 None."""
    return RequirementFit(
        req_id=req_id,
        fit=fit,  # type: ignore[arg-type]
        rationale=rationale,
        evidence_portfolio_ids=evidence_portfolio_ids or [],
        evidence_pages=evidence_pages or [],
        gap_action=gap_action,
        evidence=None if no_evidence else (evidence or make_evidence()),
    )


def make_risk(
    category: str = "계약",
    severity: str = "M",
    *,
    description: str = "합성 리스크",
    evidence: Evidence | None = None,
    mitigation: str | None = None,
) -> Risk:
    return Risk(
        category=category,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        description=description,
        evidence=evidence or make_evidence(),
        mitigation=mitigation,
    )


def _merge(model_cls: type, default: dict[str, Any], value: Any) -> Any:
    if isinstance(value, dict):
        return model_cls.model_validate({**default, **value})
    return value


def _project() -> dict[str, Any]:
    return {
        "name": "합성 홈페이지 유지관리",
        "agency": "합성부",
        "agency_type": "중앙행정",
        "budget_krw": 430_000_000,
        "budget_note": None,
        "vat_included": True,
        "is_fixed_price": False,
        "period": {"start": "2027-01-01", "end": "2027-12-31", "days": None, "months": 12},
        "contract_method": "협상에 의한 계약",
        "bidding_method": "제한경쟁",
        "evidence": [make_evidence("사업금액 430,000,000원(부가세 포함)", "S001", 1)],
    }


def _schedule() -> dict[str, Any]:
    return {
        "notice_date": "2026-10-01",
        "submission_deadline": "2026-11-05 10:00",
        "evidence": [make_evidence("제안서 제출 마감 2026.11.05 10:00", "S002", 2)],
    }


def _evaluation() -> dict[str, Any]:
    return {
        "tech_weight": 90,
        "price_weight": 10,
        "qualifying_rule": "기술능력평가 점수 85점 이상",
        "qualifying_threshold": 85.0,
        "qualifying_basis": "points",
        "quantitative": [
            EvalItem(
                item="신용평가",
                max_points=10.0,
                kind="CREDIT_RATING",
                evidence=make_evidence("신용평가 등급 10점", "S005", 7),
            )
        ],
        "qualitative": [QualItem(item="사업 이해도", max_points=20.0)],
        "evidence": [make_evidence("기술 90 : 가격 10", "S005", 7)],
    }


def _contract_terms() -> dict[str, Any]:
    return {
        "subcontract": {"allowed": False},
        "consortium": {"allowed": True, "type": "공동이행"},
        "warranty_months": 12,
        "evidence": [make_evidence("하자보수 기간 12개월", "S020", 25)],
    }


def make_facts(**overrides: Any) -> RfpFacts:
    """기본 합성 사실. project·schedule·evaluation·contract_terms는 dict면 기본값에 덮어쓴다."""
    project = _merge(Project, _project(), overrides.pop("project", {}))
    schedule = _merge(Schedule, _schedule(), overrides.pop("schedule", {}))
    evaluation = _merge(Evaluation, _evaluation(), overrides.pop("evaluation", {}))
    contract_terms = _merge(ContractTerms, _contract_terms(), overrides.pop("contract_terms", {}))
    fields: dict[str, Any] = {
        "project": project,
        "schedule": schedule,
        "evaluation": evaluation,
        "contract_terms": contract_terms,
        "staffing": [
            StaffingReq(
                role="PM",
                grade="고급",
                count=1,
                resident=True,
                location="서울",
                min_years=10,
                evidence=make_evidence("PM 1명 상주", "S012", 31),
            )
        ],
        "commercial_sw": [
            CommercialSw(name="검색엔진", vendor=None, evidence=make_evidence("검색엔진 도입"))
        ],
        "submission_docs": [
            SubmissionDoc(name="제안서", due="2026-11-05", evidence=make_evidence("제안서 10부"))
        ],
    }
    fields.update(overrides)
    return RfpFacts.model_validate(fields)


def make_recommendation(**overrides: Any) -> Recommendation:
    fields: dict[str, Any] = {
        "decision": "CONDITIONAL_GO",
        "fit_score": 48,
        "summary": "합성 요약",
        "preconditions": ["확인: 중소기업 확인서 보유 (SME_CERT UNKNOWN)"],
        "why_not": [],
        "score_breakdown": dict(SCORE_BREAKDOWN),
        "basis": ["gate:SME_CERT#2"],
    }
    fields.update(overrides)
    return Recommendation.model_validate(fields)


def make_analysis(**overrides: Any) -> Analysis:
    """기본 합성 Analysis. 키워드 인자는 Analysis 필드를 그대로 교체한다."""
    fields: dict[str, Any] = {
        "slug": "synthetic",
        "model": "claude-opus-4-1",
        "served_model": "claude-opus-4-1-20250805",
        "strategy": "single",
        "effort": "high",
        "facts": make_facts(),
        "gates": [
            make_gate("G2B_REGISTERED", "PASS", rule_text="나라장터 등록", company_value="등록"),
            make_gate("INDUSTRY_CODE", "PASS", rule_text="업종 1468", company_value="1468"),
            make_gate(
                "SME_CERT",
                "UNKNOWN",
                rule_text="중소기업 확인서 보유",
                company_value="unknown",
                action="확인 필요: 중소기업현황정보시스템(sminfo) 중소기업확인서",
                unknown_fields=["registrations.sme_certificate.status"],
            ),
            make_gate(
                "ONSITE_LOCATION",
                "RISK",
                rule_text="상주 인원 3명(서울)",
                company_value="서울 상주 가능 인원 unknown",
                evidence=[],
                action="상주 가능 여부 확인",
            ),
        ],
        "scores": [make_score(unknown_inputs=["registrations.credit_rating.grade"])],
        "fits": [
            make_fit("SFR-001", "FULL", evidence_portfolio_ids=["P2026-01"]),
            make_fit("SFR-002", "PARTIAL", rationale="검색 일부 경험", gap_action="협력사 확보"),
        ],
        "risks": [
            make_risk("인력", "H", description="서울 상주 인력 부족", mitigation="채용"),
            make_risk("계약", "M", description="지체상금 조항"),
        ],
        "profitability": Profitability(budget_krw=430_000_000, est_mm=24.0, note="합성 메모"),
        "checklist": [ChecklistItem(item="제안서 작성", due="2026-11-05", source=None)],
        "data_to_confirm": [
            DataToConfirm(field="registrations.credit_rating.grade", why="신용평가 점수 산정")
        ],
        "recommendation": make_recommendation(),
        "citations": {"total": 7, "verified": 5, "repaired": 1, "unverified": 2},
        "usage": {
            "calls": 3,
            "input_tokens": 120_000,
            "output_tokens": 8_000,
            "cache_read_input_tokens": 90_000,
            "cache_creation_input_tokens": 30_000,
            "cost_usd": 1.23456,
        },
        "created_at": CREATED_AT,
        "knowledge": None,
    }
    fields.update(overrides)
    return Analysis.model_validate(fields)


# --- rfp.json·out 디렉터리 ---


def make_rfp(
    slug: str = "synthetic",
    title: str = "합성 공고",
    requirements: list[tuple[str, str]] | None = None,
    sections: list[Section] | None = None,
) -> RfpDocument:
    """최소 RfpDocument. requirements는 (id, name) 목록(기본 SFR-001 "통합 검색").
    `sections`를 주면 절 목록으로 쓴다(PF-04 절 경로)."""
    reqs = [("SFR-001", "통합 검색")] if requirements is None else requirements
    return RfpDocument(
        slug=slug,
        title=title,
        source_files=[f"{slug}.hwpx"],
        primary_format="hwpx",
        sections=[] if sections is None else sections,
        requirements=[
            Requirement(id=rid, category=rid[:3], name=name, details="", source="table")
            for rid, name in reqs
        ],
        tables=[],
        full_text="",
        source_quality=SourceQuality(
            primary_format="hwpx",
            primary_chars=0,
            primary_digits=0,
            has_tables=False,
            requirements_found=len(reqs),
            sections_mapped_to_pages=0,
        ),
    )


def make_section(sid: str, heading: str, level: int, parent_id: str | None = None) -> Section:
    """절 하나(본문 범위는 의미 없는 합성값). 전문은 `make_section("S000", "전문", 0)`."""
    return Section(
        id=sid,
        heading=heading,
        level=level,  # type: ignore[arg-type]
        kind="other",
        parent_id=parent_id,
        block_start=0,
        block_end=0,
        text=heading,
    )


def write_bundle(
    slug_dir: Path,
    slug: str,
    *,
    notice: NoticeMeta | None = None,
    primary_format: Format = "hwpx",
    title: str = "합성 공고",
) -> Path:
    """`bundle.json`을 쓴다(PF-04: 공고 메타·primary_format). 파일 목록은 합성 1건이다."""
    bundle = NoticeBundle(
        slug=slug,
        title=title,
        manifest_matched=True,
        files=[
            SourceFile(
                path=f"{slug}.{primary_format}",
                format=primary_format,
                role="primary",
                size_bytes=1,
                sha256="0" * 64,
            )
        ],
        primary_format=primary_format,
        status="ok",
        created_at=CREATED_AT,
        notice=notice,
    )
    slug_dir.mkdir(parents=True, exist_ok=True)
    path = slug_dir / "bundle.json"
    path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    return path


def write_slug(
    out_dir: Path,
    slug: str,
    *,
    analysis: Analysis | None = None,
    analysis_text: str | None = None,
    rfp: RfpDocument | None = None,
    rfp_text: str | None = None,
    decision: dict[str, Any] | None = None,
    decision_text: str | None = None,
    report_md: str | None = None,
) -> Path:
    """`out_dir/<slug>/`를 만들고 준 파일만 쓴다(`*_text`는 깨진 파일 등 원문 그대로).

    `analysis`의 slug는 디렉터리 이름으로 맞춘다. `decision`은 decision.yaml 매핑(M2-06 구조
    `{current, history}`)을 그대로 YAML로 쓴다.
    """
    slug_dir = out_dir / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    if analysis is not None:
        analysis_text = analysis.model_copy(update={"slug": slug}).model_dump_json(indent=2)
    if analysis_text is not None:
        (slug_dir / "analysis.json").write_text(analysis_text, encoding="utf-8")
    if rfp is not None:
        rfp_text = rfp.model_dump_json(indent=2)
    if rfp_text is not None:
        (slug_dir / "rfp.json").write_text(rfp_text, encoding="utf-8")
    if decision is not None:
        decision_text = yaml.safe_dump(decision, allow_unicode=True, sort_keys=False)
    if decision_text is not None:
        (slug_dir / "decision.yaml").write_text(decision_text, encoding="utf-8")
    if report_md is not None:
        (slug_dir / "report.md").write_text(report_md, encoding="utf-8")
    return slug_dir


def decision_doc(
    slug: str,
    decision: str = "NO_GO",
    *,
    reason: str = "합성 사유",
    decided_by: str = "jechoi",
    decided_at: str = "2026-10-22T14:03:05+09:00",
) -> dict[str, Any]:
    """M2-06 spec 형식의 유효한 decision.yaml 매핑(current와 같은 항목 1건짜리 history)."""
    current = {
        "slug": slug,
        "decision": decision,
        "reason": reason,
        "decided_by": decided_by,
        "decided_at": decided_at,
    }
    return {"current": current, "history": [dict(current)]}


# --- REV-05 독립 offline out(현재 5개 분석 + 3개 미완료 모사) ---
#
# `build_mixed_out(root)`는 실제 out/에 의존하지 않고 아래 8개 대상과 비대상 폴더를 만든다.
# 분석됨/이전 입력 기준 공고는 가짜 LLM 클라이언트(tests.fake_llm)로 실제 파이프라인을 돌려
# REV-02 stamp를 기록한다(네트워크·API 호출 없음). 회사 프로필은 `<root>/company/profile.yaml`.

MIXED_NOW = "2026-11-01T09:00:00+09:00"  # 고정 생성 시각(Asia/Seoul)
FAILED_RESPONSE_SENTINEL = "RAW-FAILED-RESPONSE-SENTINEL"  # _failed 원문 전문(노출 금지)
STALE_REPORT_SENTINEL = "OLD-STALE-REPORT"  # 손상 공고에 남아 있던 이전 보고서 본문
SECRET_SENTINEL = "sk-ant-api03-SECRETSENTINEL"

# slug → index 판단 칸의 기대 앞부분(--company 지정 시, PF-03). 분석 실패(f)는 요약이 뒤따른다.
MIXED_EXPECTED: dict[str, str] = {
    "a-current": "조건부 진행(확정)",
    "b-stale": "조건부 진행(확정)",
    "c-legacy": "조건부 진행(잠정)",
    "d-damaged-actions": "조건부 진행(잠정)",
    "e-retry-failed": "조건부 진행(잠정)",
    "f-failed-extract": "분석 실패 — ",
    "g-unanalyzed": "미분석",
    "h-corrupt": "보고서 생성 실패",
}
MIXED_NON_TARGETS = ("_hidden", "past", "notes-only", "Bad_Dir")
MALFORMED_REQUEST_FIELD = "registrations.credit_rating.grade"


BASE_CONFIRMED: dict[str, Any] = {
    "company.size": "중소기업",
    "registrations.sme_certificate.status": "valid",
    "registrations.sme_certificate.valid_until": "2027-12",
    "registrations.sme_certificate.classification": "중기업",
    "policy.min_contract_amount_krw": 0,
    "policy.target_gross_margin_pct": 20,
    "policy.seoul_resident_ok": True,
    "policy.max_concurrent_new_projects": 10,
    "policy.no_bid_if": [],
    "policy.preferred_domains": [],
}
PUBLIC_SOURCE = "https://www.example.com/business"  # 합성 공개 출처(http 링크 허용 검사용)


def make_company_view(
    *,
    overrides: dict[str, Any] | None = None,
    levels: dict[str, str] | None = None,
    sources: dict[str, list[dict[str, str]]] | None = None,
    extra_portfolio: Sequence[str] = (),
) -> Any:
    """합성 회사 뷰. `overrides`는 confirmed 값 덮어쓰기, `levels`는 경로별 확인 수준(public 등).

    실적 P2024-01(통합검색 고도화)이 있다. `levels`에 준 경로는 그 수준으로 출처 sidecar에 쓴다.
    """
    from bid_deep_engine.company.provenance import (
        CompanyEvidenceView,
        ProvenanceDocument,
        resolve_profile_path,
        value_hash,
    )
    from engine_tests.gate_factories import confirmed_view, make_profile, portfolio_item

    confirmed = {**BASE_CONFIRMED, **(overrides or {})}
    values = dict(confirmed)
    profile = make_profile(
        values,
        portfolio=[
            portfolio_item("P2024-01", title="통합검색 고도화"),
            *(portfolio_item(pid, title=f"합성 실적 {pid}") for pid in extra_portfolio),
        ],
    )
    view = confirmed_view(profile, [p for p in confirmed if p not in (levels or {})])
    fields = view.provenance.model_dump(mode="json")["fields"]
    for path, level in (levels or {}).items():
        default_source = (
            [{"kind": "website", "ref": PUBLIC_SOURCE}] if level in ("public", "confirmed") else []
        )
        fields[path] = {
            "level": level,
            "sources": (sources or {}).get(path, default_source),
            "value_hash": value_hash(resolve_profile_path(profile, path)),
            "checked_at": None,
            "note": None,
        }
    provenance = ProvenanceDocument.model_validate({"schema_version": 1, "fields": fields})
    return CompanyEvidenceView(profile, provenance)


def write_company_files(root: Path, company: Any, *, knowledge: bool = False) -> Path:
    """뷰를 프로필·실적·출처 YAML로 쓴다. `knowledge`면 합성 지식 트리를 `<root>/knowledge`로 복사.

    복사본의 `cap-one`에는 `(확인 필요)` 문장을 덧붙여 확인 수준이 섞인 페이지로 만든다.
    """
    import shutil

    profile = company.profile
    profile_path = root / "profile.yaml"
    root.mkdir(parents=True, exist_ok=True)
    data = profile.model_dump(mode="json")
    portfolio = data.pop("portfolio")
    data["provenance_file"] = "profile.provenance.yaml"
    profile_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (root / profile.portfolio_file).write_text(
        yaml.safe_dump(portfolio, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (root / "profile.provenance.yaml").write_text(
        yaml.safe_dump(company.provenance.model_dump(mode="json"), allow_unicode=True),
        encoding="utf-8",
    )
    if knowledge:
        kb = root / "knowledge"
        shutil.copytree(Path(__file__).parent / "fixtures" / "knowledge", kb)
        cap = kb / "capabilities" / "cap-one.md"
        cap.write_text(
            cap.read_text(encoding="utf-8") + "\n투입 규모는 YAML unknown (확인 필요).\n",
            encoding="utf-8",
        )
    return profile_path


def write_company_profile(root: Path) -> tuple[Path, Any]:
    """확인된(confirmed) 값으로 채운 합성 회사 프로필·실적·출처 sidecar. (프로필 경로, 뷰)."""
    company = make_company_view()
    return write_company_files(root, company), company


def write_pipeline_slug(
    out_dir: Path,
    slug: str,
    company: Any,
    *,
    facts: Any = None,
    match: Any = None,
    synth: Any = None,
    extra_text: str = "",
    knowledge_root: Path | None = None,
) -> Path:
    """가짜 LLM 클라이언트로 extract·match·synth를 실행해 현재 stamp가 있는 산출물을 만든다.

    `facts`·`match`·`synth`를 주면 그 응답을 쓴다(기본: tests.test_analyze_pipeline 응답).
    `extra_text`는 원문 full_text 끝에 붙여 인용이 검증되게 한다. `knowledge_root`면 KB-03 발췌.
    """
    from bid_deep_engine.company.knowledge import load_knowledge
    from engine_tests.fake_llm import FakeLlmClient
    from engine_tests.test_analyze_pipeline import (
        RUN_ID,
        facts_response,
        load_doc,
        match_response,
        notice,
        synth_response,
        write_location_cache,
        write_rfp,
    )

    slug_dir = out_dir / slug
    rfp_path = write_rfp(slug_dir, slug)
    document = load_doc(rfp_path)
    if extra_text:
        document.full_text += f"\n{extra_text}"
        rfp_path.write_text(document.model_dump_json(indent=2), encoding="utf-8")
    write_location_cache(slug_dir, document, source_path=document.source_files[0])
    client = FakeLlmClient(phase="analyze", run_id=RUN_ID)
    client.push("extract", facts if facts is not None else facts_response())
    client.push("match", match if match is not None else match_response())
    client.push("synth", synth if synth is not None else synth_response())
    kwargs: dict[str, Any] = {}
    if knowledge_root is not None:
        kwargs["knowledge"] = load_knowledge(knowledge_root, profile=company.profile)
    outcome = notice(
        rfp_path,
        slug_dir,
        client,
        company,
        passes=("extract", "match", "synth"),
        company_input_hash=company.company_input_hash,
        **kwargs,
    )
    assert outcome.status == "ok", outcome.reason
    return slug_dir


def write_unanalyzed_slug(out_dir: Path, slug: str, *, title: str = "미분석 합성 공고") -> Path:
    """ingest까지만 끝난 공고: bundle.json·rfp.json만 있다."""
    from engine_tests.test_analyze_pipeline import load_doc, write_location_cache, write_rfp

    slug_dir = out_dir / slug
    rfp_path = write_rfp(slug_dir, slug)
    document = load_doc(rfp_path)
    document.title = title
    rfp_path.write_text(document.model_dump_json(indent=2), encoding="utf-8")
    write_location_cache(slug_dir, document, source_path=document.source_files[0])
    (slug_dir / "raw.pdf.json").unlink()
    return slug_dir


def write_run_state(slug_dir: Path, *, phase: str, at: str, outcome: str, error: str | None):
    (slug_dir / "run_state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "last_attempt": {"phase": phase, "at": at, "outcome": outcome, "error": error},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def build_mixed_out(root: Path) -> tuple[Path, Path]:
    """8개 대상 + 비대상 폴더를 가진 offline out. (out 폴더, 회사 프로필 경로)."""
    company_path, company = write_company_profile(root / "company")
    out = root / "out"
    out.mkdir(parents=True)

    write_pipeline_slug(out, "a-current", company)

    stale = write_pipeline_slug(out, "b-stale", company)
    data = json.loads((stale / "analysis.json").read_text(encoding="utf-8"))
    data["recommendation"]["fit_score"] = 0  # 저장된 권고 출력이 stamp와 달라진다(stale)
    (stale / "analysis.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    write_slug(out, "c-legacy", analysis=make_analysis(), rfp=make_rfp("c-legacy"))

    damaged = json.loads(make_analysis().model_dump_json())
    damaged["raw_data_to_confirm"] = [{"field": MALFORMED_REQUEST_FIELD}]  # why 누락(손상)
    damaged["review_actions"] = {"schema_version": 2}
    damaged["slug"] = "d-damaged-actions"
    write_slug(
        out,
        "d-damaged-actions",
        analysis_text=json.dumps(damaged, ensure_ascii=False, indent=2),
        rfp=make_rfp("d-damaged-actions", title="손상 확인 목록 공고"),
        decision=decision_doc("d-damaged-actions", "CONDITIONAL_GO"),
    )

    retry = write_slug(
        out, "e-retry-failed", analysis=make_analysis(), rfp=make_rfp("e-retry-failed")
    )
    write_run_state(
        retry,
        phase="synth",
        at="2026-10-30T10:00:00+09:00",
        outcome="failed",
        error="LlmRefusal: model refused synth",
    )

    failed = write_unanalyzed_slug(out, "f-failed-extract", title="추출 실패 합성 공고")
    long_error = (
        "LlmOutputError: output does not match schema: slug=f-failed-extract purpose=extract; "
        f"validation, 3 validation errors, first: project — {SECRET_SENTINEL} "
        "/Users/someone/private/notice.hwp "
        + "x"
        * 400
        + "; saved _failed/extract-20261030T100000-extract-1.json\n"
        f"{FAILED_RESPONSE_SENTINEL} second line"
    )
    (failed / "usage.json").write_text(
        json.dumps({"run_id": "analyze-20261030T100000", "error": long_error, "calls": []}),
        encoding="utf-8",
    )
    (failed / "_failed").mkdir()
    (failed / "_failed" / "analyze-20261030T100000-extract-1.json").write_text(
        json.dumps({"response_text": FAILED_RESPONSE_SENTINEL * 10}), encoding="utf-8"
    )

    write_unanalyzed_slug(out, "g-unanalyzed")

    write_slug(
        out,
        "h-corrupt",
        analysis_text="{broken",
        report_md=f"{STALE_REPORT_SENTINEL}\n",
        decision=decision_doc("h-corrupt", "GO", decided_by="kim"),
    )
    (out / "h-corrupt" / "report.html").write_text(f"<p>{STALE_REPORT_SENTINEL}</p>\n")

    # 비대상: `_` 시작, 중간 컨테이너(past/), 직접 산출물 없는 폴더, slug 형식이 아닌 폴더
    write_slug(out, "_hidden", analysis=make_analysis())
    write_slug(out / "past", "past-p2025-01", analysis=make_analysis())
    (out / "notes-only").mkdir()
    (out / "notes-only" / "report.md").write_text("메모\n", encoding="utf-8")
    write_slug(out, "Bad_Dir", analysis=make_analysis())
    return out, company_path


# --- REV-05 STEP-002: 회사 비교 fixture(T2·T3) ---

SEOUL_QUOTE = "PM 1명은 서울 발주기관에 상주하여야 한다"
HIRING_TEXT = "서울 인력 채용"  # LLM 완화안(첫 영역 기본 대안으로 올리지 않음)
LEGACY_SUMMARY = "적합도가 낮아 입찰 포기를 권한다"
HIRE_CHECKLIST = "서울 상주 PM 신규 채용 공고 게시"  # LLM 실행 제안(리뷰 B1)
HIRE_RISK_TEXT = "서울 상주 인력 부족 — 서울 상주 PM 채용으로 해소 필요"  # 설명에 섞인 완화안
OWNER_REASON = "소봇 연계 가능성 검토 후 조건부 진행"


def build_company_out(root: Path) -> tuple[Path, Path]:
    """회사 비교 시나리오 out. (out 폴더, 회사 프로필 경로).

    - `seoul-current`: 확인된 서울 상주 불가 방침 + 서울 상주 요구(검증 인용)
      + 공동수급·하도급 불허.
      SME 만료일은 demo, 실적 P2024-01 title/client/period는 public, 총 기술인력 35명(confirmed).
      KB-03 발췌로 SFR-001이 [[cap-one]](확인 수준 혼재)·[[P2024-01]](confirmed)을 근거로 든다.
    - `stale-links`: 현재 분석 뒤 fits 서술을 고쳐 fits 단계가 stale(연결 후보는 상세로).
    - `legacy-nogo`: stamp 없는 레거시, fits 0개, 저장 권고 NO_GO 20점, 담당자 CONDITIONAL_GO 이력.
    """
    from bid_deep_engine.analysis.schemas import (
        ChecklistItem as _Checklist,
    )
    from bid_deep_engine.analysis.schemas import (
        Evidence as _Evidence,
    )
    from bid_deep_engine.analysis.schemas import (
        MatchOut,
        RequirementFitOut,
        SynthOut,
    )
    from bid_deep_engine.analysis.schemas import (
        Profitability as _Profitability,
    )
    from bid_deep_engine.analysis.schemas import (
        Risk as _Risk,
    )
    from engine_tests.gate_factories import make_facts as gate_facts
    from engine_tests.gate_factories import rule, staffing
    from engine_tests.test_analyze_pipeline import BUDGET, BUDGET_QUOTE

    company = make_company_view(
        overrides={"policy.seoul_resident_ok": False, "people.total_tech_staff": 35},
        levels={
            "portfolio[P2024-01].title": "public",
            "portfolio[P2024-01].client": "public",
            "portfolio[P2024-01].period": "public",
            "registrations.sme_certificate.valid_until": "demo",
        },
    )
    company_path = write_company_files(root / "company", company, knowledge=True)
    out = root / "out"
    out.mkdir(parents=True)

    seoul_facts = gate_facts(
        submission_deadline="2026-11-05 10:00",
        budget_krw=BUDGET,
        eligibility=[
            rule(
                "SME_CERT",
                "중소기업확인서 제출",
                evidence=_Evidence(quote=BUDGET_QUOTE, section_id="S001"),
            )
        ],
        staffing=[
            staffing(
                "PM",
                count=1,
                resident=True,
                location="서울 발주기관",
                evidence=_Evidence(quote=SEOUL_QUOTE),
            )
        ],
        consortium_allowed=False,
        subcontract_allowed=False,
    )
    match = MatchOut(
        fits=[
            RequirementFitOut(
                req_id="SFR-001",
                fit="FULL",
                rationale="검색 고도화 실적 [[cap-one]] [[P2024-01]]",
                evidence_portfolio_ids=["P2024-01"],
                evidence=_Evidence(quote="통합검색 기능 개선", section_id="S002"),
            ),
            RequirementFitOut(req_id="SFR-002", fit="PARTIAL", rationale="인증 경험 일부"),
            RequirementFitOut(req_id="SFR-003", fit="GAP", rationale="대시보드 실적 없음"),
        ]
    )
    synth = SynthOut(
        risks=[
            _Risk(
                category="인력",
                severity="H",
                description="서울 상주 인력 부족",
                evidence=_Evidence(quote=SEOUL_QUOTE),
                mitigation=HIRING_TEXT,
            ),
            _Risk(
                category="계약",
                severity="M",
                description="원문에 없는 위험 서술",
                evidence=_Evidence(quote="원문에 전혀 없는 위험 문장"),
            ),
        ],
        profitability=_Profitability(budget_krw=None, est_mm=10.0, note="합성 메모"),
        checklist=[_Checklist(item="제안 발표 준비", due=None)],
        data_to_confirm=[],
        summary="합성 종합 요약(검증 인용 없음)",
        preconditions=[],
        why_not=[],
    )
    write_pipeline_slug(
        out,
        "seoul-current",
        company,
        facts=seoul_facts,
        match=match,
        synth=synth,
        extra_text=SEOUL_QUOTE,
        knowledge_root=root / "company" / "knowledge",
    )

    # 리뷰 B1: 확인된 방침 충돌 + 현재 서술(synth current)의 채용 checklist·채용 완화 서술
    write_pipeline_slug(
        out,
        "hire-current",
        company,
        facts=gate_facts(
            submission_deadline="2026-11-05 10:00",
            staffing=[
                staffing(
                    "PM",
                    count=1,
                    resident=True,
                    location="서울 발주기관",
                    evidence=_Evidence(quote=SEOUL_QUOTE),
                )
            ],
        ),
        match=MatchOut(fits=[]),
        synth=SynthOut(
            risks=[
                _Risk(
                    category="인력",
                    severity="H",
                    description=HIRE_RISK_TEXT,
                    evidence=_Evidence(quote=SEOUL_QUOTE),
                    mitigation="채용",
                )
            ],
            profitability=_Profitability(budget_krw=None, est_mm=10.0, note="메모"),
            checklist=[_Checklist(item=HIRE_CHECKLIST, due=None)],
            data_to_confirm=[],
            summary="요약",
            preconditions=["서울 상주 인력 채용"],
            why_not=[],
        ),
        extra_text=SEOUL_QUOTE,
    )

    stale = write_pipeline_slug(out, "stale-links", company)
    data = json.loads((stale / "analysis.json").read_text(encoding="utf-8"))
    data["fits"][0]["rationale"] = "수정된 서술"  # fits 출력이 stamp와 달라진다
    (stale / "analysis.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    legacy = make_analysis(
        fits=[],
        recommendation=make_recommendation(
            decision="NO_GO", fit_score=20, summary=LEGACY_SUMMARY, basis=[]
        ),
    )
    history = [
        {
            "slug": "legacy-nogo",
            "decision": "NO_GO",
            "reason": "1차 검토",
            "decided_by": "jechoi",
            "decided_at": "2026-10-20T10:00:00+09:00",
        },
        {
            "slug": "legacy-nogo",
            "decision": "CONDITIONAL_GO",
            "reason": OWNER_REASON,
            "decided_by": "jechoi",
            "decided_at": "2026-10-23T15:00:00+09:00",
        },
    ]
    write_slug(
        out,
        "legacy-nogo",
        analysis=legacy,
        rfp=make_rfp(
            "legacy-nogo",
            title="레거시 공고",
            requirements=[("SFR-001", "통합 검색"), ("SFR-002", "권한 관리")],
        ),
        decision={"current": dict(history[-1]), "history": history},
    )
    return out, company_path


HEAVY_PORTFOLIO_IDS = tuple(f"P2025-{i + 1:02d}" for i in range(10))


def build_heavy_analysis(*, portfolio_ids: int = 10, fields_per_id: int = 7) -> Any:
    """남양주형 레거시: 실적 필드 확인 70건 + 그 밖 28건 = 98건, 서류 9건 + 서류 반복 checklist.

    실적 ID는 `HEAVY_PORTFOLIO_IDS`(회사 뷰는 `make_company_view(extra_portfolio=...)`로 맞춘다).
    """
    portfolio_fields = (
        "amount_krw",
        "role",
        "share_pct",
        "evidence",
        "client_type",
        "tech",
        "web_accessibility_cert",
        "egov_framework",
    )
    rows: list[DataToConfirm] = []
    for i in range(portfolio_ids):
        pid = HEAVY_PORTFOLIO_IDS[i]
        for name in portfolio_fields[:fields_per_id]:
            rows.append(DataToConfirm(field=f"portfolio[{pid}].{name}", why="실적 평가 증빙 필요"))
    extra = 98 - len(rows)
    for i in range(extra):
        rows.append(DataToConfirm(field=f"확인 쟁점 {i + 1}", why=f"실행 쟁점 사유 {i + 1}"))
    docs = [
        SubmissionDoc(
            name=f"제출서류 {i + 1}", due="2026-11-05", evidence=make_evidence(f"서류 {i}")
        )
        for i in range(9)
    ]
    checklist = [ChecklistItem(item=f"제출서류 {i + 1}", due="2026-11-05") for i in range(9)]
    checklist += [ChecklistItem(item="제안 발표 리허설", due=None)]
    return make_analysis(
        facts=make_facts(submission_docs=docs),
        data_to_confirm=rows,
        checklist=checklist,
    )
