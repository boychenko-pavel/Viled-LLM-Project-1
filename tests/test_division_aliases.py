from __future__ import annotations

import unittest

from sql_agent.division_aliases import (
    DIVISION_NAME_ALIASES,
    canonicalize_division_name,
    find_contextual_division_name,
)
from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory


class DivisionAliasTests(unittest.TestCase):
    def test_every_canonical_name_and_alias_resolves(self) -> None:
        for canonical_name, aliases in DIVISION_NAME_ALIASES.items():
            with self.subTest(canonical_name=canonical_name):
                self.assertEqual(canonicalize_division_name(canonical_name), canonical_name)
            for alias in aliases:
                with self.subTest(alias=alias):
                    self.assertEqual(canonicalize_division_name(alias), canonical_name)

    def test_saks_short_russian_alias_is_contextual(self) -> None:
        self.assertEqual(
            find_contextual_division_name("продажи в сакс за июнь"),
            "Saks Fifth Avenue",
        )

    def test_saks_prepositional_russian_alias_is_contextual(self) -> None:
        self.assertEqual(
            find_contextual_division_name("продажи ювелирки в саксе за вчера"),
            "Saks Fifth Avenue",
        )

    def test_saks_alias_becomes_sales_division_filter(self) -> None:
        intent = IntentParser().parse(
            "продажи по бутику сакс за июнь 2026",
            SqlAgentMemory(),
        )
        self.assertEqual(
            intent.filters.division_filters,
            {"division": "Saks Fifth Avenue"},
        )

    def test_saks_alias_stops_before_product_brand_filter(self) -> None:
        intent = IntentParser().parse(
            "\u043f\u0440\u043e\u0434\u0430\u0436\u0438 \u0431\u0443\u0442\u0438\u043a \u0441\u0430\u043a\u0441 \u0431\u0440\u0435\u043d\u0434 Tiffany & Co. \u0437\u0430 \u0432\u0447\u0435\u0440\u0430",
            SqlAgentMemory(),
        )

        self.assertEqual(
            intent.filters.division_filters,
            {"division": "Saks Fifth Avenue"},
        )
        self.assertEqual(intent.filters.dimension_filters["brand"], "Tiffany & Co")

    def test_english_and_russian_spellings_become_same_filter(self) -> None:
        parser = IntentParser()
        english = parser.parse(
            "sales in Cartier Almaty for June 2026",
            SqlAgentMemory(),
        )
        russian = parser.parse(
            "продажи в картье алматы за июнь 2026",
            SqlAgentMemory(),
        )
        expected = {"division": "Cartier Almaty"}
        self.assertEqual(english.filters.division_filters, expected)
        self.assertEqual(russian.filters.division_filters, expected)

    def test_name_without_store_context_does_not_override_product_brand(self) -> None:
        self.assertIsNone(find_contextual_division_name("продажи бренда Boucheron"))


if __name__ == "__main__":
    unittest.main()
