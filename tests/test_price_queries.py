from __future__ import annotations

import unittest
from types import SimpleNamespace

from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory
from sql_agent.sql_builder import SqlBuilder
import sql_agent.sql_builder as sql_builder_module


class PriceQueryTests(unittest.TestCase):
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
        self.builder.execute(SimpleNamespace(_engine=object()), intent)
        self.assertIsNotNone(self.sql)
        return self.sql or ""

    def test_latest_price_for_single_sprut_code_uses_price_date(self) -> None:
        sql = self._build_sql("Покажи последнюю цену товара 12345")

        self.assertIn("ROW_NUMBER() OVER (PARTITION BY [ware_id] ORDER BY [price_date] DESC)", sql)
        self.assertIn("[ware_id] = '12345'", sql)
        self.assertIn("WHERE rn = 1", sql)

    def test_latest_price_by_product_phrase_includes_price_columns(self) -> None:
        sql = self._build_sql("покажи последнюю цену по товару 2192403")

        self.assertIn("FROM [DWH].[LLM].[price]", sql)
        self.assertIn("[ware_id] = '2192403'", sql)
        self.assertIn("[price_date]", sql)
        self.assertIn("[full_retail_price_kzt]", sql)
        self.assertIn("[full_retail_price_eur]", sql)
        self.assertIn("[full_retail_price_usd]", sql)

    def test_latest_price_by_article_joins_product_dimension(self) -> None:
        sql = self._build_sql("последняя цена артикул G062214")

        self.assertIn("FROM [DWH].[LLM].[price] AS fact", sql)
        self.assertIn("INNER JOIN product_scope AS dim", sql)
        self.assertIn("ON fact.[ware_id] = dim.[product_id]", sql)
        self.assertIn("dim.[article] = 'G062214'", sql)
        self.assertIn(
            "ROW_NUMBER() OVER (PARTITION BY fact.[ware_id] ORDER BY fact.[price_date] DESC)",
            sql,
        )
        self.assertIn("WHERE rn = 1", sql)

    def test_latest_price_by_article_prefix_uses_like_filter(self) -> None:
        sql = self._build_sql("последняя цена артикул начинается с B42298")

        self.assertIn("INNER JOIN product_scope AS dim", sql)
        self.assertIn("dim.[article] LIKE 'B42298%'", sql)
        self.assertNotIn("dim.[article] = 'начинается'", sql)
        self.assertIn("WHERE rn = 1", sql)

    def test_latest_price_by_article_in_stock_filters_current_positive_balance(self) -> None:
        sql = self._build_sql("последняя цена артикул 69683886 только в наличии")

        self.assertIn("FROM [DWH].[LLM].[price] AS fact", sql)
        self.assertIn("dim.[article] = '69683886'", sql)
        self.assertNotIn("69683886 только в наличии", sql)
        self.assertIn("FROM [DWH].[LLM].[stock] AS stock_availability", sql)
        self.assertIn("stock_availability.[product_id] = fact.[ware_id]", sql)
        self.assertIn("HAVING SUM(stock_availability.[quantity]) > 0", sql)

    def test_price_on_stock_phrase_is_an_availability_filter(self) -> None:
        sql = self._build_sql("последняя цена артикул 69683886 на остатках")

        self.assertIn("FROM [DWH].[LLM].[price] AS fact", sql)
        self.assertIn("dim.[article] = '69683886'", sql)
        self.assertIn("HAVING SUM(stock_availability.[quantity]) > 0", sql)

    def test_current_price_for_multiple_sprut_codes_after_item_word(self) -> None:
        sql = self._build_sql("Актуальная цена товара 111 222 333")

        self.assertIn("[ware_id] IN ('111', '222', '333')", sql)
        self.assertIn("PARTITION BY [ware_id]", sql)
        self.assertIn("ORDER BY [price_date] DESC", sql)

    def test_item_numbers_are_not_sprut_codes_when_brand_or_article_is_named(self) -> None:
        intent = self.parser.parse("Покажи цену товара бренд Nike 12345", self.memory)

        self.assertEqual([], intent.filters.identifier_values)
        self.assertFalse(intent.latest_per_identifier)

    def test_year_after_item_code_is_not_treated_as_sprut_code(self) -> None:
        intent = self.parser.parse("Покажи цену товара 12345 за 2025", self.memory)

        self.assertEqual(["12345"], intent.filters.identifier_values)

    def test_all_and_full_period_requests_keep_web_safety_limit(self) -> None:
        sql = self._build_sql("Покажи все цены за весь период")

        self.assertIn("SELECT TOP 100", sql)
        self.assertIn("FROM [DWH].[LLM].[price]", sql)

    def test_all_data_selects_all_columns_with_safe_limit_and_keeps_filters(self) -> None:
        sql = self._build_sql("Покажи все данные по ценам за март 2025")

        self.assertIn("SELECT TOP 100", sql)
        for column_name in (
            "price_date",
            "ware_id",
            "full_retail_price_kzt",
            "full_retail_price_eur",
            "full_retail_price_usd",
            "full_price_level_kzt",
            "full_price_level_usd",
            "full_price_level_eur",
            "_RANK",
            "brand",
        ):
            self.assertIn(f"[{column_name}]", sql)
        self.assertIn("[price_date] BETWEEN '2025-03-01' AND '2025-03-31'", sql)

    def test_price_history_sorts_oldest_first(self) -> None:
        sql = self._build_sql("История цены товара 12345")

        self.assertIn("[ware_id] = '12345'", sql)
        self.assertIn("ORDER BY [price_date] ASC", sql)

    def test_usd_price_request_selects_usd_price_column(self) -> None:
        sql = self._build_sql("Покажи цену USD товара 12345")

        self.assertIn("[full_retail_price_usd]", sql)
        self.assertNotIn("[full_retail_price_kzt]", sql)
        self.assertNotIn("[full_retail_price_eur]", sql)


if __name__ == "__main__":
    unittest.main()
