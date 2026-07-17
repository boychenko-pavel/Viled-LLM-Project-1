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


if __name__ == "__main__":
    unittest.main()
