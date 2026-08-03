from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory
from sql_agent.query_utils import validate_readonly_select_sql
from sql_agent.service import SqlAgentService
from sql_agent.sql_builder import SqlBuilder


def build_sql(question: str, rows: list[tuple] | None = None) -> tuple[object, str, str]:
    parser = IntentParser()
    assert parser.get_clarification(question) is None

    with patch(
        "sql_agent.intent_parser.build_llm",
        side_effect=AssertionError("Documented business request must not call LLM"),
    ) as build_llm_mock:
        intent = parser.parse(question, SqlAgentMemory())

    emitted_sql: list[str] = []
    with patch(
        "sql_agent.sql_builder.run_sql_query",
        return_value=rows or [],
    ):
        response = SqlBuilder().execute(
            SimpleNamespace(_engine=object()),
            intent,
            on_sql_ready=emitted_sql.append,
        )

    build_llm_mock.assert_not_called()
    assert len(emitted_sql) == 1
    validate_readonly_select_sql(emitted_sql[0])
    return intent, emitted_sql[0], response


@pytest.mark.parametrize(
    ("question", "group_column"),
    (
        ("Сумма продаж по каналу за март 2026", "channel"),
        ("Сумма продаж по документам за март 2026", "document_number"),
        ("Сумма продаж по способу оплаты за март 2026", "payment_method"),
        ("Сумма продаж по partner_id за март 2026", "partner_id"),
    ),
)
def test_sales_native_attribute_without_value_is_grouping_not_filter(
    question: str,
    group_column: str,
) -> None:
    intent, sql, _ = build_sql(question)

    assert intent.operation == "aggregate"
    assert intent.domain == "sales"
    assert intent.aggregate_function == "sum"
    assert intent.metric_column == "amount"
    assert intent.group_by == group_column
    assert group_column not in intent.filters.equality_filters
    assert f"GROUP BY [{group_column}]" in sql
    assert f"[{group_column}] =" not in sql


@pytest.mark.parametrize(
    ("question", "filter_column", "filter_value"),
    (
        ("Сумма продаж канал Online за март 2026", "channel", "Online"),
        ("Сумма продаж по документу DOC-1 за март 2026", "document_number", "DOC-1"),
        ("Сумма продаж способ оплаты Card за март 2026", "payment_method", "Card"),
        ("Сумма продаж partner_id P123 за март 2026", "partner_id", "P123"),
    ),
)
def test_sales_native_attribute_with_value_is_filter_not_grouping(
    question: str,
    filter_column: str,
    filter_value: str,
) -> None:
    intent, sql, _ = build_sql(question)

    assert intent.operation == "aggregate"
    assert intent.domain == "sales"
    assert intent.aggregate_function == "sum"
    assert intent.metric_column == "amount"
    assert intent.group_by is None
    assert intent.filters.equality_filters[filter_column] == filter_value
    assert f"[{filter_column}] = '{filter_value}'" in sql
    assert "GROUP BY" not in sql


def test_count_sales_documents_uses_distinct_document_number() -> None:
    intent, sql, _ = build_sql("Сколько документов продаж за март 2026")

    assert intent.operation == "aggregate"
    assert intent.domain == "sales"
    assert intent.aggregate_function == "count"
    assert intent.metric_column == "document_number"
    assert "document_number" not in intent.filters.equality_filters
    assert "COUNT(DISTINCT [document_number]) AS document_count" in sql
    assert "COUNT(*) AS row_count" not in sql
    assert "[sale_date] BETWEEN '2026-03-01' AND '2026-03-31'" in sql


