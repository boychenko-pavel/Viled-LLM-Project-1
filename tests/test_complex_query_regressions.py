from __future__ import annotations

import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory
from sql_agent.sql_builder import SqlBuilder


class ComplexQueryRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = IntentParser()
        self.builder = SqlBuilder()
        self.memory = SqlAgentMemory()

    def assertGeneratedSql(self, question: str, expected_sql: str) -> None:
        captured_sql: list[str] = []

        def capture_sql(_engine, sql: str):
            captured_sql.append(sql)
            return []

        intent = self.parser.parse(question, self.memory)
        with patch("sql_agent.sql_builder.run_sql_query", side_effect=capture_sql):
            self.builder.execute(SimpleNamespace(_engine=object()), intent)

        self.assertEqual(1, len(captured_sql))
        self.assertEqual(
            re.sub(r"\s+", "", expected_sql),
            re.sub(r"\s+", "", captured_sql[0]),
        )

    def test_latest_price_by_article_only_for_products_in_stock(self) -> None:
        self.assertGeneratedSql(
            "последняя цена артикул 69683886 только в наличии",
            """
            WITH latest_price AS (
                SELECT
                    fact.[price_date] AS [price_date],
                    fact.[ware_id] AS [ware_id],
                    fact.[full_retail_price_kzt] AS [full_retail_price_kzt],
                    fact.[full_retail_price_eur] AS [full_retail_price_eur],
                    fact.[full_retail_price_usd] AS [full_retail_price_usd],
                    ROW_NUMBER() OVER (PARTITION BY fact.[ware_id] ORDER BY fact.[price_date] DESC) AS rn
                FROM [DWH].[LLM].[price] AS fact INNER JOIN [DWH].[LLM].[dimension_product] AS dim ON fact.[ware_id] = dim.[product_id]
                WHERE
                    dim.[article] = '69683886' AND
                    EXISTS (
                    SELECT 1
                    FROM [DWH].[LLM].[stock] AS stock_availability
                    WHERE stock_availability.[product_id] = fact.[ware_id]
                    GROUP BY stock_availability.[product_id]
                    HAVING SUM(stock_availability.[quantity]) > 0))
            SELECT
                [price_date],
                [ware_id],
                [full_retail_price_kzt],
                [full_retail_price_eur],
                [full_retail_price_usd]
            FROM latest_price
            WHERE rn = 1
            ORDER BY [price_date] DESC, [ware_id]
            """,
        )

    def test_stock_by_article_grouped_by_sprut_code(self) -> None:
        self.assertGeneratedSql(
            "остатки товара артикул 69683886 разбивка по коду спрута",
            """
            SELECT
                fact.[product_id],
                SUM(fact.[quantity]) AS stock_quantity_end
            FROM [DWH].[LLM].[stock] AS fact INNER JOIN [DWH].[LLM].[dimension_product] AS dim ON fact.[product_id] = dim.[product_id]
            WHERE dim.[article] = '69683886'
            GROUP BY fact.[product_id]
            ORDER BY fact.[product_id]
            """,
        )


if __name__ == "__main__":
    unittest.main()
