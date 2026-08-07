from __future__ import annotations

import unittest
from types import SimpleNamespace

from sql_agent.intent_parser import IntentParser, PRODUCT_DIMENSION_COLUMNS
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

    def test_bare_product_request_defaults_to_product_dimension(self) -> None:
        sql = self._build_sql("товар 1231234")

        self.assertIn("FROM [DWH].[LLM].[dimension_product]", sql)
        self.assertIn("[product_id] = '1231234'", sql)
        self.assertIn("[article]", sql)
        self.assertNotIn("[DWH].[LLM].[price]", sql)

    def test_bare_product_id_request_defaults_to_product_dimension(self) -> None:
        sql = self._build_sql("product_id 1231234")

        self.assertIn("FROM [DWH].[LLM].[dimension_product]", sql)
        self.assertIn("[product_id] = '1231234'", sql)

    def test_sprut_code_lookup_returns_full_product_card(self) -> None:
        sql = self._build_sql("код спрута 1231234")

        self.assertIn("FROM [DWH].[LLM].[dimension_product]", sql)
        self.assertIn("[product_id] = '1231234'", sql)
        for column_name in PRODUCT_DIMENSION_COLUMNS:
            self.assertIn(f"[{column_name}]", sql)
        self.assertIn("TOP 100", sql)
        self.assertIn("ORDER BY [product_id] ASC", sql)

    def test_bare_article_lookup_returns_full_product_cards(self) -> None:
        sql = self._build_sql("артикул 19-5059/J.20_II")

        self.assertIn("FROM [DWH].[LLM].[dimension_product]", sql)
        self.assertIn("[article] = '19-5059/J.20_II'", sql)
        for column_name in PRODUCT_DIMENSION_COLUMNS:
            self.assertIn(f"[{column_name}]", sql)
        self.assertIn("TOP 100", sql)
        self.assertIn("ORDER BY [product_id] ASC", sql)

    def test_quoted_article_with_comma_is_one_filter_value(self) -> None:
        sql = self._build_sql('товар с артикулом "UW2S0491 VBP.16Q_38,5_202"')

        self.assertIn("FROM [DWH].[LLM].[dimension_product]", sql)
        self.assertIn(
            "[article] = 'UW2S0491 VBP.16Q_38,5_202'",
            sql,
        )
        self.assertNotIn("dim.[article]", sql)

    def test_dimension_text_match_word_forms_use_like_filters(self) -> None:
        cases = (
            ("список брендов которые содержат Villeroy", "[brand] LIKE '%Villeroy%'"),
            ("бренды, содержащие Villeroy", "[brand] LIKE '%Villeroy%'"),
            ("артикулы начинаются с B42298", "[article] LIKE 'B42298%'"),
            ("наименование, начинающееся на Ring", "[name] LIKE 'Ring%'"),
            ("бренд начинается Villeroy", "[brand] LIKE 'Villeroy%'"),
            ("бренды заканчиваются на Home", "[brand] LIKE '%Home'"),
            ("артикул, оканчивающийся на XL", "[article] LIKE '%XL'"),
            ("бренд заканчивается Home", "[brand] LIKE '%Home'"),
        )

        for question, expected_filter in cases:
            with self.subTest(question=question):
                sql = self._build_sql(question)
                self.assertIn(expected_filter, sql)

    def test_dimension_like_filter_escapes_sql_wildcards(self) -> None:
        sql = self._build_sql('бренды содержащие "A_100%[x]"')

        self.assertIn("[brand] LIKE '%A[_]100[%][[]x]%'", sql)

    def test_product_name_request_uses_product_dimension(self) -> None:
        sql = self._build_sql("название товара 50820")

        self.assertIn("FROM [DWH].[LLM].[dimension_product]", sql)
        self.assertIn("[product_id] = '50820'", sql)
        self.assertIn("[name]", sql)

    def test_reference_request_uses_product_dimension_without_value_markers(self) -> None:
        for question in (
            "опиши товар 50820",
            "данные о товаре 50820",
            "справочные данные товара 50820",
        ):
            with self.subTest(question=question):
                sql = self._build_sql(question)
                self.assertIn("FROM [DWH].[LLM].[dimension_product]", sql)
                self.assertIn("[product_id] = '50820'", sql)

    def test_value_marker_keeps_value_table_priority(self) -> None:
        sql = self._build_sql("данные о цене товара 50820")

        self.assertIn("FROM [DWH].[LLM].[price]", sql)
        self.assertNotIn("FROM [DWH].[LLM].[dimension_product]", sql)

    def test_product_dimension_count_by_brand(self) -> None:
        sql = self._build_sql("count products in dimension_product by brand")

        self.assertIn("FROM [DWH].[LLM].[dimension_product]", sql)
        self.assertIn("COUNT(*) AS row_count", sql)
        self.assertIn("GROUP BY [brand]", sql)

    def test_unique_brand_values_use_distinct_without_product_id(self) -> None:
        sql = self._build_sql("Покажи уникальные значения бренда")

        self.assertIn(
            "SELECT DISTINCT TOP 100 [brand] FROM [DWH].[LLM].[dimension_product]",
            sql,
        )
        self.assertNotIn("[product_id]", sql)
        self.assertIn("ORDER BY [brand] ASC", sql)

    def test_brand_list_with_relative_prefix_uses_distinct_like_filter(self) -> None:
        sql = self._build_sql("список брендов которые начинается с Villeroy")

        self.assertIn(
            "SELECT DISTINCT TOP 100 [brand] FROM [DWH].[LLM].[dimension_product]",
            sql,
        )
        self.assertIn("[brand] LIKE 'Villeroy%'", sql)
        self.assertNotIn("[brand] = 'которые начинается'", sql)
        self.assertNotIn("[product_id]", sql)
        self.assertIn("ORDER BY [brand] ASC", sql)

    def test_unique_multiple_columns_return_distinct_combinations(self) -> None:
        sql = self._build_sql(
            "Покажи уникальные значения brand и category из dimension_product"
        )

        self.assertIn("SELECT DISTINCT TOP 100 [category], [brand]", sql)
        self.assertNotIn("[product_id]", sql)

    def test_singular_unique_keyword_is_supported(self) -> None:
        sql = self._build_sql("Уникальный сезон из dimension_product")

        self.assertIn("SELECT DISTINCT TOP 100 [season]", sql)

    def test_unique_articles_for_jewelry_direction_keep_bu_filter(self) -> None:
        sql = self._build_sql("уникальные артикулы направления ювелирка")

        self.assertIn(
            "SELECT DISTINCT TOP 100 [article], [bu] FROM [DWH].[LLM].[dimension_product]",
            sql,
        )
        self.assertIn("[bu] = 'J&W'", sql)

    def test_unique_brands_by_product_keeps_product_filter_and_column(self) -> None:
        sql = self._build_sql("уникальные бренды по продукту ring")

        self.assertIn(
            "SELECT DISTINCT TOP 100 [product], [brand]",
            sql,
        )
        self.assertIn("[product] = 'ring'", sql)

    def test_default_product_dimension_supports_filter_and_grouping(self) -> None:
        sql = self._build_sql("сколько товаров бренда Gucci по категории")

        self.assertIn("FROM [DWH].[LLM].[dimension_product]", sql)
        self.assertIn("[brand] = 'Gucci'", sql)
        self.assertIn("COUNT(*) AS row_count", sql)
        self.assertIn("GROUP BY [category]", sql)

    def test_default_product_dimension_supports_column_aggregation(self) -> None:
        sql = self._build_sql("максимальный объем по бренду")

        self.assertIn("FROM [DWH].[LLM].[dimension_product]", sql)
        self.assertIn("MAX([volume]) AS max_value", sql)
        self.assertIn("GROUP BY [brand]", sql)

    def test_product_dimension_schema_uses_dwh_information_schema(self) -> None:
        sql = self._build_sql("schema for DWH.LLM.dimension_product")

        self.assertIn("FROM [DWH].INFORMATION_SCHEMA.COLUMNS", sql)
        self.assertIn("TABLE_SCHEMA = 'LLM'", sql)
        self.assertIn("TABLE_NAME = 'dimension_product'", sql)

    def test_product_cost_by_article_joins_product_dimension(self) -> None:
        sql = self._build_sql("себестоимость товар с артикулом P084503")

        self.assertIn("FROM [DWH].[LLM].[cost] AS fact", sql)
        self.assertIn("INNER JOIN product_scope AS dim", sql)
        self.assertIn("ON fact.[product_id] = dim.[product_id]", sql)
        self.assertIn("dim.[article] = 'P084503'", sql)
        self.assertIn("ORDER BY fact.[date] DESC", sql)

    def test_stock_balance_by_brand_joins_product_dimension(self) -> None:
        sql = self._build_sql("остаток по бренду Gucci")

        self.assertIn("FROM [DWH].[LLM].[stock] AS fact", sql)
        self.assertIn("INNER JOIN product_scope AS dim", sql)
        self.assertIn("ON fact.[product_id] = dim.[product_id]", sql)
        self.assertIn("dim.[brand] = 'Gucci'", sql)
        self.assertIn("SUM(fact.[quantity]) AS stock_quantity_end", sql)

    def test_stock_balance_by_collection_joins_product_dimension(self) -> None:
        sql = self._build_sql("остаток по коллекции SS25")

        self.assertIn("FROM [DWH].[LLM].[stock] AS fact", sql)
        self.assertIn("dim.[collection_jw] = 'SS25'", sql)


if __name__ == "__main__":
    unittest.main()