def test_grouped_sales_count_has_full_filtered_grand_total() -> None:
    rows = [
        (
            "Online",
            2,
            3,
            300,
            250,
            0,
            100,
            150,
            0,
            0,
            50,
            5,
            500,
            450,
            0,
            200,
            250,
            0,
            0,
            80,
            4,
        ),
    ]
    intent, sql, response = build_sql(
        "Сколько строк продаж по каналу за март 2026",
        rows=rows,
    )

    assert intent.aggregate_function == "count"
    assert intent.group_by == "channel"
    assert "COUNT(*) AS row_count" in sql
    assert "SUM(COUNT(*)) OVER () AS [__grand_total_row_count]" in sql
    assert "ИТОГО,4,5,500,450,0,200,250,0,0,80" in response


def test_gm_explicit_product_id_filters_product_scope() -> None:
    intent, sql, _ = build_sql("GM по product_id 12345")

    assert intent.operation == "gross_margin"
    assert intent.filters.identifier_values == ["12345"]
    assert "dim.[product_id] = '12345'" in sql
    assert "ON price_fact.[ware_id] = scope.[product_id]" in sql
    assert "ON cost_fact.[product_id] = scope.[product_id]" in sql


def test_gm_accepts_instrumental_discount_wording() -> None:
    intent, sql, _ = build_sql("GM по товару 12345 со скидкой 30%")

    assert intent.operation == "gross_margin"
    assert intent.discount_percent == 30
    assert "dim.[product_id] = '12345'" in sql
    assert "CAST(30.000000 AS decimal(38, 6)) AS discount_percent" in sql
    assert "CAST(0.700000 AS decimal(38, 6))" in sql


@pytest.mark.parametrize(
    "question",
    (
        "Покажи продажи товаров в наличии",
        "Покажи себестоимость товаров в наличии",
        "Покажи закупки товаров в наличии",
    ),
)
def test_unconfirmed_fact_to_stock_availability_requires_clarification(
    question: str,
) -> None:
    clarification = IntentParser().get_clarification(question)

    assert clarification is not None
    assert any(
        marker in clarification.lower()
        for marker in ("не подтверж", "нельзя", "только для расчёта gm")
    )


@pytest.mark.parametrize(
    "question",
    (
        "Продажи после 2026-03-01 до 2026-03-31",
        "Продажи после 01.03.2026 до 31.03.2026",
    ),
)
def test_two_date_after_to_range_starts_next_calendar_day(question: str) -> None:
    intent, sql, _ = build_sql(question)

    assert intent.domain == "sales"
    assert intent.filters.date_from == "2026-03-02"
    assert intent.filters.date_to == "2026-03-31"
    assert "fact.[sale_date] BETWEEN '2026-03-02' AND '2026-03-31'" in sql
    assert "BETWEEN '2026-03-01' AND '2026-03-31'" not in sql


@pytest.mark.parametrize(
    "question",
    (
        "Продажи за 2026-02-30",
        "Продажи за 31.02.2026",
    ),
)
def test_impossible_explicit_date_is_rejected_without_sql(question: str) -> None:
    parser = IntentParser()
    clarification = parser.get_clarification(question)
    if clarification is not None:
        assert "дат" in clarification.lower()
        return

    with patch(
        "sql_agent.intent_parser.build_llm",
        side_effect=AssertionError("Invalid explicit date must not call LLM"),
    ):
        with pytest.raises(ValueError, match="(?i)дат"):
            parser.parse(question, SqlAgentMemory())


@pytest.mark.parametrize(
    ("question", "domain", "group_column"),
    (
        ("Сумма продаж по категориям за март 2026", "sales", "category"),
        ("Сумма закупок по артикулам за март 2026", "purchases", "article"),
        ("Остатки по сезонам на конец марта 2025", "stock", "season"),
        (
            "Сумма себестоимости операций по размерам за март 2026",
            "product_cost",
            "common_size",
        ),
    ),
)
def test_product_dimension_plural_breakdowns_work_for_fact_domains(
    question: str,
    domain: str,
    group_column: str,
) -> None:
    intent, sql, _ = build_sql(question)

    assert intent.domain == domain
    assert intent.group_by == group_column
    assert "dimension_product" in sql
    assert f"GROUP BY dim.[{group_column}]" in sql


