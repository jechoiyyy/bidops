"""회사 프로필 로더·validate 단위 테스트(spec T1, T3·T4·T6 오류 줄, T5 YAML 날짜, T7, T8, T11).

픽스처는 테스트 안에서 임시 파일로 만든다(템플릿 픽스처는 STEP-004). 네트워크를 쓰지 않는다.
"""

import copy
from pathlib import Path

import pytest
import yaml

from bid_deep_engine.company.loader import (
    ProfileError,
    ValidationReport,
    load_profile,
    validate,
)

ID_EXPECT = r"(expected ^P\d{4}-\d{2}$)"

FULL_ONSITE = {
    "대구": {"ok": True, "max_people": "unknown"},
    "경북": {"ok": True, "max_people": "unknown"},
    "부산": {"ok": "unknown", "max_people": "unknown"},
    "서울": {"ok": "unknown", "max_people": "unknown"},
    "기타": {"ok": "unknown"},
}


def base_profile() -> dict:
    """필수 키 + 다섯 지역이 모두 있는 onsite_capacity(경고 0개)."""
    return {
        "schema_version": 1,
        "company": {"name": "㈜루트랩"},
        "people": {"onsite_capacity": copy.deepcopy(FULL_ONSITE)},
        "portfolio_file": "p.portfolio.yaml",
    }


def item(id_="P2026-01", **kw) -> dict:
    return {"id": id_, "client": "외교부", "title": "홈페이지 유지관리", **kw}


def dump(data) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def write(tmp_path: Path, profile, portfolio=None, *, name: str = "profile.yaml") -> Path:
    """프로필(dict·YAML 문자열)과 실적(list·YAML 문자열)을 쓴다. portfolio=None이면 실적 없음."""
    path = tmp_path / name
    path.write_text(profile if isinstance(profile, str) else dump(profile), encoding="utf-8")
    if portfolio is not None:
        pf = tmp_path / "p.portfolio.yaml"
        pf.write_text(
            portfolio if isinstance(portfolio, str) else dump(portfolio), encoding="utf-8"
        )
    return path


def lines_at(errors: list[str], path: str) -> list[str]:
    return [e for e in errors if e.startswith(path + ":")]


def assert_invalid_both_ways(path: Path) -> ValidationReport:
    report = validate(path)
    assert report.errors
    with pytest.raises(ProfileError) as exc:
        load_profile(path)
    assert exc.value.errors == report.errors
    return report


# --- T1: 필수 키만 있는 최소 프로필 + 실적 1건 ---


def test_minimal_profile_loads(tmp_path):
    profile = {
        "schema_version": 1,
        "company": {"name": "㈜루트랩"},
        "portfolio_file": "p.portfolio.yaml",
    }
    path = write(tmp_path, profile, [item()])
    p = load_profile(path)
    assert p.company.size == "unknown"
    assert p.registrations.debarment == "none_known"
    assert p.registrations.direct_production == []
    assert p.registrations.venture is None
    assert len(p.portfolio) == 1
    assert p.portfolio[0].amount_krw == "unknown"
    assert p.people.onsite_capacity["서울"].ok == "unknown"
    report = validate(str(path))
    assert report.errors == []
    # onsite_capacity 키가 없으면 다섯 지역 모두 빠진 것으로 본다.
    assert report.warnings == [
        f"people.onsite_capacity.{k}: missing, treated as unknown"
        for k in ("대구", "경북", "부산", "서울", "기타")
    ]


def test_load_profile_accepts_str_and_path(tmp_path):
    path = write(tmp_path, base_profile(), [item()])
    assert load_profile(str(path)).portfolio[0].id == "P2026-01"
    assert load_profile(path).company.name == "㈜루트랩"
    assert validate(path) == ValidationReport(errors=[], warnings=[])


def test_empty_portfolio_list_is_valid(tmp_path):
    path = write(tmp_path, base_profile(), "# 머리 주석\n[]\n")
    assert load_profile(path).portfolio == []
    assert validate(path).errors == []


