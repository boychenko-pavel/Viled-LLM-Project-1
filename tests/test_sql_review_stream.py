from __future__ import annotations

import json

from sql_agent.sql_reviewer import OpenAIUnavailableError
from sql_agent.web import WebSqlAgent


class FakeLocalSqlService:
    def ask_database(self, question: str, on_sql_ready=None, *, sql_override=None) -> str:
        assert question == "Покажи продажи"
        assert sql_override is None
        on_sql_ready("SELECT TOP 100 * FROM [LLM].[sales]")
        return (
            "SQL:\nSELECT TOP 100 * FROM [LLM].[sales]\n\n"
            "Result:\nproduct_id\n1"
        )


class FakeSqlReviewer:
    def review(self, question: str, sql: str, **settings) -> str:
        assert question == "Покажи продажи"
        assert sql == "SELECT TOP 100 * FROM [LLM].[sales]"
        assert settings == {
            "model": "gpt-5.6-terra",
            "reasoning_effort": "high",
            "service_tier": "priority",
        }
        return (
            "SQL-запрос неверен по смыслу.\n\n"
            "Предлагаемый SQL-запрос:\n"
            "SELECT TOP 10 product_id FROM [LLM].[sales]"
        )


def test_check_mode_reviews_sql_created_locally() -> None:
    agent = WebSqlAgent(
        service=FakeLocalSqlService(),
        sql_reviewer=FakeSqlReviewer(),
    )

    events = [
        json.loads(line)
        for line in agent.stream(
            "Покажи продажи",
            openai_model="gpt-5.6-terra",
            reasoning_effort="high",
            service_tier="priority",
            sql_calculation_enabled=False,
            sql_check_mode_enabled=True,
        )
    ]

    assert [event["event"] for event in events] == ["sql", "sql_review", "answer"]
    assert events[1]["mode"] == "check"
    assert "SELECT TOP 10 product_id" in events[1]["review"]
    assert events[0]["sql"] == "SELECT TOP 100 *\nFROM [LLM].[sales]"
    assert "SELECT TOP 10 product_id" not in events[2]["answer"]
    assert all(event["duration_seconds"] >= 0 for event in events)


def test_calculation_mode_uses_openai_sql_and_skips_review() -> None:
    generated_sql = "SELECT TOP 10 product_id FROM [LLM].[sales]"

    class GeneratorOnly:
        def generate(self, question: str, **settings) -> str:
            assert question == "Покажи продажи"
            assert settings["model"] == "gpt-5.6-luna"
            return generated_sql

        def review(self, *args, **kwargs) -> str:
            raise AssertionError("Generated OpenAI SQL must not be reviewed again.")

    class GeneratedSqlService:
        def ask_database(self, question, on_sql_ready=None, *, sql_override=None):
            assert question == "Покажи продажи"
            assert sql_override == generated_sql
            assert on_sql_ready is None
            return f"SQL:\n{sql_override}\n\nResult:\nproduct_id\n1"

    agent = WebSqlAgent(
        service=GeneratedSqlService(),
        sql_reviewer=GeneratorOnly(),
    )

    events = [
        json.loads(line)
        for line in agent.stream(
            "Покажи продажи",
            openai_model="gpt-5.6-luna",
            sql_calculation_enabled=True,
            sql_check_mode_enabled=True,
        )
    ]

    assert [event["event"] for event in events] == ["sql", "sql_review", "answer"]
    assert events[1]["mode"] == "calculation"
    assert "сформирован OpenAI API" in events[1]["review"]
    assert generated_sql in events[2]["answer"]
    assert all(event["duration_seconds"] >= 0 for event in events)


def test_calculation_mode_emits_sql_before_waiting_for_execution_lock() -> None:
    generated_sql = "SELECT TOP 10 product_id FROM [LLM].[sales]"

    class GeneratorOnly:
        def generate(self, *args, **kwargs) -> str:
            return generated_sql

    class GeneratedSqlService:
        def ask_database(self, *args, **kwargs):
            return f"SQL:\n{generated_sql}\n\nResult:\nproduct_id\n1"

    agent = WebSqlAgent(
        service=GeneratedSqlService(),
        sql_reviewer=GeneratorOnly(),
    )
    stream = agent.stream(
        "show sales",
        sql_calculation_enabled=True,
    )

    agent._lock.acquire()
    try:
        first_event = json.loads(next(stream))
        second_event = json.loads(next(stream))
        assert first_event["event"] == "sql"
        assert first_event["sql"] == "SELECT TOP 10 product_id\nFROM [LLM].[sales]"
        assert second_event["event"] == "sql_review"
    finally:
        agent._lock.release()

    assert json.loads(next(stream))["event"] == "answer"


def test_openai_unavailable_reports_reason_without_running_sql() -> None:
    class UnavailableGenerator:
        def generate(self, *args, **kwargs) -> str:
            raise OpenAIUnavailableError("не задан OPENAI_API_KEY")

    class NoSqlExecution:
        def ask_database(self, *args, **kwargs):
            raise AssertionError("SQL must not run when OpenAI generation failed.")

    agent = WebSqlAgent(
        service=NoSqlExecution(),
        sql_reviewer=UnavailableGenerator(),
    )

    events = [
        json.loads(line)
        for line in agent.stream(
            "Покажи продажи",
            sql_calculation_enabled=True,
        )
    ]

    assert [event["event"] for event in events] == ["sql", "sql_review", "answer"]
    assert events[1]["mode"] == "calculation"
    assert events[1]["review"] == "OpenAI API не доступен: не задан OPENAI_API_KEY"
    assert "Запрос не выполнен" in events[2]["answer"]
    assert all(event["duration_seconds"] >= 0 for event in events)


def test_both_modes_disabled_use_only_local_sql_agent() -> None:
    class NoOpenAI:
        def generate(self, *args, **kwargs):
            raise AssertionError("OpenAI generation must not run.")

        def review(self, *args, **kwargs):
            raise AssertionError("OpenAI review must not run.")

    agent = WebSqlAgent(
        service=FakeLocalSqlService(),
        sql_reviewer=NoOpenAI(),
    )

    events = [
        json.loads(line)
        for line in agent.stream(
            "Покажи продажи",
            sql_calculation_enabled=False,
            sql_check_mode_enabled=False,
        )
    ]

    assert [event["event"] for event in events] == ["sql", "sql_review", "answer"]
    assert events[1]["event"] == "sql_review"
    assert events[1]["review"] == "Проверка отключена"
    assert events[1]["mode"] == "disabled"
    assert events[1]["duration_seconds"] >= 0
