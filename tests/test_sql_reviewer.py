from __future__ import annotations

from types import SimpleNamespace

import pytest

from sql_agent.sql_reviewer import (
    OPENAI_UNAVAILABLE_PREFIX,
    OpenAIUnavailableError,
    OpenAISqlReviewer,
    REVIEW_SUCCESS_MESSAGE,
    SqlGenerationDecision,
    SqlReviewDecision,
)


class FakeResponses:
    def __init__(
        self,
        decision: SqlReviewDecision | SqlGenerationDecision | None = None,
        error: Exception | None = None,
    ):
        self.decision = decision
        self.error = error
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(output_parsed=self.decision)


def build_reviewer(responses: FakeResponses) -> OpenAISqlReviewer:
    return OpenAISqlReviewer(
        client=SimpleNamespace(responses=responses),
        enabled=True,
        context_files=(),
    )


def test_approved_sql_returns_required_success_message() -> None:
    responses = FakeResponses(SqlReviewDecision(status="approved", suggested_sql=""))

    result = build_reviewer(responses).review("Покажи продажи", "SELECT TOP 100 * FROM [LLM].[sales]")

    assert result == REVIEW_SUCCESS_MESSAGE
    assert responses.kwargs["store"] is False
    assert responses.kwargs["model"] == "gpt-5.6"
    assert responses.kwargs["reasoning"] == {"effort": "medium"}
    assert responses.kwargs["service_tier"] == "default"
    assert "tools" not in responses.kwargs
    assert "Result:" not in str(responses.kwargs["input"])


def test_review_uses_selected_model_reasoning_and_speed() -> None:
    responses = FakeResponses(SqlReviewDecision(status="approved", suggested_sql=""))

    build_reviewer(responses).review(
        "Проверь SQL",
        "SELECT 1",
        model="gpt-5.6-luna",
        reasoning_effort="low",
        service_tier="priority",
    )

    assert responses.kwargs["model"] == "gpt-5.6-luna"
    assert responses.kwargs["reasoning"] == {"effort": "low"}
    assert responses.kwargs["service_tier"] == "priority"


def test_rejected_sql_returns_corrected_readonly_select() -> None:
    responses = FakeResponses(
        SqlReviewDecision(
            status="rejected",
            suggested_sql="SELECT TOP 100 product_id FROM [LLM].[sales]",
        )
    )

    result = build_reviewer(responses).review("Покажи товары", "SELECT 1")

    assert "SQL-запрос неверен по смыслу." in result
    assert "SELECT TOP 100 product_id FROM [LLM].[sales]" in result


def test_missing_api_key_reports_unavailable_reason() -> None:
    reviewer = OpenAISqlReviewer(enabled=True, api_key="", context_files=())

    assert reviewer.review("Покажи продажи", "SELECT 1") == (
        "OpenAI API не доступен: не задан OPENAI_API_KEY"
    )


def test_missing_api_key_blocks_sql_generation() -> None:
    reviewer = OpenAISqlReviewer(enabled=True, api_key="", context_files=())

    with pytest.raises(
        OpenAIUnavailableError,
        match="OpenAI API не доступен: не задан OPENAI_API_KEY",
    ):
        reviewer.generate("Покажи продажи")


def test_api_error_reports_safe_reason() -> None:
    reviewer = build_reviewer(FakeResponses(error=RuntimeError("quota exhausted")))

    result = reviewer.review("Покажи продажи", "SELECT 1")

    assert result.startswith(OPENAI_UNAVAILABLE_PREFIX)
    assert "RuntimeError" in result
    assert "quota exhausted" not in result


def test_unsafe_correction_is_not_shown() -> None:
    responses = FakeResponses(
        SqlReviewDecision(status="rejected", suggested_sql="DELETE FROM [LLM].[sales]")
    )

    result = build_reviewer(responses).review("Удали продажи", "SELECT 1")

    assert "Проверка SQL не выполнена" in result
    assert "DELETE" not in result


def test_generate_returns_validated_sql_without_tools_or_results() -> None:
    responses = FakeResponses(
        SqlGenerationDecision(sql="SELECT TOP 10 product_id FROM [LLM].[sales]")
    )

    sql = build_reviewer(responses).generate(
        "Покажи последние товары",
        model="gpt-5.6-terra",
        reasoning_effort="low",
        service_tier="priority",
    )

    assert sql == "SELECT TOP 10 product_id FROM [LLM].[sales]"
    assert responses.kwargs["store"] is False
    assert responses.kwargs["model"] == "gpt-5.6-terra"
    assert responses.kwargs["reasoning"] == {"effort": "low"}
    assert responses.kwargs["service_tier"] == "priority"
    assert "tools" not in responses.kwargs
    request_text = str(responses.kwargs["input"])
    assert "Покажи последние товары" in request_text
    assert "Result:" not in request_text


@pytest.mark.parametrize(
    ("generated_sql", "expected_sql"),
    [
        ("SELECT 1;", "SELECT 1"),
        ("```sql\nSELECT 1;\n```", "SELECT 1"),
        (
            "WITH totals AS (SELECT SUM(amount) AS amount FROM [LLM].[sales]) "
            "SELECT amount FROM totals;",
            "WITH totals AS (SELECT SUM(amount) AS amount FROM [LLM].[sales]) "
            "SELECT amount FROM totals",
        ),
    ],
)
def test_generate_normalizes_safe_sql(
    generated_sql: str,
    expected_sql: str,
) -> None:
    responses = FakeResponses(SqlGenerationDecision(sql=generated_sql))

    assert build_reviewer(responses).generate("Рассчитай продажи") == expected_sql