def test_portfolio_file_relative_to_profile_folder(tmp_path):
    sub = tmp_path / "company"
    sub.mkdir()
    (sub / "x.portfolio.yaml").write_text(dump([item()]), encoding="utf-8")
    profile = base_profile() | {"portfolio_file": "x.portfolio.yaml"}
    (sub / "x.yaml").write_text(dump(profile), encoding="utf-8")
    assert len(load_profile(sub / "x.yaml").portfolio) == 1


# --- T3: enum 거부 — 잘못된 값마다 오류 줄 정확히 1개 ---


def test_enum_errors_one_line_each(tmp_path):
    profile = base_profile()
    profile["company"]["size"] = "스타트업"
    profile["registrations"] = {
        "sme_certificate": {"status": "pending"},
        "debarment": "unknown",
        "tax_delinquency": "yes",
    }
    profile["people"]["onsite_capacity"]["제주"] = {"ok": True}
    profile["people"]["headcount_by_grade"] = {"수석": 1}
    portfolio = [item(client_type="기업", type="유지보수", role="협력사")]
    report = assert_invalid_both_ways(write(tmp_path, profile, portfolio))

    paths = [
        "company.size",
        "registrations.sme_certificate.status",
        "registrations.debarment",
        "registrations.tax_delinquency",
        "people.onsite_capacity.제주",
        "people.headcount_by_grade.수석",
        "portfolio[P2026-01].client_type",
        "portfolio[P2026-01].type",
        "portfolio[P2026-01].role",
    ]
    for p in paths:
        assert len(lines_at(report.errors, p)) == 1, (p, report.errors)
    assert len(report.errors) == 9, report.errors
    # union(enum | "unknown") 필드는 분기 오류를 한 줄로 합치고 허용 목록을 붙인다.
    for p in ["company.size", "portfolio[P2026-01].client_type", "portfolio[P2026-01].role"]:
        (line,) = lines_at(report.errors, p)
        assert "; 허용: " in line and "'unknown'" in line, line
    (size_line,) = lines_at(report.errors, "company.size")
    assert "'중소기업'" in size_line
    assert report.warnings == []


# --- T4: unknown·null 처리의 validate 오류 줄 ---


def test_unknown_and_null_error_lines(tmp_path):
    profile = base_profile()
    profile["company"]["employees"] = "unkown"
    profile["company"]["size"] = None
    profile["registrations"] = {
        "g2b": {"registered": "unknown", "industry_codes": [], "other_codes": None},
        "sme_certificate": {"valid_until": None},
        "venture": None,
        "wage_arrears_listed": "unkown",
    }
    profile["capabilities"] = {"solutions": [{"name": "소봇"}]}
    report = assert_invalid_both_ways(write(tmp_path, profile, [item()]))

    expected = [
        "company.employees",
        "company.size",
        "registrations.g2b.other_codes",
        "registrations.sme_certificate.valid_until",
        "registrations.wage_arrears_listed",
    ]
    for p in expected:
        (line,) = lines_at(report.errors, p)
        assert "; 허용: " in line, line
    assert len(report.errors) == len(expected), report.errors
    (emp,) = lines_at(report.errors, "company.employees")
    assert emp == "company.employees: Input should be a valid integer; 허용: int, 'unknown'"
    (other,) = lines_at(report.errors, "registrations.g2b.other_codes")
    assert other.endswith("허용: list[str], 'unknown'")


def test_unknown_null_valid_values_load(tmp_path):
    profile = base_profile()
    profile["registrations"] = {"g2b": {"industry_codes": []}, "venture": None}
    profile["capabilities"] = {"solutions": [{"name": "소봇"}]}
    p = load_profile(write(tmp_path, profile, [item()]))
    assert p.registrations.g2b.industry_codes == []
    assert p.registrations.venture is None
    assert p.capabilities.solutions[0].desc is None


# --- T5: YAML 날짜 변환 ---


