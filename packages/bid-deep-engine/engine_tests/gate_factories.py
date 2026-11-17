"""게이트·점수 테스트용 합성 RfpFacts·CompanyProfile 빌더(spec M2-03 "테스트 케이스").

네트워크·API 키·실제 프로필 파일 없이 spec 시나리오를 한두 줄로 만든다. 기본 Evidence는 고정
quote·section_id다(`EVIDENCE`). 빌더는 입력을 따로 검증하지 않고 pydantic 모델에 넘긴다.

사용법:

    facts = make_facts(
        submission_deadline="2026-11-05 10:00",
        eligibility=[rule("SME_CERT", "중소기업확인서 제출"),
                     rule("INDUSTRY_CODE", "업종 1468", industry_code=["1468"])],
        staffing=[staffing("PM", count=1, resident=True, location="외교부 청사(서울)")],
        quantitative=[eval_item("신용평가", 10, "CREDIT_RATING", [("A0 이상", 10)])],
        consortium_allowed=False, subcontract_allowed=False,
    )
    profile = make_profile(
        {"company.size": "중소기업", "registrations.sme_certificate.status": "valid",
         "registrations.sme_certificate.valid_until": "2027-03",
         "people.headcount_by_grade.고급": 2},
        portfolio=[portfolio_item("P2024-03", amount_krw=300_000_000, completed=True,
                                  period_end="2025-06")],
        direct_production=[direct_production("8111189901", status="valid", valid_until="2027-01")],
        other_certs=[other_cert("ISMS")],
    )

`make_profile`의 첫 인자는 `{점 경로: 값}`이다(실적·직접생산·그 밖의 인증 항목은 전용 인자로).
GT-01 필드도 경로로 쓴다: `"registrations.insolvency": "none"`,
`"policy.default_bid_mode": "solo"`. 지정하지 않은 필드는 CompanyProfile 기본값, 곧 대부분
"unknown"(미확인)이다 — "unknown 입력" 시나리오는 아무것도 안 쓰면 되고, 확정 값 시나리오만
경로를 적는다. 예외로 `registrations.debarment`의 모델 기본은 `none_known`이다.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from bid_deep_engine.analysis.schemas import (
    Consortium,
    ConsortiumType,
    ContractTerms,
    Criterion,
    EligibilityRule,
    EvalItem,
    Evaluation,
    Evidence,
    Project,
    RfpFacts,
    RuleParams,
    Schedule,
    StaffingReq,
    Subcontract,
)
from bid_deep_engine.company.provenance import (
    CompanyEvidenceView,
    ProvenanceDocument,
    encode_path_token,
    resolve_profile_path,
    value_hash,
)
from bid_deep_engine.company.schema import LIST_ID_KEYS, UNKNOWN, CompanyProfile

EVIDENCE = Evidence(quote="합성 원문 인용", section_id="S001")
_FIXTURE_CONFIRMATIONS: dict[int, tuple[CompanyProfile, tuple[str, ...]]] = {}


def make_evidence(quote: str = "합성 원문 인용", section_id: str | None = "S001") -> Evidence:
    """고정 인용(기본) 또는 quote·section_id를 바꾼 인용. 중복 제거 시나리오에 쓴다."""
    return Evidence(quote=quote, section_id=section_id)


# --- RfpFacts 쪽 ---


def rule(
    code: str,
    text: str = "합성 참가자격",
    *,
    item_no: list[str] | None = None,
    industry_code: list[str] | None = None,
    region: list[str] | None = None,
    years: int | None = None,
    amount_krw: int | None = None,
    keyword: str | None = None,
    cert_name: str | None = None,
    evidence: Evidence | None = None,
) -> EligibilityRule:
    """EligibilityRule 하나. params는 키워드 인자로, 안 쓴 params는 None."""
    if code == "SME_CERT" and text == "합성 참가자격":
        text = "중소기업 확인서"
    return EligibilityRule(
        code=code,  # type: ignore[arg-type]
        text=text,
        params=RuleParams(
            item_no=item_no,
            industry_code=industry_code,
            region=region,
            years=years,
            amount_krw=amount_krw,
            keyword=keyword,
            cert_name=cert_name,
        ),
        evidence=evidence if evidence is not None else EVIDENCE,
    )


def staffing(
    role: str = "PM",
    *,
    grade: str | None = None,
    count: int | None = None,
    resident: bool | None = None,
    location: str | None = None,
    min_years: int | None = None,
    notes: str | None = None,
    evidence: Evidence | None = None,
) -> StaffingReq:
    """StaffingReq 하나."""
    return StaffingReq(
        role=role,
        grade=grade,  # type: ignore[arg-type]
        count=count,
        resident=resident,
        location=location,
        min_years=min_years,
        notes=notes,
        evidence=evidence if evidence is not None else EVIDENCE,
    )


def eval_item(
    item: str,
    max_points: float,
    kind: str,
    criteria: Iterable[tuple[str, float]] = (),
    *,
    evidence: Evidence | None = None,
) -> EvalItem:
    """정량평가 항목 하나. criteria는 `(condition, points)` 쌍의 나열."""
    return EvalItem(
        item=item,
        max_points=max_points,
        kind=kind,  # type: ignore[arg-type]
        criteria=[Criterion(condition=c, points=p) for c, p in criteria],
        evidence=evidence if evidence is not None else EVIDENCE,
    )


def make_facts(
    *,
    submission_deadline: str | None = None,
    notice_date: str | None = None,
    budget_krw: int | None = None,
    eligibility: Sequence[EligibilityRule] = (),
    staffing: Sequence[StaffingReq] = (),
    quantitative: Sequence[EvalItem] = (),
    consortium_allowed: bool | None = None,
    consortium_type: ConsortiumType | None = None,
    subcontract_allowed: bool | None = None,
    contract_evidence: Sequence[Evidence] = (),
) -> RfpFacts:
    """RfpFacts 하나. 안 쓴 필드는 RfpFacts 기본값(None·빈 리스트)."""
    return RfpFacts(
        project=Project(budget_krw=budget_krw),
        schedule=Schedule(submission_deadline=submission_deadline, notice_date=notice_date),
        eligibility=list(eligibility),
        evaluation=Evaluation(quantitative=list(quantitative)),
        staffing=list(staffing),
        contract_terms=ContractTerms(
            subcontract=Subcontract(allowed=subcontract_allowed),
            consortium=Consortium(allowed=consortium_allowed, type=consortium_type),
            evidence=list(contract_evidence),
        ),
    )


# --- CompanyProfile 쪽 ---


def direct_production(
    item_no: str,
    *,
    status: str = "unknown",
    valid_until: str = "unknown",
    name: str = "unknown",
) -> dict[str, Any]:
    """`registrations.direct_production` 항목(make_profile의 direct_production 인자용)."""
    return {"item_no": item_no, "name": name, "status": status, "valid_until": valid_until}


def other_cert(
    name: str,
    *,
    since: str = "unknown",
    valid_until: str = "unknown",
) -> dict[str, Any]:
    """`registrations.other_certs` 항목(make_profile의 other_certs 인자용, GT-01)."""
    return {"name": name, "since": since, "valid_until": valid_until}


def portfolio_item(
    id: str = "P2024-01",
    *,
    title: str = "합성 실적",
    client: str = "합성기관",
    domain: Sequence[str] = (),
    type: str = "unknown",
    period_start: str = "unknown",
    period_end: str = "unknown",
    amount_krw: int | str = "unknown",
    role: str = "unknown",
    share_pct: float | str = "unknown",
    completed: bool | str = "unknown",
) -> dict[str, Any]:
    """`portfolio` 항목(make_profile의 portfolio 인자용). 안 쓴 값은 "unknown"(미확인).

    `type`은 사업 유형(`ProjectType` 또는 "unknown", GT-02 실적 키워드 유형 대조용).
    """
    return {
        "id": id,
        "client": client,
        "title": title,
        "type": type,
        "domain": list(domain),
        "period": {"start": period_start, "end": period_end},
        "amount_krw": amount_krw,
        "role": role,
        "share_pct": share_pct,
        "completed": completed,
    }


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    """`a.b.c` 경로의 중간 dict를 만들며 값을 넣는다."""
    *parents, leaf = path.split(".")
    node = data
    for key in parents:
        node = node.setdefault(key, {})
    node[leaf] = value


def make_profile(
    values: Mapping[str, Any] | None = None,
    *,
    direct_production: Sequence[Mapping[str, Any]] | None = None,
    portfolio: Sequence[Mapping[str, Any]] | None = None,
    other_certs: Sequence[Mapping[str, Any]] | None = None,
) -> CompanyProfile:
    """CompanyProfile 하나. `values`는 `{점 경로: 값}`(예: `"company.size": "대기업"`).

    경로에 안 쓴 필드는 모델 기본값(unknown). 리스트 필드(`registrations.iso`, `.cloud_certs`
    등)도 경로로 통째 넘길 수 있다. 실적·직접생산·그 밖의 인증 항목은 전용 인자
    (`portfolio_item`·`direct_production`·`other_cert` 빌더 결과)로 준다. 모델 검증을 거치므로
    잘못된 값은 ValidationError다.
    """
    data: dict[str, Any] = {
        "schema_version": 1,
        "company": {"name": "테스트사"},
        "portfolio_file": "unused.portfolio.yaml",
    }
    for path, value in (values or {}).items():
        _set_path(data, path, value)
    if direct_production is not None:
        data.setdefault("registrations", {})["direct_production"] = [
            dict(d) for d in direct_production
        ]
    if other_certs is not None:
        data.setdefault("registrations", {})["other_certs"] = [dict(c) for c in other_certs]
    data["portfolio"] = [dict(p) for p in (portfolio or ())]
    profile = CompanyProfile.model_validate(data)
    roots = [_canonical_dotted_path(path) for path in (values or {})]
    if direct_production is not None:
        roots.append("registrations.direct_production")
    if other_certs is not None:
        roots.append("registrations.other_certs")
    if portfolio is not None:
        roots.append("portfolio")
    declared: list[str] = []
    for root in roots:
        _collect_confirmed_paths(profile, root, declared)
    _FIXTURE_CONFIRMATIONS[id(profile)] = (profile, tuple(dict.fromkeys(declared)))
    return profile


def _canonical_dotted_path(path: str) -> str:
    return ".".join(encode_path_token(token) for token in path.split("."))


def _collect_confirmed_paths(profile: CompanyProfile, path: str, output: list[str]) -> None:
    value = resolve_profile_path(profile, path)
    if value == UNKNOWN:
        return
    output.append(path)
    if isinstance(value, dict):
        for key in value:
            _collect_confirmed_paths(profile, f"{path}.{encode_path_token(str(key))}", output)
        return
    if not isinstance(value, list):
        return
    id_key = LIST_ID_KEYS.get(path)
    if id_key is None:
        return
    for item in value:
        identifier = item[id_key]
        item_path = f"{path}[{encode_path_token(str(identifier))}]"
        output.append(item_path)
        for key in item:
            _collect_confirmed_paths(profile, f"{item_path}.{encode_path_token(str(key))}", output)


def confirmed_view(profile: CompanyProfile, paths: Iterable[str]) -> CompanyEvidenceView:
    """합성 판정 fixture가 명시한 경로만 confirmed로 표시한 읽기 뷰."""
    fields = {}
    for path in dict.fromkeys(paths):
        value = resolve_profile_path(profile, path)
        if value == UNKNOWN:
            continue
        fields[path] = {
            "level": "confirmed",
            "sources": [{"kind": "user", "ref": "tests/gate_factories.py synthetic fixture"}],
            "value_hash": value_hash(value),
            "checked_at": None,
            "note": None,
        }
    provenance = ProvenanceDocument.model_validate({"schema_version": 1, "fields": fields})
    return CompanyEvidenceView(profile, provenance)


def confirmed_fixture_view(profile: CompanyProfile) -> CompanyEvidenceView:
    """`make_profile` 호출에서 명시된 값/목록만 confirmed인 합성 판정 fixture."""
    recorded = _FIXTURE_CONFIRMATIONS.get(id(profile))
    paths = recorded[1] if recorded is not None and recorded[0] is profile else ()
    return confirmed_view(profile, paths)