@pytest.mark.parametrize(
    "question",
    (
        "Покажи [DWH].[LLM].[stock] где recorder_type = Поступление товаров и услуг",
        "Движения склада: Поступление товаров и услуг",
    ),
)
def test_explicit_stock_context_wins_over_purchase_operation_wording(
    question: str,
) -> None:
    intent, sql, _ = build_sql(question)

    assert intent.domain == "stock"
    assert intent.table_name == "stock"
    assert "FROM [DWH].[LLM].[stock]" in sql
    assert "[recorder_type] = 'Поступление товаров и услуг'" in sql
    assert "purchase_date" not in sql


def test_last_five_prices_returns_five_history_rows_not_only_rank_one() -> None:
    intent, sql, _ = build_sql("Покажи последние 5 цен товара 1231235")

    assert intent.limit == 5
    assert not intent.latest_per_identifier
    assert "SELECT TOP 5" in sql
    assert "ORDER BY [price_date] DESC" in sql
    assert "WHERE rn = 1" not in sql


def test_last_five_cost_operations_are_not_collapsed_to_current_balance() -> None:
    intent, sql, _ = build_sql(
        "Покажи последние 5 операций себестоимости товара 12345"
    )

    assert intent.limit == 5
    assert not intent.latest_per_identifier
    assert "SELECT TOP 5" in sql
    assert "ORDER BY [date] DESC" in sql
    assert "ranked_cost" not in sql


@pytest.mark.parametrize(
    ("question", "message_fragment"),
    (
        ("Покажи общую себестоимость товара 12345", "sum(cost)"),
        ("Остаток товара 12345 на начало", "дат"),
    ),
)
def test_ambiguous_cost_and_start_balance_require_clarification(
    question: str,
    message_fragment: str,
) -> None:
    clarification = IntentParser().get_clarification(question)

    assert clarification is not None
    assert message_fragment in clarification.lower()


@pytest.mark.parametrize(
    ("question", "group_column", "having"),
    (
        (
            "Товары с суммой продаж больше 100000",
            "product_id",
            "HAVING SUM([amount]) > 100000",
        ),
        (
            "Бренды с выручкой не менее 100000",
            "brand",
            "HAVING SUM(fact.[amount]) >= 100000",
        ),
        (
            "Остатки по товарам меньше -5",
            "product_id",
            "HAVING SUM([quantity]) < -5",
        ),
    ),
)
def test_aggregate_thresholds_infer_entity_group_and_preserve_operator(
    question: str,
    group_column: str,
    having: str,
) -> None:
    intent, sql, _ = build_sql(question)

    assert intent.group_by == group_column
    assert having in sql


@pytest.mark.parametrize("currency", ("USD", "EUR"))
def test_detailed_sales_keeps_explicit_currency_amount_and_total(
    currency: str,
) -> None:
    metric = f"amount_{currency.lower()}"
    intent, sql, _ = build_sql(f"Покажи продажи в {currency} за март 2026")

    assert intent.metric_column == metric
    assert f"fact.[{metric}]" in sql
    assert f"AS [__total_{metric}]" in sql
    assert "price_usd" not in sql
    assert "price_eur" not in sql


@pytest.mark.parametrize(
    "question",
    ("Средняя цена продажи в USD", "Максимальная цена продажи в EUR"),
)
def test_undocumented_sales_unit_price_currency_requires_clarification(
    question: str,
) -> None:
    clarification = IntentParser().get_clarification(question)

    assert clarification is not None
    assert "price_usd/price_eur" in clarification


def test_gm_percent_threshold_is_applied_after_margin_calculation() -> None:
    intent, sql, _ = build_sql("Товары с маржей больше 10,5%")

    assert intent.operation == "gross_margin"
    assert intent.filters.threshold_value == "10.5"
    assert "WHERE margin.gross_margin_percent > 10.5" in sql


