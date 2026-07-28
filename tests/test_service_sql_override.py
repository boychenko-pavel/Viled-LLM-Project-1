from __future__ import annotations

from sqlalchemy import create_engine

from sql_agent.memory import SqlAgentMemoryRepository
from sql_agent.service import SqlAgentService


class SqliteDatabaseConnector:
    def __init__(self) -> None:
        self.engine = create_engine("sqlite://")

    def build_engine(self):
        return self.engine


def test_openai_sql_override_is_executed_without_changing_user_question(tmp_path) -> None:
    memory_repository = SqlAgentMemoryRepository(tmp_path / "memory.json")
    service = SqlAgentService(
        memory_repository=memory_repository,
        database_connector=SqliteDatabaseConnector(),
    )
    emitted_sql = []

    response = service.ask_database(
        "Покажи единицу",
        on_sql_ready=emitted_sql.append,
        sql_override="SELECT 1 AS value",
    )

    assert emitted_sql == ["SELECT 1 AS value"]
    assert "1" in response
    assert "Результат выполнения не передавался в OpenAI API" in response
    assert memory_repository.load().conversation[0]["content"] == "Покажи единицу"
