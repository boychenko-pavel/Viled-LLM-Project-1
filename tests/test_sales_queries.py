from __future__ import annotations

import unittest
from types import SimpleNamespace

from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory
from sql_agent.sql_builder import SqlBuilder
import sql_agent.sql_builder as sql_builder_module


class SalesQueryTests(unittest.TestCase):
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

    def test_sales_quantity_request_sums_quantity_not_rows(self) -> None:
        sql = self._build_sql("количество продажи январь 2026")

        self.assertIn("SUM([quantity]) AS sum_value", sql)
        self.assertNotIn("COUNT(*) AS row_count", sql)
        self.assertIn("FROM [LLM].[sales]", sql)
        self.assertIn("[sale_date] BETWEEN '2026-01-01' AND '2026-01-31'", sql)


    def test_sales_by_bu_joins_product_dimension(self) -> None:
        sql = self._build_sql("продажи товара направления J&W за 01.06.2026")

        self.assertIn("FROM [LLM].[sales] AS fact", sql)
        self.assertIn("INNER JOIN [DWH].[LLM].[dimension_product] AS dim", sql)
        self.assertIn("ON fact.[product_id] = dim.[product_id]", sql)
        self.assertIn("dim.[bu] = 'J&W'", sql)
        self.assertIn("fact.[sale_date] = '2026-06-01'", sql)

    def test_sales_by_jewelry_direction_uses_jw_bu_not_period_text(self) -> None:
        sql = self._build_sql("продажи ювелирного направления за июль 2026")

        self.assertIn("FROM [LLM].[sales] AS fact", sql)
        self.assertIn("INNER JOIN [DWH].[LLM].[dimension_product] AS dim", sql)
        self.assertIn("dim.[bu] = 'J&W'", sql)
        self.assertIn("fact.[sale_date] BETWEEN '2026-07-01' AND '2026-07-31'", sql)
        self.assertNotIn("dim.[bu] = 'за июль 2026'", sql)

    def test_sales_by_jw_direction_without_ampersand_uses_jw_bu(self) -> None:
        sql = self._build_sql("продажи направления JW за июль 2026")

        self.assertIn("dim.[bu] = 'J&W'", sql)
        self.assertIn("fact.[sale_date] BETWEEN '2026-07-01' AND '2026-07-31'", sql)


    def test_all_sales_by_article_joins_product_dimension(self) -> None:
        sql = self._build_sql("все данные продажи артикул G062214")

        self.assertIn("FROM [LLM].[sales] AS fact", sql)
        self.assertIn("INNER JOIN [DWH].[LLM].[dimension_product] AS dim", sql)
        self.assertIn("ON fact.[product_id] = dim.[product_id]", sql)
        self.assertIn("dim.[article] = 'G062214'", sql)
        self.assertIn("fact.[sale_date]", sql)
        self.assertNotIn("TOP ", sql)


if __name__ == "__main__":
    unittest.main()
