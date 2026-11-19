"""회사 프로필 스키마 모델 단위 테스트(spec T1 모델 부분, T3·T4·T6 모델 수준, T5, T7 모델 수준).

오류 줄 문구(경로 변환)는 loader의 validate가 만들므로 여기서는 `ValidationError`의 loc만 본다.
"""

import copy

import pytest
from pydantic import ValidationError

from bid_deep_engine.company.schema import (
    DATE_RE,
    LIST_ID_KEYS,
    PORTFOLIO_ID_RE,
    UNKNOWN,
    CompanyProfile,
    PortfolioItem,
)


def minimal() -> dict:
    """필수 키만 있는 최소 프로필(spec 공통 타입 규칙의 필수 키)."""
    return {"schema_version": 1, "company": {"name": "㈜루트랩"}, "portfolio_file": "p.yaml"}


def with_value(path: str, value) -> dict:
    """최소 프로필에 점 경로 값 하나를 넣은 dict. 중간 매핑은 만든다."""
    data = copy.deepcopy(minimal())
    *parents, last = path.split(".")
    node = data
    for key in parents:
        node = node.setdefault(key, {})
    node[last] = value
    return data


def item(**kw) -> dict:
    return {"id": "P2026-01", "client": "외교부", "title": "홈페이지 유지관리", **kw}


def locs(exc: pytest.ExceptionInfo[ValidationError]) -> list[tuple]:
    return [tuple(e["loc"]) for e in exc.value.errors()]


def assert_error_at(data: dict, prefix: tuple, model=CompanyProfile) -> None:
    with pytest.raises(ValidationError) as exc:
        model.model_validate(data)
    found = locs(exc)
    assert any(loc[: len(prefix)] == prefix for loc in found), found


# --- T1(모델 부분): 필수 키만 있는 프로필의 기본값 ---


def test_minimal_profile_defaults():
    p = CompanyProfile.model_validate(minimal())
    assert p.company.name == "㈜루트랩"
    assert p.company.size == UNKNOWN == "unknown"
    assert p.company.name_en == "unknown"
    assert p.company.founded == "unknown"
    assert p.company.revenue_krw == {}
    assert p.company.branches == []
    assert p.registrations.debarment == "none_known"
    assert p.registrations.tax_delinquency == "unknown"
    assert p.registrations.insolvency == "unknown"
    assert p.registrations.other_certs == []
    assert p.registrations.direct_production == []
    assert p.registrations.venture is None
    assert p.registrations.tech_rating is None
    assert p.registrations.g2b.registered == "unknown"
    assert p.registrations.g2b.industry_codes == "unknown"
    assert p.registrations.sme_certificate.status == "unknown"
    assert p.registrations.sme_certificate.valid_until == "unknown"
    assert p.registrations.gs_cert == "unknown"
    assert p.registrations.web_accessibility_certs.count == "unknown"
    assert p.registrations.web_accessibility_certs.sites == []
    assert p.registrations.credit_rating.grade == "unknown"
    assert p.people.certifications == "unknown"
    assert p.people.key_staff == []
    assert p.people.roles.pm_capable == "unknown"
    assert p.people.trainings.sw_test_expert == "unknown"
    assert p.capabilities.tech_stack.backend == "unknown"
    assert p.capabilities.solutions == []
    assert p.policy.min_contract_amount_krw == "unknown"
    assert p.policy.target_gross_margin_pct == "unknown"
    assert p.policy.seoul_resident_ok == "unknown"
    assert p.policy.max_concurrent_new_projects == "unknown"
    assert p.policy.default_bid_mode == "unknown"
    assert p.policy.no_bid_if == []
    assert p.policy.preferred_domains == []
    assert p.portfolio == []


def test_minimal_profile_fills_grade_and_onsite_keys():
    p = CompanyProfile.model_validate(minimal())
    assert p.people.headcount_by_grade == {g: "unknown" for g in ("특급", "고급", "중급", "초급")}
    assert list(p.people.onsite_capacity) == ["대구", "경북", "부산", "서울", "기타"]
    assert p.people.onsite_capacity["부산"].ok == "unknown"
    assert p.people.onsite_capacity["부산"].max_people == "unknown"
    # 기타 슬롯에는 max_people 필드가 없다.
    assert not hasattr(p.people.onsite_capacity["기타"], "max_people")


