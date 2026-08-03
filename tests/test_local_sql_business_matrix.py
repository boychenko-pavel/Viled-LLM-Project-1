from __future__ import annotations

import re
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import ANY, patch

import pytest

from sql_agent.intent_parser import IntentParser, PRODUCT_DIMENSION_COLUMNS
from sql_agent.memory import SqlAgentMemory
from sql_agent.query_utils import validate_readonly_select_sql
from sql_agent.sql_builder import SqlBuilder


@dataclass(frozen=True)
class BusinessCase:
    id: str
    question: str
    kind: str = "sql"
    operation: str | None = None
    domain: str | None = None
    required: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    expected_message: str | None = None


def sql_case(
    case_id: str,
    question: str,
    operation: str,
    domain: str,
    *required: str,
    forbidden: tuple[str, ...] = (),
) -> BusinessCase:
    return BusinessCase(
        id=case_id,
        question=question,
        operation=operation,
        domain=domain,
        required=required,
        forbidden=forbidden,
    )


def clarification_case(
    case_id: str,
    question: str,
    expected_message: str,
) -> BusinessCase:
    return BusinessCase(
        id=case_id,
        question=question,
        kind="clarification",
        expected_message=expected_message,
    )


def raw_case(
    case_id: str,
    sql: str,
    *required: str,
    valid: bool = True,
    expected_message: str | None = None,
) -> BusinessCase:
    return BusinessCase(
        id=case_id,
        question=sql,
        kind="raw_valid" if valid else "raw_invalid",
        required=required,
        expected_message=expected_message,
    )