@pytest.mark.parametrize(
    ("question", "column", "value"),
    (
        ("Продажи категории Обувь в USD за март 2026", "category", "Обувь"),
        ("Закупки бренда Gucci в EUR за март 2026", "brand", "Gucci"),
        ("Продажи бренда Gucci в городе Алматы", "brand", "Gucci"),
        ("Продажи бренда Gucci вчера", "brand", "Gucci"),
        ("Продажи бренда Gucci размера 42", "brand", "Gucci"),
        ("Продажи бренда Gucci группировка по категориям", "brand", "Gucci"),
        ("Продажи бренда Gucci первые 10", "brand", "Gucci"),
        (
            "Закупки бренда Gucci типа Поступление товаров и услуг",
            "brand",
            "Gucci",
        ),
    ),
)
def test_dimension_value_does_not_swallow_following_qualifier(
    question: str,
    column: str,
    value: str,
) -> None:
    intent, _, _ = build_sql(question)

    assert intent.filters.dimension_filters[column] == value


@pytest.mark.parametrize(
    ("question", "metric", "group_by"),
    (
        ("Сколько уникальных брендов продавалось?", "brand", None),
        ("Сколько брендов продавалось?", "brand", None),
        ("Сколько каналов продаж?", "channel", None),
        ("Сколько способов оплаты использовалось?", "payment_method", None),
        ("Сколько уникальных товаров продавалось?", "product_id", None),
        ("Сколько уникальных брендов продавалось по категориям?", "brand", "category"),
        ("Сколько уникальных артикулов по брендам в продажах?", "article", "brand"),
        ("Количество уникальных товаров по каналам продаж", "product_id", "channel"),
    ),
)
def test_distinct_cardinality_uses_requested_attribute_and_breakdown(
    question: str,
    metric: str,
    group_by: str | None,
) -> None:
    intent, sql, _ = build_sql(question)

    assert intent.operation == "aggregate"
    assert intent.aggregate_function == "count"
    assert intent.metric_column == metric
    assert intent.distinct
    assert intent.group_by == group_by
    assert f"COUNT(DISTINCT " in sql
    assert metric not in intent.filters.dimension_filters
    if metric in {"brand", "article"}:
        assert "dimension_product" in sql
        assert f"dim.[{metric}]" in sql
    if group_by:
        assert "GROUP BY" in sql
        assert "__grand_total_distinct_count" in sql


def test_current_average_cost_uses_latest_balance_ratio() -> None:
    intent, sql, _ = build_sql("Текущая средняя себестоимость товара 12345")

    assert intent.latest_per_identifier
    assert intent.current_cost_per_unit
    assert "ROW_NUMBER() OVER (PARTITION BY [product_id] ORDER BY [date] DESC)" in sql
    assert "[cost_sum] AS decimal(38, 6)" in sql
    assert "[qnt_sum] AS decimal(38, 6)), 0) AS [current_cost_per_unit]" in sql
    assert "AVG([cost])" not in sql


def test_weighted_average_cost_uses_total_cost_over_total_quantity() -> None:
    intent, sql, _ = build_sql("Средняя себестоимость товара 12345 взвешенная")

    assert intent.weighted_cost_per_unit
    assert "SUM([cost])" in sql
    assert "SUM([quantity])" in sql
    assert "AVG(CAST([cost]" not in sql


@pytest.mark.parametrize(
    "question",
    (
        "Себестоимость по категориям",
        "Операционная себестоимость по артикулам",
    ),
)
def test_cost_breakdown_without_metric_requires_clarification(question: str) -> None:
    clarification = IntentParser().get_clarification(question)

    assert clarification is not None
    assert "метрик" in clarification.lower()


