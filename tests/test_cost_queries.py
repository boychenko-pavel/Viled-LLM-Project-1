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
        sql = self._build_sql("Покажи себестоимость товара 12345")

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
                "какая себестоимость товара 12345",
                self.memory,
            ).requested_columns,
        )

    def test_cost_rows_filter_multiple_product_ids(self) -> None:
        sql = self._build_sql(
            "себестоимость товаров 1231230,1231231,1231232"
        )

        self.assertIn("FROM [DWH].[LLM].[cost]", sql)
        self.assertIn("[product_id] IN ('1231230', '1231231', '1231232')", sql)
        self.assertIn("ORDER BY [date] DESC", sql)
        self.assertNotIn("TOP", sql)

    def test_all_cost_data_filters_by_sprut_code(self) -> None:
        sql = self._build_sql("все данные себестоимость код спрута 2353446")

        self.assertIn("FROM [DWH].[LLM].[cost]", sql)
        self.assertIn("[product_id] = '2353446'", sql)
        self.assertIn("ORDER BY [date] DESC", sql)

    def test_cost_typo_still_uses_cost_table_and_product_id(self) -> None:
        sql = self._build_sql("себестомость товара 1231237")

        self.assertIn("FROM [DWH].[LLM].[cost]", sql)
        self.assertIn("[product_id] = '1231237'", sql)
        self.assertNotIn("FROM [DWH].[LLM].[price]", sql)
        self.assertNotIn("[ware_id]", sql)

    def test_cost_history_sorts_oldest_first(self) -> None:
        sql = self._build_sql("Покажи историю себестоимости товара 12345")

        self.assertIn("[product_id] = '12345'", sql)
        self.assertIn("ORDER BY [date] ASC", sql)

    def test_operation_cost_can_be_aggregated_by_product(self) -> None:
        sql = self._build_sql("Сумма себестоимости операций по товарам")

        self.assertIn("SUM([cost])", sql)
        self.assertIn("GROUP BY [product_id]", sql)

    def test_running_cost_balance_is_not_summed(self) -> None:
        sql = self._build_sql("Покажи сумму себестоимости остатка")

        self.assertNotIn("SUM([cost_sum])", sql)
        self.assertIn("[cost_sum]", sql)


if __name__ == "__main__":
    unittest.main()
