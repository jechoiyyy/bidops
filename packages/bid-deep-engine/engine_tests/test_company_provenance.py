"""회사 값 provenance sidecar 계약(spec T1). 파일 전용 fixture이며 네트워크를 쓰지 않는다."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import yaml

from bid_deep_engine.analysis.gates import (
    _CompanyReader,
    _trusted_list_identifiers,
    evaluate_gates,
    evaluate_gates_traced,
)
from bid_deep_engine.company.loader import (
    ProfileError,
    load_evidence_view,
    load_profile,
    todo,
    validate,
)
from bid_deep_engine.company.provenance import (
    CONFIRMED_LEVELS,
    CompanyEvidenceView,
    ProvenanceDocument,
    company_input_hash,
    resolve_profile_path,
    value_hash,
)
from bid_deep_engine.company.schema import UNKNOWN
from engine_tests.gate_factories import (
    direct_production,
    make_facts,
    make_profile,
    portfolio_item,
    rule,
    staffing,
)


def profile_data() -> dict:
    return {
        "schema_version": 1,
        "company": {"name": "㈜루트랩", "size": "중소기업"},
        "people": {
            "onsite_capacity": {
                "대구": {"ok": "unknown", "max_people": "unknown"},
                "경북": {"ok": "unknown", "max_people": "unknown"},
                "부산": {"ok": "unknown", "max_people": "unknown"},
                "서울": {"ok": "unknown", "max_people": "unknown"},
                "기타": {"ok": "unknown"},
            }
        },
        "portfolio_file": "portfolio.yaml",
        "capabilities": {"solutions": [{"name": "A.B[C]", "desc": None}]},
    }


def entry(value, *, level="confirmed", sources=None, value_hash_override=None) -> dict:
    return {
        "level": level,
        "sources": sources if sources is not None else [{"kind": "user", "ref": "회의 기록"}],
        "value_hash": value_hash_override or value_hash(value),
        "checked_at": "2026-10-24",
        "note": None,
    }


def write_profile(
    tmp_path: Path,
    profile: dict | None = None,
    *,
    provenance_text: str | None = None,
) -> Path:
    data = profile_data() if profile is None else profile
    data = dict(data)
    data["provenance_file"] = "profile.provenance.yaml" if provenance_text is not None else None
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (tmp_path / "portfolio.yaml").write_text("[]\n", encoding="utf-8")
    if provenance_text is not None:
        (tmp_path / "profile.provenance.yaml").write_text(provenance_text, encoding="utf-8")
    return path


def write_sidecar(tmp_path: Path, fields: dict, *, profile: dict | None = None) -> Path:
    sidecar = yaml.safe_dump(
        {"schema_version": 1, "fields": fields},
        allow_unicode=True,
        sort_keys=False,
    )
    return write_profile(tmp_path, profile, provenance_text=sidecar)


def test_legacy_profile_loads_without_provenance_and_preserves_raw_value(tmp_path):
    data = profile_data()
    data["provenance_file"] = None
    path = write_profile(tmp_path, data)
    before = path.read_bytes()

    raw_profile = load_profile(path)
    view = load_evidence_view(path)

    assert view.profile.model_dump(mode="json") == raw_profile.model_dump(mode="json")
    assert path.read_bytes() == before
    assert raw_profile.company.size == "중소기업"
    assert view.provenance is None
    assert view.get("company.size") == {
        "value": "중소기업",
        "level": "unknown",
        "effective_level": "unknown",
        "sources": [],
        "value_hash_matches": None,
    }
    assert view.decision_value("company.size") == UNKNOWN
    assert view.company_input_hash == company_input_hash(raw_profile)
    assert len(view.company_input_hash) == 64
    view_todo = {item.path: item for item in todo(view)}
    assert "company.size" in view_todo
    assert view_todo["company.size"].effective_level == "unknown"
    assert view_todo["company.size"].hint.endswith("출처 확인 필요")
    assert "company.size" not in {item.path for item in todo(raw_profile)}


def test_view_todo_lists_known_raw_values_missing_sidecar_metadata(tmp_path):
    path = write_sidecar(tmp_path, {"company.name": entry("㈜루트랩")})

    items = todo(load_evidence_view(path))
    by_path = {item.path: item for item in items}

    assert "company.name" not in by_path
    assert by_path["company.size"].effective_level == "unknown"
    assert by_path["company.size"].hint.endswith("출처 확인 필요")
    assert "capabilities.solutions" in by_path  # 목록 완전성 경로
    assert "capabilities.solutions[A%2EB%5BC%5D].desc" in by_path
    assert not any(
        path in by_path for path in ("schema_version", "portfolio_file", "provenance_file")
    )
    assert not any(path.endswith((".id", ".item_no", ".std", ".name")) for path in by_path)
    assert len(by_path) == len(items)


def test_confirmed_sidecar_exposes_decision_value_without_mutating_profile(tmp_path):
    path = write_sidecar(tmp_path, {"company.size": entry("중소기업")})
    profile = load_profile(path)
    before = profile.model_dump(mode="json")

    view = load_evidence_view(path)

    assert view.get("company.size") == {
        "value": "중소기업",
        "level": "confirmed",
        "effective_level": "confirmed",
        "sources": [{"kind": "user", "ref": "회의 기록"}],
        "value_hash_matches": True,
    }
    assert view.decision_value("company.size") == "중소기업"
    assert profile.model_dump(mode="json") == before
    items = {item.path: item for item in todo(view, required_paths=("company.size",))}
    assert "company.size" not in items


def test_value_hash_mismatch_is_warning_and_keeps_metadata(tmp_path):
    path = write_sidecar(
        tmp_path,
        {"company.size": entry("소기업", value_hash_override=value_hash("소기업"))},
    )

    report = validate(path)
    view = load_evidence_view(path)

    assert report.errors == []
    assert report.warnings == ["provenance.fields[company.size]: value_changed"]
    assert view.warnings == tuple(report.warnings)
    assert view.get("company.size")["value"] == "중소기업"
    assert view.get("company.size")["level"] == "confirmed"
    assert view.get("company.size")["effective_level"] == "unknown"
    assert view.get("company.size")["value_hash_matches"] is False
    assert view.decision_value("company.size") == UNKNOWN
    item = next(
        item for item in todo(view, required_paths=("company.size",)) if item.path == "company.size"
    )
    assert item.level == "confirmed"
    assert item.effective_level == "unknown"
    assert item.value_hash_matches is False
    assert item.hint.endswith("출처 확인 필요")


def test_special_character_list_id_uses_canonical_percent_path(tmp_path):
    path = write_sidecar(
        tmp_path,
        {"capabilities.solutions[A%2EB%5BC%5D].desc": entry(None)},
    )

    view = load_evidence_view(path)

    assert view.get("capabilities.solutions[A%2EB%5BC%5D].desc")["value"] is None
    assert view.get("capabilities.solutions[A%2EB%5BC%5D].desc")["effective_level"] == "confirmed"
    assert view.decision_value("capabilities.solutions[A%2EB%5BC%5D].desc") is None
    assert view.get("capabilities.solutions[A%2EB%5BC%5D].name")["value"] == "A.B[C]"


def test_todo_uses_canonical_special_character_list_id(tmp_path):
    data = profile_data()
    data["capabilities"]["solutions"][0]["desc"] = "unknown"
    path = write_profile(tmp_path, data)

    paths = [item.path for item in todo(load_profile(path))]

    assert "capabilities.solutions[A%2EB%5BC%5D].desc" in paths


def test_noncanonical_and_missing_sidecar_paths_fail_validation(tmp_path):
    path = write_sidecar(
        tmp_path,
        {
            "company.크기": entry("중소기업"),
            "company.missing": entry("값"),
        },
    )

    report = validate(path)

    assert len(report.errors) == 2
    assert any("company.크기" in error and "non-canonical path" in error for error in report.errors)
    assert any(
        "company.missing" in error and "path does not exist" in error for error in report.errors
    )
    try:
        load_evidence_view(path)
    except ProfileError as exc:
        assert exc.errors == report.errors
    else:
        raise AssertionError("invalid sidecar path should prevent loading")


def test_lowercase_percent_escape_is_rejected_as_noncanonical(tmp_path):
    path = write_sidecar(
        tmp_path,
        {"capabilities.solutions[A%2eB%5BC%5D].desc": entry(None)},
    )

    report = validate(path)

    assert len(report.errors) == 1
    assert "non-canonical path" in report.errors[0]


def test_duplicate_yaml_keys_in_sidecar_are_rejected(tmp_path):
    duplicate = """schema_version: 1
