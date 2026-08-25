from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory
from sql_agent.query_utils import parse_requested_limit
from sql_agent.sql_builder import SqlBuilder


def build_sql(question: str) -> tuple[object, str]:
    parser = IntentParser()
    intent = parser.parse(question, SqlAgentMemory())
    emitted_sql: list[str] = []
    with patch("sql_agent.sql_builder.run_sql_query", return_value=[]):
        SqlBuilder().execute(
            SimpleNamespace(_engine=object()),
            intent,
            on_sql_ready=emitted_sql.append,
        )
    assert len(emitted_sql) == 1
    return intent, emitted_sql[0]


@pytest.mark.parametrize(
    "question",
    ("все проданные товары", "все товары, которые были проданы", "all sold products"),
)
def test_all_sold_products_are_grouped_and_filtered_by_positive_quantity(
    question: str,
) -> None:
    intent, sql = build_sql(question)

    assert intent.operation == "aggregate"
    assert intent.domain == "sales"
    assert intent.group_by == "product_id"
    assert "SELECT TOP 100 [product_id], SUM([quantity]) AS total_quantity" in sql
    assert "GROUP BY [product_id]" in sql
    assert "HAVING SUM([quantity]) > 0" in sql


@pytest.mark.parametrize(
    ("question", "requested", "not_requested"),
    (
        ("покажи артикул товара 12345", "[article]", "[style]"),
        ("show brand for product 12345", "[brand]", "[article]"),
    ),
)
def test_explicit_product_attribute_does_not_expand_to_full_card(
    question: str,
    requested: str,
    not_requested: str,
) -> None:
    intent, sql = build_sql(question)

    assert intent.domain == "product_dimension"
    assert requested in sql
    assert not_requested not in sql
    assert "[product_id] = '12345'" in sql


def test_product_card_still_returns_documented_full_attributes() -> None:
    intent, sql = build_sql("Покажи карточку товара по артикулу G062214")

    assert intent.domain == "product_dimension"
    assert "[style]" in sql
    assert "[image_url]" in sql
    assert "[article] = 'G062214'" in sql


def test_generic_division_table_request_returns_all_dimension_columns() -> None:
    intent, sql = build_sql("покажи данные из division")

    assert intent.domain == "division_dimension"
    assert "SELECT TOP 100 [id], [division], [city]" in sql


def test_without_top_is_treated_as_an_explicit_unbounded_request() -> None:
    question = "продажи бренд Cartier за август 2026 без топ"

    assert parse_requested_limit(question) is None
    clarification = IntentParser().get_clarification(question)
    assert clarification is not None
    assert "Безлимитный вывод строк в веб-чате отключён" in clarification


def test_after_explicit_date_starts_on_the_next_calendar_day() -> None:
    intent, sql = build_sql("продажи после 2026-03-01")

    assert intent.filters.date_from == "2026-03-02"
    assert "fact.[sale_date] >= '2026-03-02'" in sql