def test_partial_onsite_keeps_given_and_fills_missing():
    data = with_value(
        "people.onsite_capacity", {"대구": {"ok": True, "max_people": 5}, "기타": {"ok": True}}
    )
    p = CompanyProfile.model_validate(data)
    assert p.people.onsite_capacity["대구"].ok is True
    assert p.people.onsite_capacity["대구"].max_people == 5
    assert p.people.onsite_capacity["서울"].ok == "unknown"
    assert p.people.onsite_capacity["기타"].ok is True


def test_minimal_portfolio_item_defaults():
    it = PortfolioItem.model_validate(item())
    assert it.amount_krw == "unknown"
    assert it.client_type == "unknown"
    assert it.type == "unknown"
    assert it.role == "unknown"
    assert it.tech == "unknown"
    assert it.domain == []
    assert it.period.start == "unknown"
    assert it.period.end == "unknown"
    assert it.share_pct == "unknown"
    assert it.completed == "unknown"
    assert it.evidence == "unknown"
    assert it.web_accessibility_cert == "unknown"
    assert it.egov_framework == "unknown"


@pytest.mark.parametrize("drop", ["schema_version", "company", "portfolio_file"])
def test_required_top_level_keys(drop):
    data = minimal()
    del data[drop]
    assert_error_at(data, (drop,))


def test_company_name_required():
    data = minimal()
    data["company"] = {}
    assert_error_at(data, ("company", "name"))


@pytest.mark.parametrize("drop", ["id", "client", "title"])
def test_portfolio_item_required_keys(drop):
    data = item()
    del data[drop]
    assert_error_at(data, (drop,), model=PortfolioItem)


def test_profile_accepts_portfolio_items():
    data = minimal()
    data["portfolio"] = [item()]
    p = CompanyProfile.model_validate(data)
    assert p.portfolio[0].id == "P2026-01"


# --- T3(모델 수준): enum 거부 ---


@pytest.mark.parametrize(
    ("path", "value", "loc"),
    [
        ("company.size", "스타트업", ("company", "size")),
        ("registrations.sme_certificate.status", "pending", None),
        ("registrations.debarment", "unknown", None),
        ("registrations.tax_delinquency", "yes", None),
        ("registrations.insolvency", "no", None),
        ("policy.default_bid_mode", "alone", None),
        (
            "people.onsite_capacity",
            {"제주": {"ok": True}},
            ("people", "onsite_capacity", "제주"),
        ),
        ("people.headcount_by_grade", {"수석": 1}, ("people", "headcount_by_grade", "수석")),
    ],
)
def test_profile_enum_rejected(path, value, loc):
    assert_error_at(with_value(path, value), loc or tuple(path.split(".")))


@pytest.mark.parametrize(
    ("field", "value"), [("client_type", "기업"), ("type", "유지보수"), ("role", "협력사")]
)
def test_portfolio_enum_rejected(field, value):
    assert_error_at(item(**{field: value}), (field,), model=PortfolioItem)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("company.size", "중견기업"),
        ("registrations.sme_certificate.status", "expired"),
        ("registrations.debarment", "active"),
        ("registrations.tax_delinquency", "exists"),
        ("registrations.insolvency", "none"),
        ("registrations.insolvency", "active"),
        ("registrations.insolvency", "unknown"),
        ("policy.default_bid_mode", "solo"),
        ("policy.default_bid_mode", "consortium"),
        ("policy.default_bid_mode", "unknown"),
        ("people.headcount_by_grade", {"특급": 1, "초급": 3}),
    ],
)
def test_profile_enum_accepted(path, value):
    CompanyProfile.model_validate(with_value(path, value))


def test_key_staff_grade_enum():
    ok = with_value("people.key_staff", [{"alias": "PM1", "grade": "고급"}])
    assert CompanyProfile.model_validate(ok).people.key_staff[0].grade == "고급"
    bad = with_value("people.key_staff", [{"alias": "PM1", "grade": "수석"}])
    assert_error_at(bad, ("people", "key_staff", 0, "grade"))


# --- T4(모델 수준): unknown·null 처리 ---