MEDIUM_CASES = [
    # Exact examples shown in the web UI.
    sql_case(
        "m01_ui_latest_price_all_currencies",
        "Покажи последние цены товара 1231235 во всех валютах",
        "select",
        "retail_price",
        "from [dwh].[llm].[price]",
        "[ware_id] = '1231235'",
        "row_number() over (partition by [ware_id] order by [price_date] desc)",
        "[full_retail_price_kzt]",
        "[full_retail_price_eur]",
        "[full_retail_price_usd]",
        "select top 100",
        "from latest_price where rn = 1",
    ),
    sql_case(
        "m02_ui_product_card_by_article",
        "Покажи карточку товара по артикулу G062214",
        "select",
        "product_dimension",
        "select top 100",
        "from [dwh].[llm].[dimension_product]",
        "[article] = 'g062214'",
        "[product_id]",
        "[brand]",
    ),
    sql_case(
        "m03_sales_detail_product_totals",
        "Покажи продажи товара 1231235",
        "select",
        "sales",
        "select top 100",
        "from [llm].[sales] as fact",
        "fact.[product_id] = '1231235'",
        "inner join [dwh].[llm].[dimension_product] as dim",
        "sum(fact.[amount]) over () as [__total_amount]",
        forbidden=("fact.[ware_id]", "customer_name"),
    ),
    sql_case(
        "m04_price_history_kzt",
        "История цены товара 12345 в KZT",
        "select",
        "retail_price",
        "select top 100",
        "from [dwh].[llm].[price]",
        "[ware_id] = '12345'",
        "[full_retail_price_kzt]",
        "order by [price_date] asc",
        forbidden=("[full_retail_price_usd]", "[full_retail_price_eur]"),
    ),
    sql_case(
        "m05_price_usd_column",
        "Покажи цену USD товара 12345",
        "select",
        "retail_price",
        "[ware_id] = '12345'",
        "[full_retail_price_usd]",
        forbidden=("[full_retail_price_kzt]", "[full_retail_price_eur]"),
    ),
    sql_case(
        "m06_price_eur_column",
        "Покажи цену в евро товара 12345",
        "select",
        "retail_price",
        "[ware_id] = '12345'",
        "[full_retail_price_eur]",
        forbidden=("[full_retail_price_kzt]", "[full_retail_price_usd]"),
    ),
    sql_case(
        "m07_price_default_all_currencies",
        "Покажи цены товара 54321",
        "select",
        "retail_price",
        "[full_retail_price_kzt]",
        "[full_retail_price_eur]",
        "[full_retail_price_usd]",
        "[ware_id] = '54321'",
    ),
    sql_case(
        "m08_price_all_columns_safe_limit",
        "Покажи все данные по ценам за март 2025",
        "select",
        "retail_price",
        "select top 100",
        "[price_date] between '2025-03-01' and '2025-03-31'",
        "[_rank]",
    ),
    sql_case(
        "m09_latest_price_article_prefix",
        "Последняя цена, артикул начинается с B42298",
        "select",
        "retail_price",
        "with product_scope as",
        "dim.[article] like 'b42298%'",
        "fact.[ware_id] = dim.[product_id]",
        "where rn = 1",
    ),
    sql_case(
        "m10_product_master_by_id",
        "Товар 1231234",
        "select",
        "product_dimension",
        "select top 100",
        "from [dwh].[llm].[dimension_product]",
        "[product_id] = '1231234'",
        "order by [product_id] asc",
    ),
    sql_case(
        "m11_product_name_by_id",
        "Название товара 50820",
        "select",
        "product_dimension",
        "[product_id] = '50820'",
        "[name]",
    ),
    sql_case(
        "m12_quoted_article_with_comma",
        'Товар с артикулом "UW2S0491 VBP.16Q_38,5_202"',
        "select",
        "product_dimension",
        "from [dwh].[llm].[dimension_product]",
        "[article] = 'uw2s0491 vbp.16q_38,5_202'",
    ),
    sql_case(
        "m13_unique_product_brands",
        "Покажи уникальные значения бренда",
        "select",
        "product_dimension",
        "select distinct top 100 [brand]",
        "from [dwh].[llm].[dimension_product]",
        "order by [brand] asc",
        forbidden=("[product_id]",),
    ),
    sql_case(
        "m14_count_products_for_brand",
        "Сколько товаров бренда Gucci",
        "aggregate",
        "product_dimension",
        "select count(*) as row_count",
        "from [dwh].[llm].[dimension_product]",
        "[brand] = 'gucci'",
    ),
    sql_case(
        "m15_product_preview_top10",
        "Покажи пример товаров из dimension_product",
        "select",
        "product_dimension",
        "select top 10",
        "from [dwh].[llm].[dimension_product]",
    ),
    sql_case(
        "m16_cost_product_history_safe_limit",
        "Покажи себестоимость товара 12345",
        "select",
        "product_cost",
        "select top 100",
        "from [dwh].[llm].[cost]",
        "[product_id] = '12345'",
        "[cost_per_unit]",
        "order by [date] desc",
        forbidden=("[ware_id]",),
    ),
    sql_case(
        "m17_cost_typo_deterministic",
        "Себестомость товара 1231237",
        "select",
        "product_cost",
        "from [dwh].[llm].[cost]",
        "[product_id] = '1231237'",
        forbidden=("from [dwh].[llm].[price]", "[ware_id]"),
    ),
    sql_case(
        "m18_cost_multiple_products",
        "Себестоимость товаров 1231230, 1231231, 1231232",
        "select",
        "product_cost",
        "[product_id] in ('1231230', '1231231', '1231232')",
        "order by [date] desc",
    ),
    sql_case(
        "m19_cost_history_chronological",
        "Покажи историю себестоимости товара 12345",
        "select",
        "product_cost",
        "[product_id] = '12345'",
        "order by [date] asc",
    ),
    sql_case(
        "m20_current_cost_latest_balance",
        "Покажи текущую себестоимость товара 12345",
        "select",
        "product_cost",
        "with ranked_cost as",
        "row_number() over (partition by [product_id] order by [date] desc)",
        "[qnt_sum]",
        "[cost_sum]",
        "where rn = 1",
    ),
    sql_case(
        "m21_stock_transfer_rows",
        "Покажи перемещение товаров по товару 12345",
        "select",
        "stock",
        "select top 100",
        "from [dwh].[llm].[stock]",
        "[product_id] = '12345'",
        "[recorder_type] = 'перемещение товаров'",
        "[document_id]",
        "order by [date] desc",
    ),
    sql_case(
        "m22_stock_start_exclusive",
        "Остаток товара 12345 на начало марта 2025",
        "stock_balance",
        "stock",
        "sum([quantity]) as stock_quantity_start",
        "[date] < convert(datetime2, '20250301', 112)",
        "[product_id] = '12345'",
    ),
    sql_case(
        "m23_stock_end_datetime_next_day",
        "Остаток товара 1231230 на 20.01.2022",
        "stock_balance",
        "stock",
        "sum([quantity]) as stock_quantity_end",
        "[date] < dateadd(day, 1, convert(datetime2, '20220120', 112))",
        forbidden=("[date] <= convert",),
    ),
    sql_case(
        "m24_current_stock_no_synthetic_date",
        "Остатки товара 1231230",
        "stock_balance",
        "stock",
        "sum([quantity]) as stock_quantity_end",
        "[product_id] = '1231230'",
        forbidden=("9999-12-31", "dateadd(day, 1"),
    ),
    sql_case(
        "m25_stock_multiple_products_grouped",
        "Остатки товаров 1231230, 1231231, 1231232 на 01.01.2023",
        "stock_balance",
        "stock",
        "select top 100 [product_id], sum([quantity]) as stock_quantity_end",
        "[product_id] in ('1231230', '1231231', '1231232')",
        "[date] < dateadd(day, 1, convert(datetime2, '20230101', 112))",
        "group by [product_id]",
    ),
    sql_case(
        "m26_purchase_rows_kzt_default",
        "Покажи закупочную стоимость товара 12345",
        "select",
        "purchases",
        "select top 100",
        "from [dwh].[llm].[v_purchases]",
        "[product_id] = '12345'",
        "[amount_kzt]",
        "order by [purchase_date] desc",
    ),
    sql_case(
        "m27_purchase_history_oldest_first",
        "Purchase history product 12345",
        "select",
        "purchases",
        "from [dwh].[llm].[v_purchases]",
        "[product_id] = '12345'",
        "order by [purchase_date] asc",
    ),
    sql_case(
        "m28_purchase_amount_kzt_month",
        "Сумма закупок в KZT за март 2026",
        "aggregate",
        "purchases",
        "sum([amount_kzt]) as sum_value",
        "[purchase_date] between '2026-03-01' and '2026-03-31'",
    ),
    sql_case(
        "m29_purchase_amount_usd_by_product",
        "Sum purchase amount USD by product",
        "aggregate",
        "purchases",
        "sum([amount_usd]) as sum_value",
        "group by [product_id]",
    ),
    sql_case(
        "m30_purchase_vat_eur",
        "Сумма НДС закупок в EUR за апрель 2026",
        "aggregate",
        "purchases",
        "sum([nds_eur]) as sum_value",
        "[purchase_date] between '2026-04-01' and '2026-04-30'",
        forbidden=("sum([nds_kzt])",),
    ),
    sql_case(
        "m31_purchase_unit_cost_kzt",
        "Покажи закупочную стоимость за единицу товара 12345",
        "select",
        "purchases",
        "cast([amount_kzt] as decimal(38, 6)) / nullif(cast([quantity] as decimal(38, 6)), 0) as [unit_cost_kzt]",
        "[product_id] = '12345'",
    ),
    sql_case(
        "m32_purchase_unit_cost_usd_grouped",
        "Средняя purchase unit cost USD по product_id",
        "aggregate",
        "purchases",
        "cast(sum([amount_usd]) as decimal(38, 6)) / nullif(cast(sum([quantity]) as decimal(38, 6)), 0)",
        "group by [product_id]",
    ),
    sql_case(
        "m33_sales_quantity_month",
        "Количество продаж за январь 2026",
        "aggregate",
        "sales",
        "sum([quantity]) as total_quantity",
        "sum([amount]) as [total_amount]",
        "[sale_date] between '2026-01-01' and '2026-01-31'",
        forbidden=("count(*)",),
    ),
    sql_case(
        "m34_sales_amount_month_kzt_default",
        "Сумма продаж за март 2026",
        "aggregate",
        "sales",
        "sum([amount]) as total_amount",
        "sum([quantity]) as [total_quantity]",
        "[sale_date] between '2026-03-01' and '2026-03-31'",
    ),
    sql_case(
        "m35_sales_amount_usd",
        "Сумма продаж в USD за март 2026",
        "aggregate",
        "sales",
        "sum([amount_usd]) as sum_value",
        "[sale_date] between '2026-03-01' and '2026-03-31'",
        forbidden=("sum([amount]) as total_amount",),
    ),
    sql_case(
        "m36_sales_amount_eur",
        "Выручка в EUR за февраль 2026",
        "aggregate",
        "sales",
        "sum([amount_eur]) as sum_value",
        "[sale_date] between '2026-02-01' and '2026-02-28'",
    ),
    sql_case(
        "m37_sales_article_join_safe_limit",
        "Все данные продажи артикула G062214",
        "select",
        "sales",
        "with product_scope as",
        "select top 100",
        "dim.[article] = 'g062214'",
        "fact.[product_id] = dim.[product_id]",
        "sum(fact.[amount]) over () as [__total_amount]",
    ),
    sql_case(
        "m38_unique_sales_product_ids",
        "Покажи уникальные product_id из sales",
        "select",
        "sales",
        "select distinct top 100 [product_id]",
        "from [llm].[sales]",
        forbidden=("[sale_date]", "inner join"),
    ),
    sql_case(
        "m39_sales_amount_by_channel",
        "Сумма продаж за июнь 2026 по каналу",
        "aggregate",
        "sales",
        "[channel], sum([amount]) as total_amount",
        "group by [channel]",
        "[__grand_total_amount]",
    ),
    sql_case(
        "m40_best_product_quantity",
        "Какой товар продавался лучше всего по количеству за март 2026",
        "aggregate",
        "sales",
        "select top 1 [product_id], sum([quantity]) as total_quantity",
        "group by [product_id]",
        "order by total_quantity desc, [product_id]",
        forbidden=("count(*)",),
    ),
    clarification_case(
        "m41_best_product_needs_metric",
        "Какой товар продавался лучше всего за март 2026?",
        "лучший товар считать по количеству",
    ),
    clarification_case(
        "m42_missing_customer_name",
        "Покажи продажи по customer_name Иванов",
        "нет customer_name",
    ),
    clarification_case(
        "m43_unbounded_rows_blocked",
        "Покажи все строки продаж без лимита",
        "безлимитный вывод строк",
    ),
    clarification_case(
        "m44_unsupported_sales_purchase_join",
        "Сравни продажи и закупки по товарам",
        "grain и ключи соединения",
    ),
    raw_case(
        "m45_raw_valid_top_select",
        "SELECT TOP 25 product_id, amount FROM [LLM].[sales] ORDER BY sale_date DESC;",
        "select top 25 product_id, amount",
        "from [llm].[sales]",
    ),
    raw_case(
        "m46_raw_valid_scalar_aggregate",
        "SELECT SUM(amount) AS total_amount FROM [LLM].[sales]",
        "select sum(amount) as total_amount",
    ),
    raw_case(
        "m47_raw_invalid_delete",
        "DELETE FROM [LLM].[sales] WHERE product_id = 1",
        valid=False,
        expected_message="только select",
    ),
    raw_case(
        "m48_raw_invalid_multiple_statements",
        "SELECT TOP 1 * FROM [LLM].[sales]; SELECT TOP 1 * FROM [DWH].[LLM].[price]",
        valid=False,
        expected_message="один select",
    ),
    sql_case(
        "m49_division_rows_by_city",
        "Все бутики город Алматы",
        "select",
        "division_dimension",
        "select top 100",
        "from [dwh].[llm].[division]",
        "[city] = 'алматы'",
        "[division]",
    ),
    sql_case(
        "m50_unique_season",
        "Уникальный сезон из dimension_product",
        "select",
        "product_dimension",
        "select distinct top 100 [season]",
        "from [dwh].[llm].[dimension_product]",
    ),
]


