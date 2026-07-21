from __future__ import annotations

import unittest
from types import SimpleNamespace

from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory
from sql_agent.sql_builder import SqlBuilder
import sql_agent.sql_builder as sql_builder_module


class ProductDimensionQueryTests(unittest.TestCase):
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

    def test_product_dimension_rows_use_dimension_table(self) -> None:
        sql = self._build_sql("show product attributes from dimension_product for product_id 12345")

        self.assertIn("FROM [DWH].[LLM].[dimension_product]", sql)
        self.assertIn("[product_id] = '12345'", sql)
        self.assertIn("[article]", sql)
        self.assertIn("[brand]", sql)
        self.assertIn("ORDER BY [product_id] ASC", sql)

    def test_product_dimension_count_by_brand(self) -> None:
        sql = self._build_sql("count products in dimension_product by brand")

        self.assertIn("FROM [DWH].[LLM].[dimension_product]", sql)
        self.assertIn("COUNT(*) AS row_count", sql)
        self.assertIn("GROUP BY [brand]", sql)

    def test_product_dimension_schema_uses_dwh_information_schema(self) -> None:
        sql = self._build_sql("schema for DWH.LLM.dimension_product")

        self.assertIn("FROM [DWH].INFORMATION_SCHEMA.COLUMNS", sql)
        self.assertIn("TABLE_SCHEMA = 'LLM'", sql)
        self.assertIn("TABLE_NAME = 'dimension_product'", sql)

    def test_product_cost_by_article_joins_product_dimension(self) -> None:
        sql = self._build_sql("себестоимость товар с артикулом P084503")

        self.assertIn("FROM [DWH].[LLM].[cost] AS fact", sql)
        self.assertIn("INNER JOIN [DWH].[LLM].[dimension_product] AS dim", sql)
        self.assertIn("ON fact.[product_id] = dim.[product_id]", sql)
        self.assertIn("dim.[article] = 'P084503'", sql)
        self.assertIn("ORDER BY fact.[date] DESC", sql)

    def test_stock_balance_by_brand_joins_product_dimension(self) -> None:
        sql = self._build_sql("остаток по бренду Gucci")

        self.assertIn("FROM [DWH].[LLM].[stock] AS fact", sql)
        self.assertIn("INNER JOIN [DWH].[LLM].[dimension_product] AS dim", sql)
        self.assertIn("ON fact.[product_id] = dim.[product_id]", sql)
        self.assertIn("dim.[brand] = 'Gucci'", sql)
        self.assertIn("SUM(fact.[quantity]) AS stock_quantity_end", sql)

    def test_stock_balance_by_collection_joins_product_dimension(self) -> None:
        sql = self._build_sql("остаток по коллекции SS25")

        self.assertIn("FROM [DWH].[LLM].[stock] AS fact", sql)
        self.assertIn("dim.[collection_jw] = 'SS25'", sql)


if __name__ == "__main__":
    unittest.main()
