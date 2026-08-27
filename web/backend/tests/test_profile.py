from pathlib import Path

from app.services.profile import count_reference_mentions, parse_profile


def test_company_profile_status_counts_and_unknown_items_are_preserved():
    profile = parse_profile()

    assert len(profile.sections) == 7
    assert dict(profile.status_counts) == {"confirmed": 24, "inferred": 4, "unknown": 15}
    assert len(profile.unknown_items) == 15
    assert {item.section_number for _, item in profile.unknown_items} == {"2.7", "4.2", "4.4", "4.5", "4.6", "4.8", "5.1", "5.3", "5.4"}


def test_malformed_yaml_keeps_the_original_block(tmp_path: Path):
    source = tmp_path / "company-profile.md"
    raw_block = "```yaml\ncompany: [broken\n```\n"
    source.write_text(f"# 1. Company Identity\n\n{raw_block}", encoding="utf-8")

    profile = parse_profile(source)

    assert profile.sections[0].raw_blocks[0].raw == raw_block
    assert profile.parse_errors
    assert profile.status_counts == {}


def test_reference_count_uses_section_or_item_mentions_without_turning_unavailable_into_zero():
    profile = parse_profile()
    section, item = next((section, item) for section, item in profile.unknown_items if item.section_number == "2.7")

    assert section.number == "2.7"
    assert count_reference_mentions(item, [
        "회사 프로필 2.7 인력 (unknown)",
        "회사 프로필 2.7 인력 (unknown)",
        "PM·PL 보유 인력은 확인되지 않았다.",
    ]) == 2
