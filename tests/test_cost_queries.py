from __future__ import annotations

import unittest
from types import SimpleNamespace

from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory
from sql_agent.sql_builder import SqlBuilder
import sql_agent.sql_builder as sql_builder_module


class CostQueryTests(unittest.TestCase):
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

    def test_cost_rows_use_cost_table_and_product_id(self) -> None:
        sql = self._build_sql("\u041f\u043e\u043a\u0430\u0436\u0438 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c \u0442\u043e\u0432\u0430\u0440\u0430 12345")

        self.assertIn("FROM [DWH].[LLM].[cost]", sql)
        self.assertIn("[product_id] = '12345'", sql)
        self.assertIn("ORDER BY [date] DESC", sql)
        self.assertNotIn("TOP", sql)
        self.assertEqual(
            [
                "date",
                "product_id",
                "op_type",
                "quantity",
                "cost",
                "cost_per_unit",
                "qnt_sum",
                "cost_sum",
            ],
            self.parser.parse(
                "\u043a\u0430\u043a\u0430\u044f \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c \u0442\u043e\u0432\u0430\u0440\u0430 12345",
                self.memory,
            ).requested_columns,
        )

    def test_cost_history_sorts_oldest_first(self) -> None:
        sql = self._build_sql("\u041f\u043e\u043a\u0430\u0436\u0438 \u0438\u0441\u0442\u043e\u0440\u0438\u044e \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438 \u0442\u043e\u0432\u0430\u0440\u0430 12345")

        self.assertIn("[product_id] = '12345'", sql)
        self.assertIn("ORDER BY [date] ASC", sql)

    def test_operation_cost_can_be_aggregated_by_product(self) -> None:
        sql = self._build_sql("\u0421\u0443\u043c\u043c\u0430 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438 \u043e\u043f\u0435\u0440\u0430\u0446\u0438\u0439 \u043f\u043e \u0442\u043e\u0432\u0430\u0440\u0430\u043c")

        self.assertIn("SUM([cost])", sql)
        self.assertIn("GROUP BY [product_id]", sql)

    def test_running_cost_balance_is_not_summed(self) -> None:
        sql = self._build_sql("\u041f\u043e\u043a\u0430\u0436\u0438 \u0441\u0443\u043c\u043c\u0443 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438 \u043e\u0441\u0442\u0430\u0442\u043a\u0430")

        self.assertNotIn("SUM([cost_sum])", sql)
        self.assertIn("[cost_sum]", sql)


if __name__ == "__main__":
    unittest.main()
