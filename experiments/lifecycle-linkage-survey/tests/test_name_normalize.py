"""Pure, offline tests for name search normalization."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import name_normalize as normalize


class NormalizeTests(unittest.TestCase):
    def test_character_classification_keeps_unknown_out_of_both_measured_sets(self) -> None:
        self.assertEqual(
            set(normalize.CONFIRMED_BREAKING_CHARS), {"·", "&", "‘", "’", "•"}
        )
        for harmless in "~/_『』・‧․":
            self.assertIn(harmless, normalize.CONFIRMED_HARMLESS_CHARS)
        self.assertEqual(normalize.UNKNOWN_CHARS, "∙")
        self.assertNotIn("∙", normalize.CONFIRMED_BREAKING_CHARS)
        self.assertNotIn("∙", normalize.CONFIRMED_HARMLESS_CHARS)

    def test_middle_dot_codepoints_are_equivalent(self) -> None:
        values = [normalize.normalize(f"가{dot}나") for dot in normalize.DOT_CHARS]

        self.assertEqual(len(set(values)), 1)

    def test_leading_tags_are_removed_without_removing_body_text(self) -> None:
        self.assertEqual(
            normalize.normalize("[재공고] (긴급) 2026년 재공고 사업"),
            "2026년 재공고 사업",
        )
        self.assertEqual(normalize.normalize("[재공고]"), "")

    def test_longest_fragment_is_a_literal_substring(self) -> None:
        name = "기관  \t사업(세부) 용역"

        fragment = normalize.longest_fragment(name)

        self.assertIsNotNone(fragment)
        self.assertIn(fragment, name)
        self.assertEqual(fragment, "기관  \t사업")

    def test_breaking_split_splits_all_confirmed_breakers_and_keeps_harmless_context(
        self,
    ) -> None:
        for breaking in normalize.CONFIRMED_BREAKING_CHARS:
            name = f"기관  사업(세부)~사업/『내용』{breaking}용역"

            fragment = normalize.breaking_split(name)

            self.assertEqual(fragment, "기관  사업(세부)~사업/『내용』")
            self.assertIn(fragment, name)
            self.assertIn("  ", fragment)
            self.assertIn("(세부)", fragment)
            self.assertIn("~", fragment)
            self.assertIn("/", fragment)
            self.assertIn("『내용』", fragment)
            self.assertNotIn(breaking, fragment)

    def test_breaking_split_is_absent_without_a_confirmed_breaker(self) -> None:
        name = "기관 사업(세부) ~사업/『내용』・‧․∙ 용역"

        self.assertIsNone(normalize.breaking_split(name))
        self.assertNotIn(
            "breaking_split",
            [strategy for strategy, _query in normalize.search_variants(name)],
        )

    def test_short_queries_are_omitted_and_duplicate_queries_are_removed(self) -> None:
        self.assertEqual(normalize.search_variants("가나다"), [])

        variants = normalize.search_variants("abcdef")
        queries = [query for _strategy, query in variants]

        self.assertEqual(queries, ["abcdef"])
        self.assertEqual(len(queries), len(set(queries)))
        self.assertTrue(all(len(query) >= normalize.MIN_FRAGMENT_CHARS for query in queries))

    def test_ladder_is_ordered_and_fragment_is_literal(self) -> None:
        name = "[재공고] 긴본문구간·아주긴연속부분 사업(세부) 용역"

        variants = normalize.search_variants(name)

        self.assertEqual(
            [strategy for strategy, _query in variants],
            ["full", "breaking_split", "normalized", "longest_fragment", "prefix12"],
        )
        breaking_fragment = dict(variants)["breaking_split"]
        self.assertIn(breaking_fragment, name)
        fragment = dict(variants)["longest_fragment"]
        self.assertIn(fragment, name)

    def test_prefix12_uses_collapsed_source_not_normalized_source(self) -> None:
        name = "가나다라마바사·아자차카타파"
        variants = dict(normalize.search_variants(name))

        self.assertEqual(
            variants["prefix12"], normalize.collapse(name)[: normalize.PREFIX_CHARS].strip()
        )
        self.assertNotEqual(
            variants["prefix12"], normalize.normalize(name)[: normalize.PREFIX_CHARS].strip()
        )


if __name__ == "__main__":
    unittest.main()
