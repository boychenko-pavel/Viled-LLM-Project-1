from __future__ import annotations

import unittest
from types import SimpleNamespace

from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory
from sql_agent.sql_builder import SqlBuilder
import sql_agent.sql_builder as sql_builder_module


class PurchaseQueryTests(unittest.TestCase):
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

    def test_purchase_rows_use_purchase_table(self) -> None:
        question = "покажи закупочную стоимость товара 12345"
        sql = self._build_sql(question)

        self.assertIn("FROM [DWH].[LLM].[v_Purchases]", sql)
        self.assertIn("[product_id] = '12345'", sql)
        self.assertIn("[amount_kzt]", sql)
        self.assertIn("ORDER BY [purchase_date] DESC", sql)

    def test_purchase_aggregate_by_product_uses_usd_amount(self) -> None:
        sql = self._build_sql("sum purchase amount usd by product")

        self.assertIn("FROM [DWH].[LLM].[v_Purchases]", sql)
        self.assertIn("SUM([amount_usd]) AS sum_value", sql)
        self.assertIn("GROUP BY [product_id]", sql)

    def test_purchase_history_sorts_oldest_first(self) -> None:
        sql = self._build_sql("purchase history product 12345")

        self.assertIn("FROM [DWH].[LLM].[v_Purchases]", sql)
        self.assertIn("[product_id] = '12345'", sql)
        self.assertIn("ORDER BY [purchase_date] ASC", sql)

    def test_purchase_rows_by_article_use_product_dimension_filter(self) -> None:
        sql = self._build_sql("закупки артикул G062214")

        self.assertIn("FROM [DWH].[LLM].[v_Purchases] AS fact", sql)
        self.assertIn("INNER JOIN [DWH].[LLM].[dimension_product] AS dim", sql)
        self.assertIn("ON fact.[product_id] = dim.[product_id]", sql)
        self.assertIn("dim.[article] = 'G062214'", sql)

    def test_purchase_rows_by_business_unit_use_bu_filter(self) -> None:
        sql = self._build_sql("закупки направление бизнеса Fashion")

        self.assertIn("dim.[bu] = 'Fashion'", sql)


if __name__ == "__main__":
    unittest.main()
