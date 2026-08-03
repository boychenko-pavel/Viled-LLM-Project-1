from __future__ import annotations

import unittest
from types import SimpleNamespace

from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory
from sql_agent.sql_builder import SqlBuilder
import sql_agent.sql_builder as sql_builder_module


class DivisionQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = IntentParser()
        self.builder = SqlBuilder()
        self.memory = SqlAgentMemory()
        self.original_run_sql_query = sql_builder_module.run_sql_query
        self.sql = ""

        def capture_sql(_engine, sql: str):
            self.sql = sql
            return []

        sql_builder_module.run_sql_query = capture_sql

    def tearDown(self) -> None:
        sql_builder_module.run_sql_query = self.original_run_sql_query

    def build_sql(self, question: str) -> str:
        intent = self.parser.parse(question, self.memory)
        self.builder.execute(SimpleNamespace(_engine=object()), intent)
        return self.sql

    def test_sales_can_be_grouped_by_city(self) -> None:
        sql = self.build_sql("сумма продаж за июнь 2026 в разрезе городов")

        self.assertIn("INNER JOIN [DWH].[LLM].[division] AS div", sql)
        self.assertIn("ON fact.[division_id] = div.[id]", sql)
        self.assertIn("SELECT TOP 100 div.[city], SUM(fact.[amount]) AS total_amount", sql)
        self.assertIn("GROUP BY div.[city]", sql)

    def test_sales_can_be_filtered_by_store(self) -> None:
        sql = self.build_sql("продажи магазин Viled.kz за июнь 2026")

        self.assertIn("INNER JOIN [DWH].[LLM].[division] AS div", sql)
        self.assertIn("div.[division] = 'Viled.kz'", sql)

    def test_sales_can_be_filtered_by_division(self) -> None:
        sql = self.build_sql("продажи подразделение Viled.kz за июнь 2026")

        self.assertIn("INNER JOIN [DWH].[LLM].[division] AS div", sql)
        self.assertIn("div.[division] = 'Viled.kz'", sql)

    def test_sales_can_be_filtered_by_division_dative_form(self) -> None:
        sql = self.build_sql("продажи по подразделению Viled.kz за июнь 2026")

        self.assertIn("INNER JOIN [DWH].[LLM].[division] AS div", sql)
        self.assertIn("div.[division] = 'Viled.kz'", sql)

    def test_sales_by_named_boutique_treats_name_as_filter(self) -> None:
        sql = self.build_sql("продажи товара по бутику Saks Fifth Avenue за вчера")

        self.assertIn("INNER JOIN [DWH].[LLM].[division] AS div", sql)
        self.assertIn("div.[division] = 'Saks Fifth Avenue'", sql)
        self.assertNotIn("GROUP BY div.[division]", sql)

    def test_jewelry_sales_in_boutique_uses_only_division_store_filter(self) -> None:
        sql = self.build_sql("продажи ювелирки в бутике Saks Fifth Avenue за март 2026")

        self.assertIn("INNER JOIN product_scope AS dim", sql)
        self.assertIn("INNER JOIN [DWH].[LLM].[division] AS div", sql)
        self.assertIn("dim.[bu] = 'J&W'", sql)
        self.assertIn("div.[division] = 'Saks Fifth Avenue'", sql)
        self.assertNotIn("dim.[store_jw]", sql)
        self.assertIn("fact.[sale_date]", sql)
        self.assertIn("fact.[document_number]", sql)
        self.assertIn("fact.[product_id]", sql)
        self.assertIn("fact.[amount]", sql)
        self.assertNotIn("SELECT TOP 100 fact.[amount] FROM", sql)

    def test_jewelry_sales_in_boutique_can_be_grouped_by_brand(self) -> None:
        sql = self.build_sql(
            "продажи ювелирки в бутике Saks Fifth Avenue за май 2025 "
            "группировка по брендам"
        )

        self.assertIn("SELECT TOP 100 dim.[brand], SUM(fact.[amount]) AS total_amount", sql)
        self.assertIn("INNER JOIN product_scope AS dim", sql)
        self.assertIn("INNER JOIN [DWH].[LLM].[division] AS div", sql)
        self.assertIn("fact.[sale_date] BETWEEN '2025-05-01' AND '2025-05-31'", sql)
        self.assertIn("dim.[bu] = 'J&W'", sql)
        self.assertIn("div.[division] = 'Saks Fifth Avenue'", sql)
        self.assertIn("GROUP BY dim.[brand]", sql)

    def test_short_sales_by_brand_phrase_is_grouping_not_brand_filter(self) -> None:
        sql = self.build_sql("продажи бутик сакс за вчера по брендам")

        self.assertIn("SELECT TOP 100 dim.[brand], SUM(fact.[amount]) AS total_amount", sql)
        self.assertIn("div.[division] = 'Saks Fifth Avenue'", sql)
        self.assertIn("GROUP BY dim.[brand]", sql)
        self.assertNotIn("dim.[brand] =", sql)

    def test_sales_can_be_grouped_by_multiple_product_dimensions(self) -> None:
        sql = self.build_sql(
            "все данные продажи товара по бутику Saks Fifth Avenue за март 2026 "
            "группировка по брендам и направлению бизнеса"
        )

        self.assertIn(
            "SELECT TOP 100 dim.[brand], dim.[bu], SUM(fact.[amount]) AS total_amount",
            sql,
        )
        self.assertIn("INNER JOIN [DWH].[LLM].[dimension_product] AS dim", sql)
        self.assertIn("INNER JOIN [DWH].[LLM].[division] AS div", sql)
        self.assertIn(
            "fact.[sale_date] BETWEEN '2026-03-01' AND '2026-03-31'",
            sql,
        )
        self.assertIn("div.[division] = 'Saks Fifth Avenue'", sql)
        self.assertIn("GROUP BY dim.[brand], dim.[bu]", sql)
        self.assertIn("ORDER BY dim.[brand], dim.[bu]", sql)

    def test_sales_can_be_filtered_by_city(self) -> None:
        sql = self.build_sql("сумма продаж город Алматы за июнь 2026")

        self.assertIn("div.[city] = 'Алматы'", sql)

    def test_direct_division_table_query(self) -> None:
        sql = self.build_sql("покажи все колонки таблицы DWH.LLM.division")

        self.assertIn("FROM [DWH].[LLM].[division]", sql)
        self.assertIn("[id]", sql)
        self.assertIn("[division]", sql)
        self.assertIn("[city]", sql)


    def test_direct_division_query_can_be_filtered_by_city(self) -> None:
        sql = self.build_sql("все бутики город Алматы")

        self.assertIn("FROM [DWH].[LLM].[division]", sql)
        self.assertIn("[city] = 'Алматы'", sql)


if __name__ == "__main__":
    unittest.main()