def test_unquoted_yaml_dates_become_strings(tmp_path):
    text = dump(base_profile()) + "\n"
    text = text.replace(
        "company:\n  name: ㈜루트랩\n",
        "company:\n  name: ㈜루트랩\n  founded: 2023-05\n  incorporated: 2023-05-01\n",
    )
    portfolio = (
        "- id: P2026-01\n  client: c\n  title: t\n  period: {start: 2026-01-02, end: 2026-12}\n"
    )
    path = write(tmp_path, text, portfolio)
    p = load_profile(path)
    assert p.company.founded == "2023-05"
    assert p.company.incorporated == "2023-05-01"
    assert p.portfolio[0].period.start == "2026-01-02"
    assert validate(path).errors == []


@pytest.mark.parametrize("value", ["2023/05", "2023-13", "23-05"])
def test_bad_dates_are_errors(tmp_path, value):
    profile = base_profile()
    profile["company"]["founded"] = value
    report = assert_invalid_both_ways(write(tmp_path, profile, [item()]))
    (line,) = report.errors
    assert line.startswith("company.founded: String should match pattern")
    assert "허용: YYYY-MM|YYYY-MM-DD, 'unknown'" in line


# --- T6: 금액·번호 ---


def test_amount_and_number_error_lines(tmp_path):
    profile = base_profile()
    profile["company"]["capital_krw"] = 100000000  # 유효
    profile["registrations"] = {
        "direct_production": [{"item_no": 8111189901, "name": "정보시스템유지관리서비스"}]
    }
    portfolio = [
        item("P2026-01", amount_krw=-1),
        item("P2026-02", amount_krw=1.5),
        item("P2026-03", amount_krw="1억"),
        item("P2026-04", share_pct=120),
    ]
    report = assert_invalid_both_ways(write(tmp_path, profile, portfolio))
    expected = [
        "portfolio[P2026-01].amount_krw",
        "portfolio[P2026-02].amount_krw",
        "portfolio[P2026-03].amount_krw",
        "portfolio[P2026-04].share_pct",
        "registrations.direct_production[#0].item_no",
    ]
    for p in expected:
        assert len(lines_at(report.errors, p)) == 1, (p, report.errors)
    assert len(report.errors) == len(expected), report.errors
    for p in expected[:4]:
        (line,) = lines_at(report.errors, p)
        assert "; 허용: " in line, line
    assert lines_at(report.errors, "portfolio[P2026-01].amount_krw") == [
        "portfolio[P2026-01].amount_krw: Input should be greater than or equal to 0; "
        "허용: int, 'unknown'"
    ]
    assert not any(e.startswith("company.capital_krw") for e in report.errors)


# --- T7: 실적 ID 형식·중복·연도 경고 ---


def test_bad_id_format_exactly_one_line_each(tmp_path):
    portfolio = [item("P2026-1"), item("2026-01"), item("P26-01")]
    report = assert_invalid_both_ways(write(tmp_path, base_profile(), portfolio))
    for i, bad in enumerate(["P2026-1", "2026-01", "P26-01"]):
        assert lines_at(report.errors, f"portfolio[#{i}].id") == [
            f"portfolio[#{i}].id: invalid id '{bad}' {ID_EXPECT}"
        ]
    assert len(report.errors) == 3


def test_bad_id_uses_index_for_other_field_errors(tmp_path):
    portfolio = [item("P2026-1", amount_krw=-1)]
    report = validate(write(tmp_path, base_profile(), portfolio))
    assert len(lines_at(report.errors, "portfolio[#0].amount_krw")) == 1
    assert len(lines_at(report.errors, "portfolio[#0].id")) == 1
    assert len(report.errors) == 2


def test_missing_id_and_item_no(tmp_path):
    profile = base_profile()
    profile["registrations"] = {
        "direct_production": [
            {"item_no": "8111189901", "name": "a"},
            {"name": "item_no 없음"},
        ]
    }
    no_id = {"client": "c", "title": "t"}
    portfolio = [item("P2026-01"), no_id]
    report = assert_invalid_both_ways(write(tmp_path, profile, portfolio))
    assert report.errors == [
        "registrations.direct_production[#1].item_no: Field required",
        "portfolio[#1].id: Field required",
    ]


def test_non_string_id_is_schema_error_only(tmp_path):
    report = validate(write(tmp_path, base_profile(), [item(202601)]))
    assert report.errors == ["portfolio[#0].id: Input should be a valid string"]


