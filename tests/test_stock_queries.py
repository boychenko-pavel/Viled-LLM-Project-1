from __future__ import annotations

import unittest
from types import SimpleNamespace

from sql_agent.intent_parser import IntentParser, STOCK_COLUMNS
from sql_agent.memory import SqlAgentMemory
from sql_agent.sql_builder import SqlBuilder
import sql_agent.sql_builder as sql_builder_module


class StockQueryTests(unittest.TestCase):
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

    def test_stock_movements_use_stock_table(self) -> None:
        sql = self._build_sql("Покажи перемещение товаров по товару 12345")

        self.assertIn("FROM [DWH].[LLM].[stock]", sql)
        for column_name in STOCK_COLUMNS:
            self.assertIn(f"[{column_name}]", sql)
        self.assertIn("[product_id] = '12345'", sql)
        self.assertIn("[recorder_type] = 'Перемещение товаров'", sql)
        self.assertIn("[document_id]", sql)
        self.assertIn("ORDER BY [date] DESC", sql)

    def test_stock_balance_start_uses_exclusive_start_date(self) -> None:
        sql = self._build_sql("Остаток товара 12345 на начало периода март 2025")

        self.assertIn("FROM [DWH].[LLM].[stock]", sql)
        self.assertIn("SUM([quantity]) AS stock_quantity_start", sql)
        self.assertIn("[date] < CONVERT(datetime2, '20250301', 112)", sql)
        self.assertIn("[product_id] = '12345'", sql)

    def test_current_stock_balance_without_date_does_not_add_synthetic_date(self) -> None:
        sql = self._build_sql("остатки товара 1231230")

        self.assertIn("FROM [DWH].[LLM].[stock]", sql)
        self.assertIn("SUM([quantity]) AS stock_quantity_end", sql)
        self.assertIn("[product_id] = '1231230'", sql)
        self.assertNotIn("9999-12-31", sql)
        self.assertNotIn("[date] <=", sql)

    def test_short_stock_balance_treats_number_as_sprut_code(self) -> None:
        sql = self._build_sql("остаток 924293")

        self.assertIn("FROM [DWH].[LLM].[stock]", sql)
        self.assertIn("SELECT TOP 100 [warehouse_id],", sql)
        self.assertIn("SUM([quantity]) AS stock_quantity_end", sql)
        self.assertIn("[product_id] = '924293'", sql)
        self.assertIn("GROUP BY [warehouse_id]", sql)

    def test_stock_balance_by_article_can_be_grouped_by_sprut_code(self) -> None:
        sql = self._build_sql("остатки товара артикул 69683886 разбивка по коду спрута")

        self.assertIn("FROM [DWH].[LLM].[stock] AS fact", sql)
        self.assertIn("dim.[article] = '69683886'", sql)
        self.assertNotIn("69683886 разбивка", sql)
        self.assertIn("SELECT TOP 100 fact.[product_id], SUM(fact.[quantity]) AS stock_quantity_end", sql)
        self.assertIn("GROUP BY fact.[product_id]", sql)

    def test_stock_balance_with_sprut_code_filters_product_id(self) -> None:
        sql = self._build_sql(
            "остаток товара с кодом спрута 121230"
        )

        self.assertIn("FROM [DWH].[LLM].[stock]", sql)
        self.assertIn("SUM([quantity]) AS stock_quantity_end", sql)
        self.assertIn("[product_id] = '121230'", sql)

    def test_stock_balance_on_date_uses_inclusive_date_filter(self) -> None:
        sql = self._build_sql(
            "остаток товара с кодом спрута 1231230 на 20.01.2022"
        )

        self.assertIn("FROM [DWH].[LLM].[stock]", sql)
        self.assertIn("SUM([quantity]) AS stock_quantity_end", sql)
        self.assertIn("[product_id] = '1231230'", sql)
        self.assertIn(
            "[date] < DATEADD(day, 1, CONVERT(datetime2, '20220120', 112))",
            sql,
        )
        self.assertNotIn("20220121", sql)

    def test_stock_balance_on_date_with_multiple_products_uses_inclusive_date_filter(self) -> None:
        sql = self._build_sql(
            "остатки товаров 1231230, 1231231, 1231232 на 01.01.2023"
        )

        self.assertIn("FROM [DWH].[LLM].[stock]", sql)
        self.assertIn("SUM([quantity]) AS stock_quantity_end", sql)
        self.assertIn("SELECT TOP 100 [product_id], SUM([quantity]) AS stock_quantity_end", sql)
        self.assertIn("[product_id] IN ('1231230', '1231231', '1231232')", sql)
        self.assertIn(
            "[date] < DATEADD(day, 1, CONVERT(datetime2, '20230101', 112))",
            sql,
        )
        self.assertIn("GROUP BY [product_id]", sql)
        self.assertNotIn("20230102", sql)

    def test_stock_balance_period_uses_start_and_end_rules(self) -> None:
        sql = self._build_sql("Остаток на начало и конец периода за март 2025 по складам")

        self.assertIn("SUM(CASE WHEN [date] < CONVERT(datetime2, '20250301', 112)", sql)
        self.assertIn(
            "SUM(CASE WHEN [date] < DATEADD(day, 1, "
            "CONVERT(datetime2, '20250331', 112))",
            sql,
        )
        self.assertIn("GROUP BY [warehouse_id]", sql)


if __name__ == "__main__":
    unittest.main()
