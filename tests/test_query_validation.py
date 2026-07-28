from __future__ import annotations

import pytest

from sql_agent.query_utils import extract_select_statement, validate_readonly_select_sql


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
