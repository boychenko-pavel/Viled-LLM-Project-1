from __future__ import annotations

import unittest
from types import SimpleNamespace

from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory
from sql_agent.sql_builder import SqlBuilder
import sql_agent.sql_builder as sql_builder_module


class GrossMarginQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = IntentParser()
        self.builder = SqlBuilder()
        self.memory = SqlAgentMemory()
        self._original_run_sql_query = sql_builder_module.run_sql_query
        self.sql: str | None = None

        def capture_sql(_engine, sql: str):
            self.sql = sql
            return []

        sql_builder_module.run_sql_query = capture_sql

    def tearDown(self) -> None:
        sql_builder_module.run_sql_query = self._original_run_sql_query

    def _build_sql(self, question: str) -> str:
        intent = self.parser.parse(question, self.memory)
        self.assertEqual("gross_margin", intent.operation)
        self.builder.execute(SimpleNamespace(_engine=object()), intent)
        self.assertIsNotNone(self.sql)
        return self.sql or ""

    def test_gm_by_article_is_detailed_to_sprut_code(self) -> None:
        sql = self._build_sql("Посчитай GM по артикулу G062214")

        self.assertIn("dim.[article] = 'G062214'", sql)
        self.assertIn("margin.[product_id]", sql)
        self.assertIn("ORDER BY dim.[article], margin.[product_id]", sql)
        self.assertNotIn("GROUP BY dim.[article]", sql)

    def test_gm_by_article_applies_requested_discount(self) -> None:
        sql = self._build_sql("маржинальность артикул 2807742 при скидке 40%")

        self.assertIn("dim.[article] = '2807742'", sql)
        self.assertNotIn("dim.[article] = '2807742 при скидке 40'", sql)
        self.assertIn(
            "CAST(price.[full_retail_price_kzt] AS decimal(38, 6)) "
            "* CAST(0.600000 AS decimal(38, 6))",
            sql,
        )
        expected_discount_columns = (
            "AS retail_price_kzt_before_discount, "
            "CAST(ROUND(margin.discount_percent, 2) "
            "AS decimal(38, 2)) AS discount_percent, "
            "CAST(ROUND(margin.retail_price_kzt_after_discount, 2) "
            "AS decimal(38, 2)) AS retail_price_kzt_after_discount"
        )
        self.assertIn(expected_discount_columns, sql)
        self.assertIn(
            "CAST(40.000000 AS decimal(38, 6)) AS discount_percent",
            sql,
        )

    def test_gross_margin_by_brand_returns_each_product(self) -> None:
        sql = self._build_sql("Покажи Gross Margin по бренду Nike")

        self.assertIn("dim.[brand] = 'Nike'", sql)
        self.assertIn(
            "margin.[product_id], dim.[article], dim.[brand], dim.[name]",
            sql,
        )
        self.assertIn(
            "ORDER BY dim.[brand], dim.[article], margin.[product_id]",
            sql,
        )

    def test_gm_by_sprut_code_filters_product_id(self) -> None:
        sql = self._build_sql("Рассчитай ГМ по коду спрута 12345")

        self.assertIn("margin.[product_id] = '12345'", sql)
        self.assertIn(
            "ROW_NUMBER() OVER (PARTITION BY [ware_id] ORDER BY [price_date] DESC)",
            sql,
        )

    def test_gm_uses_only_positive_current_stock(self) -> None:
        sql = self._build_sql("Маржинальность товаров")

        self.assertIn("FROM [DWH].[LLM].[stock]", sql)
        self.assertIn("HAVING SUM([quantity]) > 0", sql)
        self.assertIn("WHERE [date] <= GETDATE()", sql)

    def test_gm_uses_latest_price_and_current_average_cost(self) -> None:
        sql = self._build_sql("Маржа по артикулам")

        self.assertIn("FROM [DWH].[LLM].[price]", sql)
        self.assertIn("WHERE price.rn = 1 AND cost.rn = 1", sql)
        self.assertIn("cost.[cost_sum]", sql)
        self.assertIn("cost.[qnt_sum]", sql)
        self.assertIn("NULLIF", sql)
        self.assertIn("CAST(1.16 AS decimal(38, 6))", sql)
        self.assertIn("gross_margin_kzt", sql)
        self.assertIn("gross_margin_percent", sql)

    def test_gm_report_has_required_columns_in_required_order(self) -> None:
        sql = self._build_sql("GM по бренду Nike")

        expected_select = (
            "margin.stock_quantity AS [остаток], margin.[product_id], "
            "dim.[article], dim.[brand], dim.[name], margin.[price_date], "
            "margin.cost_date, "
            "CAST(ROUND(margin.retail_price_kzt_vat_included, 2) "
            "AS decimal(38, 2)) AS retail_price_kzt_incl_vat, "
            "CAST(ROUND(margin.retail_price_kzt_vat_excluded, 2) "
            "AS decimal(38, 2)) AS retail_price_kzt_excl_vat, "
            "CAST(ROUND(margin.unit_cost_kzt, 2) "
            "AS decimal(38, 2)) AS cost_kzt_per_unit, "
            "CAST(ROUND(margin.gross_margin_kzt, 2) "
            "AS decimal(38, 2)) AS gross_profit_kzt_per_unit, "
            "CAST(ROUND(margin.gross_margin_percent, 2) "
            "AS decimal(38, 2)) AS gross_margin_percent"
        )
        self.assertIn(expected_select, sql)

    def test_all_supported_gm_aliases_use_deterministic_operation(self) -> None:
        for alias in ("GM", "Gross Margin", "ГМ", "Маржинальность", "Маржа"):
            with self.subTest(alias=alias):
                intent = self.parser.parse(alias, self.memory)
                self.assertEqual("gross_margin", intent.operation)


if __name__ == "__main__":
    unittest.main()