COMPLEX_CASES = [
    # The four analytical examples below complete the exact six UI examples.
    sql_case(
        "c01_ui_cartier_top10_sales_kzt",
        "Топ-10 товаров бренда Cartier по сумме продаж в KZT за март 2026",
        "aggregate",
        "sales",
        "select top 10 fact.[product_id], sum(fact.[amount]) as total_amount",
        "dim.[brand] = 'cartier'",
        "fact.[sale_date] between '2026-03-01' and '2026-03-31'",
        "group by fact.[product_id]",
        "order by total_amount desc, fact.[product_id]",
        "[__grand_total_amount]",
        forbidden=("count(*)",),
    ),
    sql_case(
        "c02_ui_jewelry_sales_by_brand",
        "Сумма продаж ювелирного направления за апрель 2026 с группировкой по брендам",
        "aggregate",
        "sales",
        "select top 100 dim.[brand], sum(fact.[amount]) as total_amount",
        "dim.[bu] = 'j&w'",
        "fact.[sale_date] between '2026-04-01' and '2026-04-30'",
        "group by dim.[brand]",
        "[__grand_total_amount]",
    ),
    sql_case(
        "c03_ui_stock_period_by_warehouse",
        "Покажи остаток товара 1231230 на начало и конец марта 2025 по складам",
        "stock_balance",
        "stock",
        "sum(case when [date] < convert(datetime2, '20250301', 112)",
        "sum(case when [date] < dateadd(day, 1, convert(datetime2, '20250331', 112))",
        "from [dwh].[llm].[stock]",
        "[product_id] = '1231230'",
        "group by [warehouse_id]",
    ),
    sql_case(
        "c04_ui_gm_articles_discount",
        "Рассчитай GM по артикулу 2807742, 2814951 с учетом скидки 30%",
        "gross_margin",
        "retail_price",
        "dim.[article] in ('2807742', '2814951')",
        "cast(30.000000 as decimal(38, 6)) as discount_percent",
        "cast(0.700000 as decimal(38, 6))",
        "from [dwh].[llm].[stock] as stock_fact",
        "from [dwh].[llm].[price] as price_fact",
        "from [dwh].[llm].[cost] as cost_fact",
        "/ cast(1.16 as decimal(38, 6)) as retail_price_kzt_vat_excluded",
        "cast(cost.[cost_sum] as decimal(38, 6)) / nullif(cast(cost.[qnt_sum] as decimal(38, 6)), 0) as unit_cost_kzt",
        "order by dim.[article], margin.[product_id]",
    ),
    sql_case(
        "c05_gm_article_each_sprut_code",
        "Посчитай Gross Margin по артикулу G062214",
        "gross_margin",
        "retail_price",
        "select top 100 margin.stock_quantity as [остаток], margin.[product_id], dim.[article]",
        "dim.[article] = 'g062214'",
        "left join stock_balance as stock",
        "cost.[cost_sum]",
        "cost.[qnt_sum]",
        "cast(1.16 as decimal(38, 6))",
        "gross_margin_percent",
        forbidden=("group by dim.[article]",),
    ),
    sql_case(
        "c06_gm_brand_each_product",
        "Покажи маржинальность по бренду Nike",
        "gross_margin",
        "retail_price",
        "dim.[brand] = 'nike'",
        "margin.[product_id], dim.[article], dim.[brand], dim.[name]",
        "order by dim.[brand], dim.[article], margin.[product_id]",
        "left join stock_balance as stock",
    ),
    sql_case(
        "c07_gm_sprut_code",
        "Рассчитай ГМ по коду спрута 12345",
        "gross_margin",
        "retail_price",
        "dim.[product_id] = '12345'",
        "partition by price_fact.[ware_id] order by price_fact.[price_date] desc",
        "partition by cost_fact.[product_id] order by cost_fact.[date] desc",
    ),
    sql_case(
        "c08_gm_explicit_positive_stock",
        "Маржинальность товаров в наличии",
        "gross_margin",
        "retail_price",
        "having sum(stock_fact.[quantity]) > 0",
        "inner join stock_balance as stock",
        forbidden=("left join stock_balance as stock",),
    ),
    sql_case(
        "c09_gm_as_of_date_next_day",
        "GM по товарам на 31.03.2026",
        "gross_margin",
        "retail_price",
        "stock_fact.[date] < dateadd(day, 1, convert(datetime2, '20260331', 112))",
        "price_fact.[price_date] < dateadd(day, 1, convert(datetime2, '20260331', 112))",
        "cost_fact.[date] < dateadd(day, 1, convert(datetime2, '20260331', 112))",
    ),
    sql_case(
        "c10_gm_brand_discount_as_of",
        "Маржа бренда Cartier на 30.06.2026 при скидке 15%",
        "gross_margin",
        "retail_price",
        "dim.[brand] = 'cartier'",
        "cast(15.000000 as decimal(38, 6)) as discount_percent",
        "cast(0.850000 as decimal(38, 6))",
        "dateadd(day, 1, convert(datetime2, '20260630', 112))",
    ),
    sql_case(
        "c11_sales_brand_filter_category_group",
        "Сумма продаж бренда Gucci с января по февраль 2025 группировка по категориям",
        "aggregate",
        "sales",
        "with product_scope as",
        "dim.[brand] = 'gucci'",
        "fact.[sale_date] between '2025-01-01' and '2025-02-28'",
        "group by dim.[category]",
        "[__grand_total_amount]",
    ),
    sql_case(
        "c12_sales_bu_exact_date_detail",
        "Продажи товара направления J&W за 01.06.2026",
        "select",
        "sales",
        "dim.[bu] = 'j&w'",
        "fact.[sale_date] = '2026-06-01'",
        "inner join product_scope as dim on fact.[product_id] = dim.[product_id]",
        "sum(fact.[quantity]) over () as [__total_quantity]",
    ),
    sql_case(
        "c13_sales_jewelry_month",
        "Покажи продажи ювелирного направления за июль 2026",
        "select",
        "sales",
        "dim.[bu] = 'j&w'",
        "fact.[sale_date] between '2026-07-01' and '2026-07-31'",
        "select top 100",
    ),
    sql_case(
        "c14_sales_boutique_jewelry_brand_totals",
        "Продажи ювелирки в бутике Saks Fifth Avenue за май 2025 группировка по брендам",
        "aggregate",
        "sales",
        "inner join product_scope as dim",
        "inner join [dwh].[llm].[division] as div on fact.[division_id] = div.[id]",
        "dim.[bu] = 'j&w'",
        "div.[division] = 'saks fifth avenue'",
        "group by dim.[brand]",
        "[__grand_total_amount]",
        forbidden=("dim.[store_jw]",),
    ),
    sql_case(
        "c15_sales_by_city",
        "Сумма продаж за июнь 2026 в разрезе городов",
        "aggregate",
        "sales",
        "select top 100 div.[city], sum(fact.[amount]) as total_amount",
        "fact.[division_id] = div.[id]",
        "group by div.[city]",
        "[__grand_total_amount]",
    ),
    sql_case(
        "c16_sales_multiple_dimension_groups",
        "Все данные продажи товара по бутику Saks Fifth Avenue за март 2026 группировка по брендам и направлению бизнеса",
        "aggregate",
        "sales",
        "select top 100 dim.[brand], dim.[bu], sum(fact.[amount]) as total_amount",
        "div.[division] = 'saks fifth avenue'",
        "group by dim.[brand], dim.[bu]",
        "order by dim.[brand], dim.[bu]",
        "[__grand_total_amount]",
    ),
    sql_case(
        "c17_top_products_quantity_brand",
        "Топ-5 товаров бренда Cartier по количеству продаж за апрель 2026",
        "aggregate",
        "sales",
        "select top 5 fact.[product_id], sum(fact.[quantity]) as total_quantity",
        "dim.[brand] = 'cartier'",
        "fact.[sale_date] between '2026-04-01' and '2026-04-30'",
        "group by fact.[product_id]",
        "[__grand_total_quantity]",
        forbidden=("count(*)",),
    ),
    sql_case(
        "c18_best_product_revenue",
        "Какой товар продавался лучше всего по сумме продаж в USD за 2025 год",
        "aggregate",
        "sales",
        "select top 1 [product_id], sum([amount_usd]) as sum_value",
        "group by [product_id]",
        "order by sum_value desc, [product_id]",
        "[__grand_total_primary]",
    ),
    sql_case(
        "c19_sales_two_dimension_filters_by_product",
        "Сумма продаж бренда Gucci категории Shoes по товарам за март 2026",
        "aggregate",
        "sales",
        "dim.[brand] = 'gucci'",
        "dim.[category] = 'shoes'",
        "fact.[sale_date] between '2026-03-01' and '2026-03-31'",
        "group by fact.[product_id]",
        "[__grand_total_amount]",
    ),
    sql_case(
        "c20_filtered_sales_detail_full_totals",
        "Покажи продажи артикула G062214 за март 2026",
        "select",
        "sales",
        "select top 100",
        "dim.[article] = 'g062214'",
        "fact.[sale_date] between '2026-03-01' and '2026-03-31'",
        "sum(fact.[quantity]) over () as [__total_quantity]",
        "sum(fact.[amount]) over () as [__total_amount]",
        "sum(fact.[discount]) over () as [__total_discount]",
    ),
    sql_case(
        "c21_latest_price_article_join",
        "Последняя цена артикула G062214",
        "select",
        "retail_price",
        "with product_scope as",
        "dim.[article] = 'g062214'",
        "fact.[ware_id] = dim.[product_id]",
        "partition by fact.[ware_id] order by fact.[price_date] desc",
        "where rn = 1",
    ),
    sql_case(
        "c22_latest_price_brand_join",
        "Покажи актуальные цены бренда Cartier",
        "select",
        "retail_price",
        "dim.[brand] = 'cartier'",
        "fact.[ware_id] = dim.[product_id]",
        "partition by fact.[ware_id] order by fact.[price_date] desc",
        "where rn = 1",
    ),
    sql_case(
        "c23_price_brand_month_safe_limit",
        "Покажи все цены бренда Cartier за март 2026",
        "select",
        "retail_price",
        "select top 100",
        "dim.[brand] = 'cartier'",
        "fact.[price_date] between '2026-03-01' and '2026-03-31'",
        "fact.[ware_id] = dim.[product_id]",
    ),
    sql_case(
        "c24_price_season_filter_history",
        "История цен товаров season_short SS25",
        "select",
        "retail_price",
        "dim.[season_short] = 'ss25'",
        "fact.[ware_id] = dim.[product_id]",
        "order by fact.[price_date] asc",
    ),
    sql_case(
        "c25_latest_price_as_of_next_day",
        "Последняя цена товара 12345 на 31.03.2026",
        "select",
        "retail_price",
        "[price_date] < dateadd(day, 1, convert(datetime2, '20260331', 112))",
        "[ware_id] = '12345'",
        "where rn = 1",
    ),
    sql_case(
        "c26_cost_article_join",
        "Себестоимость товара с артикулом P084503",
        "select",
        "product_cost",
        "with product_scope as",
        "dim.[article] = 'p084503'",
        "fact.[product_id] = dim.[product_id]",
        "order by fact.[date] desc",
    ),
    sql_case(
        "c27_current_cost_brand_latest",
        "Покажи текущую себестоимость товаров бренда Gucci",
        "select",
        "product_cost",
        "with product_scope as",
        "dim.[brand] = 'gucci'",
        "row_number() over (partition by fact.[product_id] order by fact.[date] desc)",
        "where rn = 1",
        forbidden=("sum(fact.[cost_sum])",),
    ),
    sql_case(
        "c28_cost_exact_date_datetime_range",
        "Покажи операции себестоимости товара 12345 за 20.01.2022",
        "select",
        "product_cost",
        "[date] >= convert(datetime2, '20220120', 112)",
        "[date] < dateadd(day, 1, convert(datetime2, '20220120', 112))",
        "[product_id] = '12345'",
    ),
    sql_case(
        "c29_cost_period_datetime_range",
        "Покажи операции себестоимости с 01.03.2025 по 31.03.2025",
        "select",
        "product_cost",
        "[date] >= convert(datetime2, '20250301', 112)",
        "[date] < dateadd(day, 1, convert(datetime2, '20250331', 112))",
    ),
    sql_case(
        "c30_cost_operations_sum_by_product",
        "Сумма себестоимости операций по товарам за март 2026",
        "aggregate",
        "product_cost",
        "sum([cost]) as sum_value",
        "group by [product_id]",
        "[date] >= convert(datetime2, '20260301', 112)",
        "[date] < dateadd(day, 1, convert(datetime2, '20260331', 112))",
    ),
    sql_case(
        "c31_running_cost_balance_not_summed",
        "Покажи себестоимость остатка товара 12345",
        "select",
        "product_cost",
        "[cost_sum]",
        "[product_id] = '12345'",
        forbidden=("sum([cost_sum])",),
    ),
    sql_case(
        "c32_stock_article_group_sprut",
        "Остатки товара артикул 69683886 разбивка по коду спрута",
        "stock_balance",
        "stock",
        "dim.[article] = '69683886'",
        "fact.[product_id] = dim.[product_id]",
        "select top 100 fact.[product_id], sum(fact.[quantity]) as stock_quantity_end",
        "group by fact.[product_id]",
    ),
    sql_case(
        "c33_stock_brand_join",
        "Остаток по бренду Gucci",
        "stock_balance",
        "stock",
        "dim.[brand] = 'gucci'",
        "fact.[product_id] = dim.[product_id]",
        "sum(fact.[quantity]) as stock_quantity_end",
    ),
    sql_case(
        "c34_stock_collection_join",
        "Остаток по коллекции SS25",
        "stock_balance",
        "stock",
        "dim.[collection_jw] = 'ss25'",
        "fact.[product_id] = dim.[product_id]",
    ),
    sql_case(
        "c35_stock_period_two_balances_product",
        "Остаток товара 55555 на начало и конец января-февраля 2025",
        "stock_balance",
        "stock",
        "sum(case when [date] < convert(datetime2, '20250101', 112)",
        "sum(case when [date] < dateadd(day, 1, convert(datetime2, '20250228', 112))",
        "[product_id] = '55555'",
    ),
    sql_case(
        "c36_stock_movement_exact_datetime_date",
        "Покажи движения склада за 21.05.2026",
        "select",
        "stock",
        "[date] >= convert(datetime2, '20260521', 112)",
        "[date] < dateadd(day, 1, convert(datetime2, '20260521', 112))",
        "order by [date] desc",
    ),
    sql_case(
        "c37_stock_transfer_article_period",
        "Перемещения товаров артикула G062214 за март 2026",
        "select",
        "stock",
        "dim.[article] = 'g062214'",
        "fact.[recorder_type] = 'перемещение товаров'",
        "fact.[date] >= convert(datetime2, '20260301', 112)",
        "fact.[date] < dateadd(day, 1, convert(datetime2, '20260331', 112))",
    ),
    sql_case(
        "c38_positive_stock_by_warehouse_having",
        "Остаток по складам больше 0 на 31.03.2026",
        "stock_balance",
        "stock",
        "group by [warehouse_id]",
        "having sum(case when [date] < dateadd(day, 1, convert(datetime2, '20260331', 112)) then [quantity] else 0 end) > 0",
    ),
    sql_case(
        "c39_purchase_article_join",
        "Закупки артикула G062214 за март 2026",
        "select",
        "purchases",
        "with product_scope as",
        "dim.[article] = 'g062214'",
        "fact.[product_id] = dim.[product_id]",
        "fact.[purchase_date] between '2026-03-01' and '2026-03-31'",
    ),
    sql_case(
        "c40_purchase_bu_join",
        "Закупки направления бизнеса Fashion за январь 2026",
        "select",
        "purchases",
        "dim.[bu] = 'fashion'",
        "fact.[purchase_date] between '2026-01-01' and '2026-01-31'",
        "fact.[product_id] = dim.[product_id]",
    ),
    sql_case(
        "c41_purchase_supplier_returns",
        "Покажи возвраты товаров поставщику за март 2026",
        "select",
        "purchases",
        "[recorder_type] = 'возврат товаров поставщику'",
        "[purchase_date] between '2026-03-01' and '2026-03-31'",
        "[recorder_number]",
    ),
    sql_case(
        "c42_import_purchase_vat_chf",
        "Сумма НДС закупок CHF по ГТД за апрель 2026",
        "aggregate",
        "purchases",
        "sum([nds_chf]) as sum_value",
        "[recorder_type] = 'гтд по импорту'",
        "[purchase_date] between '2026-04-01' and '2026-04-30'",
        forbidden=("sum([nds_kzt])",),
    ),
    sql_case(
        "c43_purchase_unit_cost_eur_by_product",
        "Средняя закупочная стоимость за единицу EUR по товарам за март 2026",
        "aggregate",
        "purchases",
        "cast(sum([amount_eur]) as decimal(38, 6)) / nullif(cast(sum([quantity]) as decimal(38, 6)), 0)",
        "group by [product_id]",
        "[purchase_date] between '2026-03-01' and '2026-03-31'",
    ),
    sql_case(
        "c44_purchase_extra_expenses_brand",
        "Сумма дополнительных расходов закупки бренда Cartier за май 2026",
        "aggregate",
        "purchases",
        "dim.[brand] = 'cartier'",
        "fact.[recorder_type] = 'поступление доп. расходов'",
        "sum(fact.[amount_kzt]) as sum_value",
        "fact.[purchase_date] between '2026-05-01' and '2026-05-31'",
    ),
    sql_case(
        "c45_product_count_multiple_groups",
        "Сколько товаров в dimension_product с группировкой по брендам и категориям",
        "aggregate",
        "product_dimension",
        "select top 100 [brand], [category], count(*) as row_count",
        "group by [brand], [category]",
    ),
    sql_case(
        "c46_unique_articles_jewelry",
        "Уникальные артикулы направления ювелирка",
        "select",
        "product_dimension",
        "select distinct top 100 [article]",
        "[bu] = 'j&w'",
        forbidden=("sum(",),
    ),
    sql_case(
        "c47_product_multiple_attribute_filters",
        "Покажи карточки товаров бренда Gucci категории Shoes сезона SS25",
        "select",
        "product_dimension",
        "select top 100",
        "[brand] = 'gucci'",
        "[category] = 'shoes'",
        "[season] = 'ss25'",
        forbidden=("sum(",),
    ),
    sql_case(
        "c48_filtered_top_sales_full_grand_total",
        "Топ-3 бренда по сумме продаж в городе Алматы за март 2026",
        "aggregate",
        "sales",
        "select top 3 dim.[brand], sum(fact.[amount]) as total_amount",
        "div.[city] = 'алматы'",
        "fact.[sale_date] between '2026-03-01' and '2026-03-31'",
        "group by dim.[brand]",
        "sum(sum(fact.[amount])) over () as [__grand_total_amount]",
    ),
    clarification_case(
        "c49_price_stock_join_not_confirmed",
        "Покажи последнюю цену артикула 69683886 только в наличии",
        "price↔stock join документирован только для расчёта gm",
    ),
    raw_case(
        "c50_raw_valid_cte_select",
        "WITH totals AS (SELECT product_id, SUM(amount) AS revenue FROM [LLM].[sales] GROUP BY product_id) SELECT TOP 10 product_id, revenue FROM totals ORDER BY revenue DESC",
        "with totals as",
        "select top 10 product_id, revenue from totals",
    ),
]