@pytest.mark.parametrize(
    ("question", "date_from", "date_to", "date_eq"),
    (
        ("Продажи не ранее 2026-03-01", "2026-03-01", None, None),
        ("Продажи позже 2026-03-01", "2026-03-02", None, None),
        ("Продажи раньше 2026-03-01", None, "2026-02-28", None),
        ("Продажи на 15 марта 2026", None, None, "2026-03-15"),
        ("Продажи с 1 марта по 31 марта 2026", "2026-03-01", "2026-03-31", None),
    ),
)
def test_date_wording_preserves_direction_and_exact_russian_day(
    question: str,
    date_from: str | None,
    date_to: str | None,
    date_eq: str | None,
) -> None:
    intent, _, _ = build_sql(question)

    assert intent.filters.date_from == date_from
    assert intent.filters.date_to == date_to
    assert intent.filters.date_eq == date_eq


@pytest.mark.parametrize(
    "question",
    (
        "Продажи с 2026-03-31 по 2026-03-01",
        "Продажи с 31 марта 2026 по 1 марта 2026",
        "Продажи за 31 февраля 2026",
    ),
)
def test_invalid_or_reversed_date_requires_clarification(question: str) -> None:
    clarification = IntentParser().get_clarification(question)

    assert clarification is not None
    assert "дат" in clarification.lower()


@pytest.mark.parametrize(
    ("wording", "operator"),
    (
        ("более 100000", ">"),
        ("от 100000", ">="),
        ("до 100000", "<="),
        ("равной 100000", "="),
        ("= 100000", "="),
    ),
)
def test_numeric_threshold_synonyms_are_not_dropped(
    wording: str,
    operator: str,
) -> None:
    intent, sql, _ = build_sql(f"Товары с суммой продаж {wording}")

    assert intent.filters.threshold_operator == operator
    assert f"HAVING SUM([amount]) {operator} 100000" in sql


@pytest.mark.parametrize(
    "question",
    (
        "Товары с суммой продаж от 100000 до 200000",
        "Товары с суммой продаж между 100000 и 200000",
        "GM от 20% до 40%",
    ),
)
def test_two_sided_numeric_range_is_not_partially_applied(question: str) -> None:
    clarification = IntentParser().get_clarification(question)

    assert clarification is not None
    assert "двумя границами" in clarification.lower()


@pytest.mark.parametrize(
    "question",
    (
        "Сравни продажи и остатки по товарам",
        "Сравни цены и себестоимость",
        "Сравни закупки и себестоимость",
        "Цены и продажи по товарам",
        "Покажи себестоимость и остаток товара 12345",
    ),
)
def test_unsupported_cross_fact_request_is_not_silently_reduced(question: str) -> None:
    clarification = IntentParser().get_clarification(question)

    assert clarification is not None
    assert "grain" in clarification.lower()


@pytest.mark.parametrize(
    ("question", "limit", "direction"),
    (
        ("Топ 10 товаров по марже", 10, "DESC"),
        ("Покажи 10 товаров с минимальной маржинальностью", 10, "ASC"),
        ("Самый маржинальный товар", 1, "DESC"),
    ),
)
def test_gm_ranking_orders_by_margin_not_product_code(
    question: str,
    limit: int,
    direction: str,
) -> None:
    intent, sql, _ = build_sql(question)

    assert intent.limit == limit
    assert f"SELECT TOP {limit}" in sql
    assert f"ORDER BY margin.gross_margin_percent {direction}, margin.[product_id]" in sql


@pytest.mark.parametrize(
    "question",
    (
        "Покажи [DWH].[LLM].[price] продажи",
        "Покажи [DWH].[LLM].[v_Purchases] себестоимость",
        "Покажи [LLM].[sales] себестоимость",
    ),
)
def test_explicit_table_conflict_requires_clarification(question: str) -> None:
    clarification = IntentParser().get_clarification(question)

    assert clarification is not None
    assert "таблиц" in clarification.lower()