fields:
  company.size:
    level: confirmed
    sources: [{kind: user, ref: meeting}]
    value_hash: 0000000000000000000000000000000000000000000000000000000000000000
    checked_at: null
    note: null
  company.size:
    level: demo
    sources: []
    value_hash: 0000000000000000000000000000000000000000000000000000000000000000
    checked_at: null
    note: null
"""
    path = write_profile(tmp_path, provenance_text=duplicate)

    report = validate(path)

    assert len(report.errors) == 1
    assert report.errors[0].startswith("provenance_file: yaml parse error: ")
    assert "duplicate key" in report.errors[0]


def test_malformed_sidecar_structure_and_hash_format_are_errors(tmp_path):
    path = write_sidecar(
        tmp_path,
        {"company.size": entry("중소기업", value_hash_override="A" * 64)},
    )

    report = validate(path)

    assert len(report.errors) == 1
    assert report.errors[0].startswith("provenance.fields[company.size].value_hash:")


def test_sidecar_schema_version_rejects_bool_and_float(tmp_path):
    for name, version in (("bool", True), ("float", 1.0)):
        case_dir = tmp_path / name
        case_dir.mkdir()
        sidecar_text = yaml.safe_dump(
            {"schema_version": version, "fields": {}},
            allow_unicode=True,
            sort_keys=False,
        )
        report = validate(write_profile(case_dir, provenance_text=sidecar_text))

        assert len(report.errors) == 1
        assert report.errors[0].startswith("provenance.schema_version:")


def test_confirmed_and_public_require_sources(tmp_path):
    fields = {
        "company.size": entry("중소기업", sources=[]),
        "company.name": entry("㈜루트랩", level="public", sources=[]),
    }
    path = write_sidecar(tmp_path, fields)

    report = validate(path)

    assert len(report.errors) == 2
    assert any(
        "company.size" in error and "requires at least one source" in error
        for error in report.errors
    )
    assert any(
        "company.name" in error and "requires at least one source" in error
        for error in report.errors
    )


def test_checked_at_requires_real_full_date(tmp_path):
    fields = {"company.size": entry("중소기업") | {"checked_at": "2026-02-30"}}
    path = write_sidecar(tmp_path, fields)

    report = validate(path)

    assert len(report.errors) == 1
    assert report.errors[0].startswith("provenance.fields[company.size].checked_at:")


def test_provenance_file_path_is_confined_to_profile_directory(tmp_path):
    path = tmp_path / "profile.yaml"
    data = profile_data() | {"provenance_file": "../outside.yaml"}
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    (tmp_path / "portfolio.yaml").write_text("[]\n", encoding="utf-8")

    report = validate(path)

    assert len(report.errors) == 1
    assert report.errors[0].startswith("provenance_file: path must be relative")


def test_provenance_file_cannot_escape_through_symlink(tmp_path):
    profile_dir = tmp_path / "company"
    profile_dir.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("schema_version: 1\nfields: {}\n", encoding="utf-8")
    (profile_dir / "linked.yaml").symlink_to(outside)
    profile = profile_data() | {"provenance_file": "linked.yaml"}
    path = profile_dir / "profile.yaml"
    path.write_text(yaml.safe_dump(profile, allow_unicode=True), encoding="utf-8")
    (profile_dir / "portfolio.yaml").write_text("[]\n", encoding="utf-8")

    report = validate(path)

    assert len(report.errors) == 1
    assert report.errors[0] == "provenance_file: path resolves outside the profile directory"


def test_missing_explicit_sidecar_is_validation_error(tmp_path):
    data = profile_data() | {"provenance_file": "missing.yaml"}
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    (tmp_path / "portfolio.yaml").write_text("[]\n", encoding="utf-8")

    report = validate(path)

    assert len(report.errors) == 1
    assert report.errors[0].startswith("provenance_file: file not found:")


def test_duplicate_ids_are_rejected_for_non_portfolio_lists_too(tmp_path):
    data = profile_data()
    data["registrations"] = {
        "iso": [{"std": "9001"}, {"std": "9001"}],
        "direct_production": [
            {"item_no": "8111189901"},
            {"item_no": "8111189901"},
        ],
    }
    path = write_profile(tmp_path, data)

    report = validate(path)

    assert report.errors == [
        "registrations.direct_production[8111189901].item_no: duplicate id",
        "registrations.iso[9001].std: duplicate id",
    ]


def test_canonical_duplicate_list_id_errors_percent_encode_identifier(tmp_path):
    data = profile_data()
    data["capabilities"]["solutions"] = [
        {"name": "A.B", "desc": None},
        {"name": "A.B", "desc": None},
    ]
    path = write_profile(tmp_path, data)

    report = validate(path)

    assert "capabilities.solutions[A%2EB].name: duplicate id" in report.errors


def test_company_input_hash_ignores_sidecar_pointer_and_changes_with_metadata(tmp_path):
    base = profile_data() | {"provenance_file": None}
    profile_path = write_profile(tmp_path, base)
    legacy_profile = load_profile(profile_path)
    legacy_hash = company_input_hash(legacy_profile)

    sidecar_path = write_sidecar(
        tmp_path,
        {"company.size": entry("중소기업", level="demo", sources=[])},
        profile=base,
    )
    with_sidecar = load_evidence_view(sidecar_path)

    assert with_sidecar.profile.company.size == legacy_profile.company.size
    assert with_sidecar.company_input_hash != legacy_hash
    changed_pointer = with_sidecar.profile.model_copy(update={"provenance_file": "other.yaml"})
    assert (
        company_input_hash(changed_pointer, with_sidecar.provenance)
        == with_sidecar.company_input_hash
    )

    profile_payload = with_sidecar.profile.model_dump(mode="json")
    profile_payload.pop("provenance_file")
    expected_payload = {
        "schema_version": 1,
        "profile": profile_payload,
        "provenance": with_sidecar.provenance.to_payload(),
    }
    expected_hash = hashlib.sha256(
        json.dumps(
            expected_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert with_sidecar.company_input_hash == expected_hash
    assert (
        company_input_hash(with_sidecar.profile, with_sidecar.provenance)
        == with_sidecar.company_input_hash
    )


def test_sme_classification_defaults_to_unknown_and_rejects_other_values(tmp_path):
    path = write_profile(tmp_path)
    assert load_profile(path).registrations.sme_certificate.classification == "unknown"

    invalid = profile_data()
    invalid["registrations"] = {"sme_certificate": {"classification": "스타트업"}}
    invalid_path = tmp_path / "invalid.yaml"
    invalid["portfolio_file"] = "portfolio.yaml"
    invalid_path.write_text(
        yaml.safe_dump(invalid, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    report = validate(invalid_path)

    assert report.errors
    assert any("registrations.sme_certificate.classification" in error for error in report.errors)


# --- PF-01 T1: 기본 뷰(confirmed만 수용)의 판정은 수용 수준 뷰 도입 전과 같다 ---

LEVELED_AS_OF = date(2026, 11, 5)


def leveled_view(profile, levels: dict[str, str]) -> CompanyEvidenceView:
    """경로별 출처 수준을 지정한 기본 뷰. 값 해시는 현재 값과 일치한다."""
    fields = {
        path: {
            "level": level,
            "sources": [{"kind": "user", "ref": "PF-01 T1 synthetic fixture"}],
            "value_hash": value_hash(resolve_profile_path(profile, path)),
            "checked_at": None,
            "note": None,
        }
        for path, level in levels.items()
    }
    provenance = ProvenanceDocument.model_validate({"schema_version": 1, "fields": fields})
    return CompanyEvidenceView(profile, provenance)


def _mixed_level_profile():
    return make_profile(
        {
            "company.size": "중소기업",
            "company.founded": "2010-01",
            "registrations.g2b.registered": True,
            "registrations.venture": {"type": "기술평가보증", "since": "2020-01"},
            "registrations.iso": [{"std": "9001", "since": "2020-01"}],
            "people.total_tech_staff": 10,
        },
        portfolio=[
            portfolio_item("P2020-01", title="홈페이지 유지관리", completed=True),
            portfolio_item("P2021-01", title="챗봇 구축", completed=True),
        ],
        direct_production=[direct_production("8111189901", status="valid")],
    )


def test_pf01_t1_default_view_accepts_confirmed_and_demo():
    """기본 뷰는 confirmed와 demo(데모 임의값, 2026-10-25)를 수용하고 public·estimate·unknown은
    수용하지 않는다."""
    profile = _mixed_level_profile()
    view = leveled_view(
        profile,
        {
            "company.size": "confirmed",
            "company.founded": "public",
            "people.total_tech_staff": "estimate",
            "registrations.g2b.registered": "demo",
        },
    )

    assert view.accepted_levels == frozenset({"confirmed", "demo"})
    assert view.accepted_levels == CONFIRMED_LEVELS
    assert view.accepts("confirmed")
    assert view.accepts("demo")
    for level in ("public", "estimate", "unknown"):
        assert not view.accepts(level)
    assert view.decision_value("company.size") == "중소기업"
    assert view.decision_value("company.founded") == UNKNOWN
    assert view.decision_value("people.total_tech_staff") == UNKNOWN
    assert view.decision_value("registrations.g2b.registered") is True
    # 표지·level은 그대로 남는다(교체 대상 추적용).
    assert view.get("registrations.g2b.registered")["level"] == "demo"
    assert view.get("registrations.g2b.registered")["effective_level"] == "demo"


def test_default_view_demo_with_stale_hash_or_unknown_value_is_not_accepted():
    """demo도 value_hash가 현재 값과 다르거나 값이 unknown이면 effective unknown이라 수용되지
    않는다."""
    profile = _mixed_level_profile()
    view = leveled_view(profile, {"registrations.g2b.registered": "demo"})
    stale_fields = view.provenance.to_payload()["fields"]
    stale_fields["registrations.g2b.registered"]["value_hash"] = value_hash(False)
    stale = CompanyEvidenceView(
        profile,
        ProvenanceDocument.model_validate({"schema_version": 1, "fields": stale_fields}),
    )
    assert stale.get("registrations.g2b.registered")["effective_level"] == "unknown"
    assert stale.decision_value("registrations.g2b.registered") == UNKNOWN

    unknown_profile = make_profile({"company.size": UNKNOWN})
    unknown_view = leveled_view(unknown_profile, {"company.size": "demo"})
    assert unknown_view.get("company.size")["effective_level"] == "unknown"
    assert unknown_view.decision_value("company.size") == UNKNOWN


def test_pf01_t1_default_reader_value_optional_present_and_trusted_ids_unchanged():
    profile = _mixed_level_profile()
    public_view = leveled_view(
        profile,
        {
            "company.size": "public",
            "registrations.venture.type": "public",
            "registrations.iso[9001]": "public",
            "registrations.iso[9001].std": "estimate",
        },
    )
    reader = _CompanyReader(public_view)
    assert reader.value("company.size") == UNKNOWN
    assert reader.optional_present("registrations.venture", ("type", "since", "valid_until")) == (
        UNKNOWN,
        ["registrations.venture.type"],
    )
    assert _trusted_list_identifiers(
        reader, "registrations.iso", profile.registrations.iso, "std"
    ) == ([], ["registrations.iso"])

    confirmed = leveled_view(
        profile,
        {
            "company.size": "confirmed",
            "registrations.venture.type": "confirmed",
            "registrations.iso[9001]": "confirmed",
        },
    )
    reader = _CompanyReader(confirmed)
    assert reader.value("company.size") == "중소기업"
    assert reader.optional_present("registrations.venture", ("type", "since", "valid_until")) == (
        True,
        [],
    )
    assert _trusted_list_identifiers(
        reader, "registrations.iso", profile.registrations.iso, "std"
    ) == (["9001"], ["registrations.iso"])

    id_only = leveled_view(profile, {"registrations.iso[9001].std": "confirmed"})
    assert _trusted_list_identifiers(
        _CompanyReader(id_only), "registrations.iso", profile.registrations.iso, "std"
    ) == (["9001"], ["registrations.iso"])


def test_pf01_t1_default_view_never_assumes_list_completeness():
    profile = _mixed_level_profile()
    view = leveled_view(
        profile,
        {
            "portfolio[P2020-01].title": "public",
            "registrations.direct_production[8111189901].status": "estimate",
        },
    )
    reader = _CompanyReader(view)

    assert reader.list_complete("portfolio") is False
    assert reader.list_complete("registrations.direct_production") is False
    assert reader.assumed_lists == []
    assert reader.input_fields == ["portfolio", "registrations.direct_production"]


def test_pf01_t1_default_gate_output_is_identical_to_traced_and_explicit_confirmed_view():
    profile = _mixed_level_profile()
    view = leveled_view(
        profile,
        {
            "company.size": "confirmed",
            "company.founded": "confirmed",
            "registrations.g2b.registered": "public",
            "registrations.venture.type": "estimate",
            "registrations.iso[9001]": "demo",
            "people.total_tech_staff": "public",
            "portfolio[P2020-01].title": "public",
            "portfolio[P2020-01].domain": "public",
            "portfolio[P2020-01].completed": "public",
            "registrations.direct_production[8111189901].status": "public",
        },
    )
    facts = make_facts(
        submission_deadline="2026-11-05 10:00",
        eligibility=[
            rule("LARGE_CORP_EXCLUDED", "대기업 참여 제한"),
            rule("G2B_REGISTERED", "나라장터 등록"),
            rule("REQUIRED_CERT", "ISO 9001 보유", cert_name="ISO 9001"),
            rule("DIRECT_PRODUCTION", "직접생산확인", item_no=["8111189901", "8111159901"]),
            rule("PAST_PERFORMANCE", "챗봇 구축 실적", keyword="챗봇 구축"),
            rule("PAST_PERFORMANCE", "드론 실적", keyword="드론 관제"),
        ],
        staffing=[staffing("PM", count=1, resident=True, location="서울")],
        consortium_allowed=False,
        subcontract_allowed=False,
    )

    baseline = evaluate_gates(facts, view.profile, as_of=LEVELED_AS_OF, evidence_view=view)
    traced, assumed = evaluate_gates_traced(
        facts, view.profile, as_of=LEVELED_AS_OF, evidence_view=view
    )
    explicit = view.with_accepted_levels(frozenset({"confirmed", "demo"}))
    explicit_gates = evaluate_gates(
        facts, explicit.profile, as_of=LEVELED_AS_OF, evidence_view=explicit
    )

    dump = [g.model_dump_json() for g in baseline]
    assert [g.model_dump_json() for g in traced] == dump
    assert [g.model_dump_json() for g in explicit_gates] == dump
    assert assumed == ()
    by_rule = {g.rule_text.split(" [")[0]: g for g in baseline}
    assert by_rule["대기업 참여 제한"].verdict == "PASS"
    assert by_rule["나라장터 등록"].verdict == "UNKNOWN"
    # demo 수준 ISO 항목은 기본 뷰에서 확인값과 같이 쓰인다.
    assert by_rule["ISO 9001 보유"].verdict == "PASS"
    assert by_rule["직접생산확인"].verdict == "UNKNOWN"
    assert "registrations.direct_production" in by_rule["직접생산확인"].unknown_fields
    assert by_rule["드론 실적"].verdict == "UNKNOWN"
