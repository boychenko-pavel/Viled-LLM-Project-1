from __future__ import annotations

import pytest

from sql_agent.query_utils import (
    MAX_WEB_CELL_BYTES,
    MAX_WEB_RESULT_BYTES,
    _read_web_safe_rows,
    extract_select_statement,
    validate_readonly_select_sql,
)


def test_extract_select_statement_preserves_leading_ctes() -> None:
    question = """запрос
WITH stock_balance AS (
    SELECT [product_id], SUM([quantity]) AS stock_quantity
    FROM [DWH].[LLM].[stock]
    GROUP BY [product_id]
), ranked_price AS (
    SELECT [ware_id] AS product_id
    FROM [DWH].[LLM].[price]
)
SELECT stock_balance.[product_id]
FROM stock_balance
INNER JOIN ranked_price
    ON stock_balance.[product_id] = ranked_price.[product_id]
"""

    extracted_sql = extract_select_statement(question)

    assert extracted_sql is not None
    assert extracted_sql.startswith("WITH stock_balance AS (")
    assert "), ranked_price AS (" in extracted_sql
    validate_readonly_select_sql(extracted_sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1;",
        "WITH values_cte AS (SELECT 1 AS value) SELECT value FROM values_cte;",
    ],
)
def test_readonly_validation_accepts_single_select_with_optional_terminator(sql: str) -> None:
    validate_readonly_select_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "WITH rows_to_delete AS (SELECT 1 AS value) DELETE FROM rows_to_delete",
    ],
)
def test_readonly_validation_still_rejects_multiple_or_mutating_statements(sql: str) -> None:
    with pytest.raises(ValueError):
        validate_readonly_select_sql(sql)


def test_web_result_reader_rejects_oversized_cell() -> None:
    oversized_text = "x" * (MAX_WEB_CELL_BYTES // 4 + 1)

    with pytest.raises(ValueError, match="ячейка"):
        _read_web_safe_rows([(oversized_text,)])


def test_web_result_reader_rejects_oversized_total_payload() -> None:
    cell = b"x" * (MAX_WEB_CELL_BYTES - 1)
    rows = [(cell,)] * (MAX_WEB_RESULT_BYTES // len(cell) + 1)

    with pytest.raises(ValueError, match="Результат"):
        _read_web_safe_rows(rows)
