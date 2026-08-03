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
        self.rows: list[tuple] = []

        def capture_sql(_engine, sql: str):
            self.sql = sql
            return self.rows

        sql_builder_module.run_sql_query = capture_sql

    def tearDown(self) -> None:
        sql_builder_module.run_sql_query = self._original_run_sql_query

    def _build_sql(self, question: str) -> str:
        intent = self.parser.parse(question, self.memory)
        self.builder.execute(SimpleNamespace(_engine=object()), intent)
        self.assertIsNotNone(self.sql)
        return self.sql or ""

    def _execute(self, question: str) -> str:
        intent = self.parser.parse(question, self.memory)
        return self.builder.execute(SimpleNamespace(_engine=object()), intent)

    def test_short_sales_request_returns_enriched_rows_and_full_totals(self) -> None:
        sql = self._build_sql("продажи товара 1231235")

        expected_columns = (
            "fact.[sale_date], fact.[document_number], fact.[product_id], "
            "dim.[brand], dim.[article], dim.[individual_number], dim.[name], "
            "fact.[quantity], fact.[full_price], fact.[price], fact.[amount], "
            "fact.[loan], fact.[cash], fact.[card], fact.[certificate], "
            "fact.[bonus], fact.[discount], fact.[channel], "
            "fact.[payment_method], fact.[partner_id], fact.[customer_status]"
        )
        self.assertIn(f"SELECT TOP 100 {expected_columns}", sql)
        self.assertIn(
            "INNER JOIN [DWH].[LLM].[dimension_product] AS dim "
            "ON fact.[product_id] = dim.[product_id]",
            sql,
        )
        self.assertIn("WHERE fact.[product_id] = '1231235'", sql)
        for column_name in (
            "quantity",
            "full_price",
            "amount",
            "loan",
            "cash",
            "card",
            "certificate",
            "bonus",
            "discount",
        ):
            self.assertIn(
                f"SUM(fact.[{column_name}]) OVER () AS [__total_{column_name}]",
                sql,
            )

    def test_sales_result_has_one_totals_row(self) -> None:
        self.rows = [
            (
                "2026-07-01",
                "DOC-1",
                "1231235",
                "Brand",
                "ART-1",
                "IND-1",
                "Product",
                2,
                1200,
                1000,
                2000,
                0,
                500,
                1500,
                0,
                0,
                200,
                "retail",
                "mixed",
                "PARTNER-1",
                "regular",
                5,
                2500,
                5000,
                0,
                1000,
                4000,
                0,
                0,
                500,
            ),
        ]

        response = self._execute("продажи товара 1231235")

        self.assertIn(
            ",,ИТОГО,,,,,5,2500,,5000,0,1000,4000,0,0,500,,,,",
            response,
        )

    def test_sales_dimension_filter_cte_includes_enrichment_columns(self) -> None:
        sql = self._build_sql("все продажи артикула G062214")

        self.assertIn(
            "product_scope AS (SELECT dim.[product_id], dim.[brand], "
            "dim.[article], dim.[individual_number], dim.[name]",
            sql,
        )

    def test_sales_quantity_request_sums_quantity_not_rows(self) -> None:
        sql = self._build_sql("количество продажи январь 2026")

        self.assertIn("SUM([quantity]) AS total_quantity", sql)
        self.assertNotIn("COUNT(*) AS row_count", sql)
        self.assertIn("FROM [LLM].[sales]", sql)
        self.assertIn("[sale_date] BETWEEN '2026-01-01' AND '2026-01-31'", sql)
        for column_name in (
            "full_price",
            "amount",
            "loan",
            "cash",
            "card",
            "certificate",
            "bonus",
            "discount",
        ):
            self.assertIn(
                f"SUM([{column_name}]) AS [total_{column_name}]",
                sql,
            )

    def test_sales_amount_with_product_word_is_not_grouped(self) -> None:
        sql = self._build_sql("сумма продажа товара за март 2026")

        self.assertIn("SELECT SUM([amount]) AS total_amount", sql)
        self.assertNotIn("[product_id]", sql)
        self.assertNotIn("GROUP BY", sql)
        self.assertIn("[sale_date] BETWEEN '2026-03-01' AND '2026-03-31'", sql)

    def test_sales_amount_explicitly_by_products_is_grouped(self) -> None:
        sql = self._build_sql("сумма продаж по товарам за март 2026")

        self.assertIn("[product_id], SUM([amount]) AS total_amount", sql)
        self.assertIn("SUM([quantity]) AS [total_quantity]", sql)
        for column_name in (
            "full_price",
            "loan",
            "cash",
            "card",
            "certificate",
            "bonus",
            "discount",
        ):
            self.assertIn(f"SUM([{column_name}]) AS [total_{column_name}]", sql)
        self.assertIn("__grand_total_amount", sql)
        self.assertIn("GROUP BY [product_id]", sql)

    def test_hyphenated_top_products_by_sales_amount_is_ranked(self) -> None:
        sql = self._build_sql(
            "Топ-10 товаров бренда Cartier по сумме продаж в KZT за март 2026"
        )

        self.assertIn(
            "SELECT TOP 10 fact.[product_id], SUM(fact.[amount]) AS total_amount",
            sql,
        )
        self.assertIn("dim.[brand] = 'Cartier'", sql)
        self.assertIn("GROUP BY fact.[product_id]", sql)
        self.assertIn("ORDER BY total_amount DESC, fact.[product_id]", sql)

    def test_top_products_total_row_sums_only_returned_top_rows(self) -> None:
        self.rows = [
            ("P-1", 1000, 2, 1200, 0, 500, 500, 0, 0, 200),
            ("P-2", 700, 1, 800, 0, 200, 500, 0, 0, 100),
        ]

        response = self._execute(
            "Топ-2 товаров бренда Cartier по сумме продаж в KZT за март 2026"
        )

        self.assertIn("ИТОГО,1700,3,2000,0,700,1000,0,0,300", response)

    def test_grouped_sales_result_has_grand_total_row(self) -> None:
        self.rows = [
            ("Cartier", 1000, 2, 1200, 0, 500, 500, 0, 0, 200, 5, 3200, 3000, 0, 1000, 2000, 0, 0, 500),
            ("Chopard", 2000, 3, 2000, 0, 500, 1500, 0, 0, 300, 5, 3200, 3000, 0, 1000, 2000, 0, 0, 500),
        ]

        response = self._execute(
            "сумма продаж ювелирки за апрель 2026 группировка по брендам"
        )

        self.assertIn("ИТОГО,3000,5,3200,0,1000,2000,0,0,500", response)

    def test_exact_saks_jewelry_request_has_brand_totals(self) -> None:
        self.rows = [
            ("Cartier", 3000, 2, 3200, 0, 1000, 2000, 0, 0, 500, 2, 3200, 3000, 0, 1000, 2000, 0, 0, 500),
        ]

        response = self._execute(
            "продажи БУТИКА сакс за вчера по направлению ювелирка "
            "группировка по брендам"
        )

        self.assertIn("dim.[bu] = 'J&W'", self.sql or "")
        self.assertIn("div.[division] = 'Saks Fifth Avenue'", self.sql or "")
        self.assertIn("GROUP BY dim.[brand]", self.sql or "")
        self.assertIn("ИТОГО,3000,2,3200,0,1000,2000,0,0,500", response)


    def test_sales_by_bu_joins_product_dimension(self) -> None:
        sql = self._build_sql("продажи товара направления J&W за 01.06.2026")

        self.assertIn("FROM [LLM].[sales] AS fact", sql)
        self.assertIn("INNER JOIN product_scope AS dim", sql)
        self.assertIn("ON fact.[product_id] = dim.[product_id]", sql)
        self.assertIn("dim.[bu] = 'J&W'", sql)
        self.assertIn("fact.[sale_date] = '2026-06-01'", sql)

    def test_sales_by_jewelry_direction_uses_jw_bu_not_period_text(self) -> None:
        sql = self._build_sql("продажи ювелирного направления за июль 2026")

        self.assertIn("FROM [LLM].[sales] AS fact", sql)
        self.assertIn("INNER JOIN product_scope AS dim", sql)
        self.assertIn("dim.[bu] = 'J&W'", sql)
        self.assertIn("fact.[sale_date] BETWEEN '2026-07-01' AND '2026-07-31'", sql)
        self.assertNotIn("dim.[bu] = 'за июль 2026'", sql)

    def test_sales_by_jw_direction_without_ampersand_uses_jw_bu(self) -> None:
        sql = self._build_sql("продажи направления JW за июль 2026")

        self.assertIn("dim.[bu] = 'J&W'", sql)
        self.assertIn("fact.[sale_date] BETWEEN '2026-07-01' AND '2026-07-31'", sql)

    def test_sales_amount_can_be_grouped_by_dimension_brand(self) -> None:
        sql = self._build_sql(
            "сумма продаж ювелирка апрель 2026 группировка по брендам"
        )

        self.assertIn("SELECT TOP 100 dim.[brand], SUM(fact.[amount]) AS total_amount", sql)
        self.assertIn("INNER JOIN product_scope AS dim", sql)
        self.assertIn("fact.[sale_date] BETWEEN '2026-04-01' AND '2026-04-30'", sql)
        self.assertIn("dim.[bu] = 'J&W'", sql)
        self.assertIn("GROUP BY dim.[brand]", sql)
        self.assertNotIn("dim.[brand] =", sql)


    def test_all_sales_by_article_joins_product_dimension(self) -> None:
        sql = self._build_sql("все данные продажи артикул G062214")

        self.assertIn("FROM [LLM].[sales] AS fact", sql)
        self.assertIn("INNER JOIN product_scope AS dim", sql)
        self.assertIn("ON fact.[product_id] = dim.[product_id]", sql)
        self.assertIn("dim.[article] = 'G062214'", sql)
        self.assertIn("fact.[sale_date]", sql)
        self.assertIn("SELECT TOP 100", sql)

    def test_sales_by_multiple_articles_use_in_filter(self) -> None:
        sql = self._build_sql("продажи товара артикул 2807742, 2807743")

        self.assertIn("FROM [LLM].[sales] AS fact", sql)
        self.assertIn("INNER JOIN product_scope AS dim", sql)
        self.assertIn(
            "dim.[article] IN ('2807742', '2807743')",
            sql,
        )

    def test_unique_sales_product_ids_select_only_requested_column(self) -> None:
        sql = self._build_sql("Покажи уникальные product_id из sales")

        self.assertIn("SELECT DISTINCT TOP 100 [product_id] FROM [LLM].[sales]", sql)
        self.assertNotIn("[sale_date]", sql)

    def test_unique_sales_brands_join_product_dimension(self) -> None:
        sql = self._build_sql("Покажи 10 уникальных брендов в продажах")

        self.assertIn("SELECT DISTINCT TOP 10 dim.[brand]", sql)
        self.assertIn("FROM [LLM].[sales] AS fact", sql)
        self.assertIn("INNER JOIN [DWH].[LLM].[dimension_product] AS dim", sql)
        self.assertNotIn("dim.[brand] =", sql)


if __name__ == "__main__":
    unittest.main()