@pytest.mark.parametrize(
    "path",
    [
        "company.founded",
        "company.size",
        "company.employees",
        "company.capital_krw",
        "registrations.g2b.registered",
        "registrations.g2b.industry_codes",
        "registrations.sw_business_report.latest_year",
        "registrations.gs_cert",
        "registrations.insolvency",
        "policy.default_bid_mode",
        "registrations.egov_framework_inspection_reports",
        "registrations.wage_arrears_listed",
        "registrations.patents",
        "people.total_tech_staff",
        "people.certifications",
        "capabilities.cms_experience",
        "capabilities.egov_framework_experience",
        "policy.target_gross_margin_pct",
    ],
)
def test_unknown_accepted(path):
    p = CompanyProfile.model_validate(with_value(path, "unknown"))
    node = p
    for key in path.split("."):
        node = getattr(node, key)
    assert node == "unknown"


@pytest.mark.parametrize(
    "path",
    [
        "registrations.g2b.registered",
        "company.employees",
        "registrations.patents",
        "policy.seoul_resident_ok",
        "policy.max_concurrent_new_projects",
    ],
)
def test_unknown_typo_rejected(path):
    assert_error_at(with_value(path, "unkown"), tuple(path.split(".")))


@pytest.mark.parametrize(
    "path",
    [
        "company.size",
        "registrations.g2b.other_codes",
        "registrations.sme_certificate.valid_until",
        "registrations.debarment",
        "people.certifications",
        "people.onsite_capacity",
    ],
)
def test_null_rejected_where_not_optional(path):
    assert_error_at(with_value(path, None), tuple(path.split(".")))


def test_null_venture_and_empty_codes_allowed():
    data = with_value("registrations.venture", None)
    data["registrations"]["g2b"] = {"industry_codes": []}
    p = CompanyProfile.model_validate(data)
    assert p.registrations.venture is None
    assert p.registrations.g2b.industry_codes == []


def test_solution_desc_defaults_to_none():
    data = with_value(
        "capabilities.solutions", [{"name": "소봇"}, {"name": "DPP One", "desc": "x"}]
    )
    p = CompanyProfile.model_validate(data)
    assert p.capabilities.solutions[0].desc is None
    assert p.capabilities.solutions[1].desc == "x"


def test_other_certs_item_defaults_and_id_key():
    data = with_value("registrations.other_certs", [{"name": "ISMS"}])
    cert = CompanyProfile.model_validate(data).registrations.other_certs[0]
    assert cert.name == "ISMS"
    assert cert.since == "unknown"
    assert cert.valid_until == "unknown"
    assert LIST_ID_KEYS["registrations.other_certs"] == "name"


def test_other_certs_name_required():
    data = with_value("registrations.other_certs", [{"since": "2024-01"}])
    assert_error_at(data, ("registrations", "other_certs", 0, "name"))


def test_other_certs_extra_key_forbidden():
    data = with_value("registrations.other_certs", [{"name": "ISMS", "status": "valid"}])
    assert_error_at(data, ("registrations", "other_certs", 0, "status"))


@pytest.mark.parametrize("field", ["since", "valid_until"])
def test_other_certs_date_pattern(field):
    ok = with_value("registrations.other_certs", [{"name": "ISMS", field: "2026-10"}])
    assert (
        getattr(CompanyProfile.model_validate(ok).registrations.other_certs[0], field) == "2026-10"
    )
    bad = with_value("registrations.other_certs", [{"name": "ISMS", field: "2026/10"}])
    assert_error_at(bad, ("registrations", "other_certs", 0, field))


def test_venture_object_defaults():
    p = CompanyProfile.model_validate(with_value("registrations.venture", {"since": "2023-05"}))
    assert p.registrations.venture.since == "2023-05"
    assert p.registrations.venture.valid_until == "unknown"
    assert p.registrations.venture.type == "unknown"


def test_extra_keys_forbidden():
    assert_error_at(with_value("company.nmae", "x"), ("company", "nmae"))
    assert_error_at(with_value("registrations.g2b.registerd", True), ("registrations", "g2b"))
    data = minimal()
    data["registraions"] = {}
    assert_error_at(data, ("registraions",))
    assert_error_at(item(amount=1), ("amount",), model=PortfolioItem)


def test_schema_version_must_be_1():
    data = minimal()
    data["schema_version"] = 2
    assert_error_at(data, ("schema_version",))