@pytest.mark.parametrize(
    "question",
    (
        "Продажи кроме бренда Gucci",
        "Продажи без бренда Gucci",
        "Закупки исключая бренд Gucci",
    ),
)
def test_negated_dimension_filter_is_not_inverted(question: str) -> None:
    clarification = IntentParser().get_clarification(question)

    assert clarification is not None
    assert "исключ" in clarification.lower()


@pytest.mark.parametrize(
    ("question", "column", "values"),
    (
        ("Продажи брендов Gucci и Prada", "brand", ["Gucci", "Prada"]),
        (
            "Продажи брендов Gucci, Prada и Cartier",
            "brand",
            ["Gucci", "Prada", "Cartier"],
        ),
        ("Закупки категорий Обувь и Одежда", "category", ["Обувь", "Одежда"]),
    ),
)
def test_dimension_conjunction_list_becomes_in_filter(
    question: str,
    column: str,
    values: list[str],
) -> None:
    intent, sql, _ = build_sql(question)

    assert intent.filters.dimension_filters[column] == values
    assert " IN (" in sql


def test_identifier_conjunction_list_keeps_every_product() -> None:
    intent, sql, _ = build_sql("Продажи товаров 1231230 и 1231231")

    assert intent.filters.identifier_values == ["1231230", "1231231"]
    assert "IN ('1231230', '1231231')" in sql


@pytest.mark.parametrize(
    ("question", "value"),
    (
        ("Продажи бренда O'Neill", "O'Neill"),
        ("Продажи бренда Saint Laurent (YSL)", "Saint Laurent (YSL)"),
    ),
)
def test_dimension_value_keeps_apostrophe_and_parentheses(
    question: str,
    value: str,
) -> None:
    intent, sql, _ = build_sql(question)

    assert intent.filters.dimension_filters["brand"] == value
    assert value.replace("'", "''") in sql


@pytest.mark.parametrize(
    "question",
    (
        "GM со скидкой 110%",
        "GM со скидкой -10%",
        "Сумма продаж в CHF",
        "Розничная цена в CHF",
        "Закупки в RUB",
    ),
)
def test_invalid_discount_or_unsupported_currency_requires_clarification(
    question: str,
) -> None:
    clarification = IntentParser().get_clarification(question)

    assert clarification is not None


@pytest.mark.parametrize(
    ("question", "direction"),
    (
        ("Сумма продаж по брендам по убыванию выручки", "DESC"),
        ("Сумма продаж по брендам по возрастанию выручки", "ASC"),
        ("Закупки по брендам сортировать по сумме", "DESC"),
    ),
)
def test_grouped_aggregate_explicit_metric_sort_is_honored(
    question: str,
    direction: str,
) -> None:
    intent, sql, _ = build_sql(question)

    assert intent.sort_column == intent.metric_column
    assert f"ORDER BY " in sql
    assert f"{direction}, dim.[brand]" in sql


@pytest.mark.parametrize(
    ("original", "clarification", "answer", "expected_tail"),
    (
        (
            "Общая себестоимость товара 12345",
            "Уточните смысл «общая себестоимость»: SUM(cost) по операциям или текущий баланс cost_sum.",
            "текущий баланс",
            "текущая себестоимость",
        ),
        (
            "Средняя себестоимость товара 12345",
            "Уточните среднюю себестоимость: AVG(cost_per_unit) по операциям или взвешенную.",
            "взвешенную",
            "взвешенная",
        ),
    ),
)
def test_cost_clarification_short_answer_is_combined_with_original_question(
    original: str,
    clarification: str,
    answer: str,
    expected_tail: str,
) -> None:
    memory = SqlAgentMemory(
        conversation=[
            {"role": "user", "content": original},
            {"role": "assistant", "content": clarification},
        ]
    )

    resolved = SqlAgentService()._resolve_clarification_followup(answer, memory)

    assert resolved.startswith(original)
    assert expected_tail in resolved
