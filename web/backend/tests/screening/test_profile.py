from pathlib import Path

from app.screening.services.profile import count_reference_mentions, parse_profile

# 실회사 프로필은 Git에 없다(.gitignore). 같은 형식의 합성 예시로 파서 동작을 검사한다.
EXAMPLE_PROFILE = Path(__file__).resolve().parents[4] / "docs" / "reference" / "company-profile.example.md"


def test_company_profile_status_counts_and_unknown_items_are_preserved():
    profile = parse_profile(EXAMPLE_PROFILE)

    assert len(profile.sections) == 5
    assert dict(profile.status_counts) == {"confirmed": 4, "inferred": 2, "unknown": 2}
    assert len(profile.unknown_items) == 2
    assert {item.section_number for _, item in profile.unknown_items} == {"1", "5.2"}


def test_malformed_yaml_keeps_the_original_block(tmp_path: Path):
    source = tmp_path / "company-profile.md"
    raw_block = "```yaml\ncompany: [broken\n```\n"
    source.write_text(f"# 1. Company Identity\n\n{raw_block}", encoding="utf-8")

    profile = parse_profile(source)

    assert profile.sections[0].raw_blocks[0].raw == raw_block
    assert profile.parse_errors
    assert profile.status_counts == {}


def test_reference_count_uses_section_or_item_mentions_without_turning_unavailable_into_zero():
    profile = parse_profile(EXAMPLE_PROFILE)
    section, item = next((section, item) for section, item in profile.unknown_items if item.section_number == "5.2")

    assert section.number == "5.2"
    assert count_reference_mentions(item, [
        "회사 프로필 5.2 자격·조달 관련 정보 (unknown)",
        "회사 프로필 5.2 자격·조달 관련 정보 (unknown)",
        "소프트웨어사업자 신고 여부는 확인되지 않았다.",
    ]) == 2