def test_onsite_other_has_no_max_people():
    data = with_value("people.onsite_capacity", {"기타": {"ok": True, "max_people": 3}})
    assert_error_at(data, ("people", "onsite_capacity", "기타", "max_people"))


# --- T5: 날짜 ---


@pytest.mark.parametrize("value", ["2023-05", "2023-05-01", "2024-12-31"])
def test_date_accepted(value):
    p = CompanyProfile.model_validate(with_value("company.founded", value))
    assert p.company.founded == value
    it = PortfolioItem.model_validate(item(period={"start": value, "end": "unknown"}))
    assert it.period.start == value


@pytest.mark.parametrize("value", ["2023/05", "2023-13", "23-05", "2023-05-32", "2023"])
def test_date_rejected(value):
    assert_error_at(with_value("company.founded", value), ("company", "founded"))
    assert_error_at(item(period={"start": value}), ("period", "start"), model=PortfolioItem)


def test_date_regex_constant():
    assert DATE_RE.pattern == r"^\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?$"
    assert PORTFOLIO_ID_RE.pattern == r"^P\d{4}-\d{2}$"


# --- T6(모델 수준): 금액·번호 ---


@pytest.mark.parametrize("value", [-1, 1.5, "1억", "100", True, None])
def test_amount_rejected(value):
    assert_error_at(item(amount_krw=value), ("amount_krw",), model=PortfolioItem)


def test_capital_accepted():
    p = CompanyProfile.model_validate(with_value("company.capital_krw", 100000000))
    assert p.company.capital_krw == 100000000


@pytest.mark.parametrize("value", [120, -1, "50"])
def test_share_pct_rejected(value):
    assert_error_at(item(share_pct=value), ("share_pct",), model=PortfolioItem)


def test_share_pct_accepts_int_and_float():
    assert PortfolioItem.model_validate(item(share_pct=100)).share_pct == 100
    assert PortfolioItem.model_validate(item(share_pct=33.3)).share_pct == 33.3


def test_target_margin_range():
    assert_error_at(
        with_value("policy.target_gross_margin_pct", 101), ("policy", "target_gross_margin_pct")
    )
    p = CompanyProfile.model_validate(with_value("policy.target_gross_margin_pct", 12.5))
    assert p.policy.target_gross_margin_pct == 12.5


def test_unquoted_item_no_rejected():
    data = with_value("registrations.direct_production", [{"item_no": 8111189901, "name": "x"}])
    assert_error_at(data, ("registrations", "direct_production", 0, "item_no"))


def test_unquoted_biz_no_and_iso_std_rejected():
    assert_error_at(with_value("company.biz_no", 5498603068), ("company", "biz_no"))
    assert_error_at(
        with_value("registrations.iso", [{"std": 9001}]), ("registrations", "iso", 0, "std")
    )
    assert_error_at(
        with_value("registrations.g2b.industry_codes", [1468]),
        ("registrations", "g2b", "industry_codes"),
    )


def test_negative_counts_rejected():
    assert_error_at(with_value("company.employees", -3), ("company", "employees"))
    assert_error_at(with_value("people.certifications", {"PMP": -1}), ("people", "certifications"))
    assert_error_at(with_value("company.revenue_krw", {2025: -5}), ("company", "revenue_krw", 2025))


def test_revenue_by_year():
    p = CompanyProfile.model_validate(
        with_value("company.revenue_krw", {2023: "unknown", 2024: 1000})
    )
    assert p.company.revenue_krw == {2023: "unknown", 2024: 1000}


def test_direct_production_item_no_required():
    data = with_value("registrations.direct_production", [{"name": "정보시스템개발서비스"}])
    assert_error_at(data, ("registrations", "direct_production", 0, "item_no"))


# --- T7(모델 수준): ID 형식은 모델이 검사하지 않음(X64) ---


@pytest.mark.parametrize("bad_id", ["P2026-1", "2026-01", "P26-01"])
def test_portfolio_id_has_no_pattern(bad_id):
    assert PortfolioItem(id=bad_id, client="c", title="t").id == bad_id


def test_portfolio_id_must_be_string():
    assert_error_at(item(id=202601), ("id",), model=PortfolioItem)
