from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from sql_agent.memory import SqlAgentMemoryRepository
from sql_agent.query_utils import extract_select_statement, validate_readonly_select_sql
from sql_agent.service import SqlAgentService


class SqliteDatabaseConnector:
    def __init__(self) -> None:
        self.engine = create_engine("sqlite://")

    def build_engine(self):
        return self.engine


class ClarificationTrap:
    def get_clarification(self, question: str) -> str:
        raise AssertionError("Explicit SQL must bypass semantic clarification")


def test_explicit_select_bypasses_semantic_clarification(tmp_path) -> None:
    service = SqlAgentService(
        memory_repository=SqlAgentMemoryRepository(tmp_path / "memory.json"),
        database_connector=SqliteDatabaseConnector(),
        intent_parser=ClarificationTrap(),
    )

    response = service.ask_database("SELECT 1 AS sales_and_purchases")

    assert "sales_and_purchases" in response
    assert "1" in response


def test_web_select_safety_accepts_only_bounded_details_or_scalar_aggregates() -> None:
    service = SqlAgentService()
    safe_sql = (
        "SELECT 1 AS value",
        "SELECT COUNT(*) AS row_count FROM [LLM].[sales]",
        "SELECT SUM(amount), AVG(quantity) FROM [LLM].[sales]",
        "SELECT TOP 100 *, SUM(amount) OVER () AS full_total FROM [LLM].[sales]",
        "SELECT TOP (10) product_id FROM [LLM].[sales]",
        "WITH scoped AS (SELECT * FROM [LLM].[sales]) "
        "SELECT TOP 10 * FROM scoped",
        "SELECT product_id FROM [LLM].[sales] ORDER BY product_id "
        "OFFSET 0 ROWS FETCH NEXT 100 ROWS ONLY",
    )

    for sql in safe_sql:
        assert not service._is_unbounded_detail_select(sql), sql


def test_web_select_safety_blocks_unbounded_or_oversized_details() -> None:
    service = SqlAgentService()
    unsafe_sql = (
        "SELECT * FROM [LLM].[sales]",
        "SELECT *, SUM(amount) OVER () AS full_total FROM [LLM].[sales]",
        "SELECT product_id, SUM(amount) OVER () FROM [LLM].[sales]",
        "SELECT TOP 101 * FROM [LLM].[sales]",
        "SELECT TOP 10 PERCENT * FROM [LLM].[sales]",
        "SELECT TOP 10 WITH TIES * FROM [LLM].[sales] ORDER BY amount DESC",
        "SELECT product_id FROM [LLM].[sales] ORDER BY product_id OFFSET 0 ROWS",
        "SELECT product_id FROM [LLM].[sales] ORDER BY product_id "
        "OFFSET 0 ROWS FETCH NEXT 101 ROWS ONLY",
        "SELECT product_id, SUM(amount) FROM [LLM].[sales] GROUP BY product_id",
        "SELECT TOP 10 product_id FROM [LLM].[sales] "
        "UNION ALL SELECT product_id FROM [LLM].[sales]",
        "SELECT (SELECT SUM(amount) FROM [LLM].[sales]) AS total "
        "FROM [LLM].[sales]",
        "WITH scoped AS (SELECT TOP 10 * FROM [LLM].[sales]) "
        "SELECT * FROM scoped",
    )

    for sql in unsafe_sql:
        assert service._is_unbounded_detail_select(sql), sql


@pytest.mark.parametrize(
    "sql",
    (
        "SELECT TOP 1 * INTO dbo.audit_copy FROM [LLM].[sales]",
        "WITH scoped AS (SELECT TOP 1 * FROM [LLM].[sales]) "
        "SELECT * INTO dbo.audit_copy FROM scoped",
        "SELECT NEXT VALUE FOR dbo.some_sequence AS n",
    ),
)
def test_readonly_validator_blocks_select_side_effects(sql: str) -> None:
    with pytest.raises(ValueError, match="read-only"):
        validate_readonly_select_sql(sql)


def test_readonly_validator_ignores_keywords_inside_literals_and_identifiers() -> None:
    validate_readonly_select_sql(
        "SELECT TOP 1 [update], 'drop; into' AS note FROM [LLM].[sales]"
    )


@pytest.mark.parametrize(
    "sql",
    (
        "SELECT TOP 1 1 AS ok -- harmless\nDROP TABLE dbo.should_never_run",
        "SELECT TOP 1 1 AS ok -- harmless\nDELETE FROM [LLM].[sales]",
        "SELECT TOP 1 1 FROM sys.objects\nSELECT * FROM [LLM].[sales]",
        "SELECT TOP 1 1 AS ok\nDISABLE TRIGGER ALL ON [LLM].[sales]",
        "SELECT TOP 1 1 AS ok\nDENY CONTROL ON DATABASE::[DWH] TO [some_user]",
        "SELECT TOP 1 1 AS ok\nSET NOCOUNT ON",
        "SELECT TOP 1 1 AS ok\nCHECKPOINT",
        "SELECT TOP 1 1 AS ok\nRECONFIGURE",
        "SELECT TOP 1 1 AS ok\nDUMP DATABASE DWH TO DISK = 'x'",
        "SELECT TOP 1 * FROM OPENQUERY([linked], 'SELECT 1')",
        "SELECT TOP 1 * FROM OPENROWSET('provider', 'connection', 'SELECT 1')",
        "SELECT TOP 1 * FROM OPENDATASOURCE('provider', 'connection').db.dbo.t",
    ),
)
def test_readonly_validator_preserves_comment_newlines_and_blocks_batches(
    sql: str,
) -> None:
    with pytest.raises(ValueError):
        validate_readonly_select_sql(sql)


@pytest.mark.parametrize(
    "sql",
    (
        "SELECT product_id /* COUNT( */ FROM [LLM].[sales]",
        "SELECT SUM(amount) OVER /*gap*/ () FROM [LLM].[sales]",
        "SELECT (SELECT * FROM [LLM].[sales] FOR JSON PATH) AS payload",
        "SELECT TOP 1 1 FROM sys.objects\nSELECT * FROM [LLM].[sales]",
    ),
)
def test_web_select_safety_cannot_be_bypassed_by_comments_or_nested_payloads(
    sql: str,
) -> None:
    assert SqlAgentService()._is_unbounded_detail_select(sql)


def test_select_extraction_ignores_select_inside_a_comment() -> None:
    question = "-- SELECT TOP 1 999 AS wrong\nSELECT TOP 1 1 AS right"

    assert extract_select_statement(question) == "SELECT TOP 1 1 AS right"