assert len(MEDIUM_CASES) == 50
assert len(COMPLEX_CASES) == 50
ALL_CASES = [*MEDIUM_CASES, *COMPLEX_CASES]
assert len({case.id for case in ALL_CASES}) == 100
assert len({case.question for case in ALL_CASES}) == 100


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda case: case.id)
def test_local_sql_business_matrix(case: BusinessCase) -> None:
    parser = IntentParser()
    builder = SqlBuilder()
    memory = SqlAgentMemory()

    with (
        patch(
            "sql_agent.intent_parser.build_llm",
            side_effect=AssertionError(
                f"Supported deterministic case unexpectedly called LLM: {case.id}"
            ),
        ) as build_llm_mock,
        patch("sql_agent.sql_builder.run_sql_query", return_value=[]) as run_query_mock,
    ):
        if case.kind == "clarification":
            clarification = parser.get_clarification(case.question)
            assert clarification is not None
            assert _normalized(case.expected_message or "") in _normalized(clarification)
            run_query_mock.assert_not_called()
        elif case.kind == "raw_valid":
            validate_readonly_select_sql(case.question)
            normalized_sql = _normalized(case.question)
            for fragment in case.required:
                assert _normalized(fragment) in normalized_sql
            run_query_mock.assert_not_called()
        elif case.kind == "raw_invalid":
            with pytest.raises(ValueError) as error:
                validate_readonly_select_sql(case.question)
            assert _normalized(case.expected_message or "") in _normalized(str(error.value))
            run_query_mock.assert_not_called()
        else:
            assert case.kind == "sql"
            assert parser.get_clarification(case.question) is None
            intent = parser.parse(case.question, memory)
            assert intent.operation == case.operation
            assert intent.domain == case.domain

            emitted_sql: list[str] = []
            builder.execute(
                SimpleNamespace(_engine=object()),
                intent,
                on_sql_ready=emitted_sql.append,
            )
            assert len(emitted_sql) == 1
            generated_sql = emitted_sql[0]
            validate_readonly_select_sql(generated_sql)

            normalized_sql = _normalized(generated_sql)
            for fragment in case.required:
                assert _normalized(fragment) in normalized_sql
            for fragment in case.forbidden:
                assert _normalized(fragment) not in normalized_sql

            if case.id == "m02_ui_product_card_by_article":
                for column_name in PRODUCT_DIMENSION_COLUMNS:
                    assert f"[{column_name.lower()}]" in normalized_sql

            if case.id == "c04_ui_gm_articles_discount":
                final_select = normalized_sql[normalized_sql.rfind("select top 100") :]
                mandatory_columns = (
                    "as [остаток]",
                    "margin.[product_id]",
                    "dim.[article]",
                    "dim.[brand]",
                    "dim.[name]",
                    "margin.[price_date]",
                    "margin.cost_date",
                    "as retail_price_kzt_incl_vat",
                    "as retail_price_kzt_excl_vat",
                    "as cost_kzt_per_unit",
                    "as gross_profit_kzt_per_unit",
                    "as gross_margin_percent",
                )
                positions = [
                    final_select.index(fragment)
                    for fragment in mandatory_columns
                ]
                assert positions == sorted(positions)

            run_query_mock.assert_called_once_with(ANY, generated_sql)

        build_llm_mock.assert_not_called()