def test_duplicate_ids(tmp_path):
    portfolio = [item("P2025-03"), item("P2025-03"), item("P2025-04"), item("P2025-03")]
    report = assert_invalid_both_ways(write(tmp_path, base_profile(), portfolio))
    # 두 번째 이후 항목마다 한 줄.
    assert report.errors == ["portfolio[P2025-03].id: duplicate id"] * 2


def test_year_mismatch_is_warning_only(tmp_path):
    portfolio = [
        item("P2025-01", period={"start": "2026-01"}),
        item("P2025-02", period={"start": "unknown"}),
        item("P2025-03", period={"start": "2025-03"}),
        item("P2025-04"),
    ]
    path = write(tmp_path, base_profile(), portfolio)
    report = validate(path)
    assert report.errors == []
    assert report.warnings == ["portfolio[P2025-01].id: id year 2025 != period.start year 2026"]
    assert len(load_profile(path).portfolio) == 4


def test_warnings_computed_despite_schema_errors(tmp_path):
    """X65: 스키마 오류(같은 항목의 다른 필드 포함)가 있어도 원본에서 경고를 계산한다."""
    profile = base_profile()
    profile["company"]["size"] = "스타트업"
    del profile["people"]["onsite_capacity"]["부산"]
    portfolio = [item("P2025-01", period={"start": "2026-01"}, amount_krw="1억")]
    report = validate(write(tmp_path, profile, portfolio))
    assert len(report.errors) == 2
    assert report.warnings == [
        "people.onsite_capacity.부산: missing, treated as unknown",
        "portfolio[P2025-01].id: id year 2025 != period.start year 2026",
    ]


def test_year_warning_skipped_for_invalid_inputs(tmp_path):
    portfolio = [
        item("P2025-1", period={"start": "2026-01"}),  # 형식 오류 ID
        item("P2025-02", period={"start": "2026/01"}),  # 날짜 형식 오류
        item("P2025-03", period="2026-01"),  # period가 매핑이 아님
        "not a mapping",
    ]
    report = validate(write(tmp_path, base_profile(), portfolio))
    assert report.warnings == []
    assert report.errors  # 오류는 따로 나온다


# --- T8: 파일 단위 오류 ---


def test_missing_profile_file(tmp_path):
    path = tmp_path / "none.yaml"
    report = assert_invalid_both_ways(path)
    assert report.errors == [f"{path}: file not found: {path}"]  # "<파일 경로>: <내용>"
    assert report.warnings == []


def test_missing_portfolio_file(tmp_path):
    path = write(tmp_path, base_profile())
    report = assert_invalid_both_ways(path)
    assert report.errors == [f"portfolio: file not found: {tmp_path / 'p.portfolio.yaml'}"]


def test_profile_yaml_syntax_error(tmp_path):
    path = write(tmp_path, "schema_version: 1\ncompany: {name: [unclosed\n")
    report = assert_invalid_both_ways(path)
    (line,) = report.errors
    assert line.startswith(f"{path}: yaml parse error")
    assert "\n" not in line


def test_portfolio_yaml_syntax_error(tmp_path):
    path = write(tmp_path, base_profile(), "- id: [unclosed\n")
    (line,) = assert_invalid_both_ways(path).errors
    assert line.startswith("portfolio: yaml parse error")


@pytest.mark.parametrize("text", ["- a\n- b\n", "just a string\n", ""])
def test_profile_top_level_not_mapping(tmp_path, text):
    path = write(tmp_path, text)
    (line,) = assert_invalid_both_ways(path).errors
    assert line.startswith(f"{path}: top-level must be a mapping")


@pytest.mark.parametrize("text", ["id: P2026-01\n", "# only comment\n"])
def test_portfolio_top_level_not_sequence(tmp_path, text):
    path = write(tmp_path, base_profile(), text)
    (line,) = assert_invalid_both_ways(path).errors
    assert line.startswith("portfolio: top-level must be a sequence")


