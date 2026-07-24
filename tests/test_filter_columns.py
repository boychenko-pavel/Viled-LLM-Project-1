from __future__ import annotations

import unittest

from sql_agent.intents import QueryFilters, QueryIntent
from sql_agent.sql_builder import SqlBuilder


class FilterColumnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = SqlBuilder()

    def test_all_active_filter_columns_are_included_in_select(self) -> None:
        intent = QueryIntent(
            operation="select",
            domain="sales",
            schema_name="LLM",
            table_name="sales",
            requested_columns=["amount"],
            filters=QueryFilters(
                date_column="sale_date",
                date_from="2026-06-01",
                date_to="2026-06-30",
                identifier_column="product_id",
                identifier_value="12345",
                threshold_column="quantity",
                threshold_operator=">",
                threshold_value="0",
                equality_filters={"payment_type": "card"},
                dimension_filters={"brand": "Test Brand"},
                division_filters={"city": "Алматы"},
            ),
        )

        self.assertEqual(
            [
                "amount",
                "product_id",
                "sale_date",
                "quantity",
                "payment_type",
                "brand",
                "city",
            ],
            self.builder._resolve_select_columns(intent),
        )

    def test_filter_columns_are_not_duplicated(self) -> None:
        intent = QueryIntent(
            operation="select",
            domain="sales",
            schema_name="LLM",
            table_name="sales",
            requested_columns=["sale_date", "product_id", "amount"],
            filters=QueryFilters(
                date_column="sale_date",
                date_eq="2026-06-01",
                identifier_column="product_id",
                identifier_values=["12345", "67890"],
            ),
        )

        self.assertEqual(
            ["sale_date", "product_id", "amount"],
            self.builder._resolve_select_columns(intent),
        )


if __name__ == "__main__":
    unittest.main()