def test_portfolio_key_in_profile_rejected(tmp_path):
    profile = base_profile()
    profile["portfolio"] = [item()]
    report = assert_invalid_both_ways(write(tmp_path, profile, [item()]))
    assert len(report.errors) == 1
    assert report.errors[0].startswith("portfolio: ")
    assert "portfolio_file" in report.errors[0]


def test_typo_top_level_key(tmp_path):
    profile = base_profile()
    profile["registraions"] = {}
    report = assert_invalid_both_ways(write(tmp_path, profile, [item()]))
    assert report.errors == ["registraions: Extra inputs are not permitted"]


def test_schema_version_2(tmp_path):
    profile = base_profile() | {"schema_version": 2}
    report = assert_invalid_both_ways(write(tmp_path, profile, [item()]))
    assert report.errors == ["schema_version: Input should be 1"]


def test_schema_errors_and_portfolio_errors_together(tmp_path):
    profile = base_profile()
    profile["company"]["size"] = "스타트업"
    report = validate(write(tmp_path, profile, [item("P2026-1")]))
    assert len(report.errors) == 2
    assert report.errors[0].startswith("company.size: ")
    assert report.errors[1].startswith("portfolio[#0].id: invalid id")


def test_profile_error_message_lists_errors(tmp_path):
    with pytest.raises(ProfileError) as exc:
        load_profile(tmp_path / "none.yaml")
    assert "file not found" in str(exc.value)


# --- 오류 경로: 식별 키·인덱스 ---


def test_error_paths_use_identity_keys(tmp_path):
    profile = base_profile()
    profile["registrations"] = {
        "direct_production": [{"item_no": "8111189901", "status": "pending"}],
        "iso": [{"std": "9001", "since": "2024/01"}],
        "web_accessibility_certs": {"sites": [{"site": "a.go.kr", "year": "2024"}]},
    }
    profile["company"]["branches"] = ["a", 3]
    profile["people"]["key_staff"] = [{"alias": "", "years": -1}]
    report = validate(write(tmp_path, profile, [item()]))
    expected = [
        "company.branches[#1]",
        "registrations.direct_production[8111189901].status",
        "registrations.iso[9001].since",
        "registrations.web_accessibility_certs.sites[a.go.kr].year",
        "people.key_staff[#0].years",  # 빈 문자열 식별 키는 인덱스
    ]
    for p in expected:
        assert len(lines_at(report.errors, p)) == 1, (p, report.errors)
    assert len(report.errors) == len(expected), report.errors


def test_union_list_branch_error_is_one_line(tmp_path):
    profile = base_profile()
    profile["registrations"] = {"g2b": {"industry_codes": [1468, "x", 2]}}
    report = validate(write(tmp_path, profile, [item()]))
    assert report.errors == [
        "registrations.g2b.industry_codes[#0]: Input should be a valid string; "
        "허용: list[str], 'unknown'"
    ]


# --- T11: onsite_capacity ---


def test_missing_onsite_region_filled_with_warning(tmp_path):
    profile = base_profile()
    del profile["people"]["onsite_capacity"]["부산"]
    path = write(tmp_path, profile, [item()])
    p = load_profile(path)
    assert p.people.onsite_capacity["부산"].ok == "unknown"
    assert p.people.onsite_capacity["부산"].max_people == "unknown"
    report = validate(path)
    assert report.errors == []
    assert report.warnings == ["people.onsite_capacity.부산: missing, treated as unknown"]


def test_onsite_other_max_people_is_error(tmp_path):
    profile = base_profile()
    profile["people"]["onsite_capacity"]["기타"] = {"ok": True, "max_people": 3}
    report = assert_invalid_both_ways(write(tmp_path, profile, [item()]))
    assert report.errors == [
        "people.onsite_capacity.기타.max_people: Extra inputs are not permitted"
    ]


def test_onsite_not_mapping_skips_warning(tmp_path):
    profile = base_profile()
    profile["people"]["onsite_capacity"] = None
    report = validate(write(tmp_path, profile, [item()]))
    assert report.warnings == []
    assert len(lines_at(report.errors, "people.onsite_capacity")) == 1
