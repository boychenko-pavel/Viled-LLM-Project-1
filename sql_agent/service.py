from __future__ import annotations

import json
from types import SimpleNamespace

from sql_agent.config import MAX_SCHEMA_CHARS, MEMORY_FILE
from sql_agent.database import DatabaseConnector
from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory, SqlAgentMemoryRepository
from sql_agent.query_utils import (
    extract_select_statement,
    format_rows,
    format_sql_response,
    run_sql_query_with_columns,
    validate_readonly_select_sql,
)
from sql_agent.schema import build_schema_snapshot_from_engine
from sql_agent.sql_builder import SqlBuilder


class SqlAgentService:
    def __init__(
        self,
        memory_repository: SqlAgentMemoryRepository | None = None,
        database_connector: DatabaseConnector | None = None,
        intent_parser: IntentParser | None = None,
        sql_builder: SqlBuilder | None = None,
    ):
        self.memory_repository = memory_repository or SqlAgentMemoryRepository(MEMORY_FILE)
        self.database_connector = database_connector or DatabaseConnector()
        self.intent_parser = intent_parser or IntentParser()
        self.sql_builder = sql_builder or SqlBuilder()

    def ask_database(self, question: str) -> str:
        memory = self.memory_repository.load()
        effective_question = self._resolve_clarification_followup(question, memory)

        clarification = self.intent_parser.get_clarification(effective_question)
        if clarification:
            self._save_turn(memory, question, clarification)
            return clarification

        raw_sql = extract_select_statement(effective_question)
        if raw_sql:
            engine = self.database_connector.build_engine()
            response = self._execute_raw_select(engine, raw_sql)
        else:
            intent = self.intent_parser.parse(effective_question, memory)
            engine = self.database_connector.build_engine()
            db = SimpleNamespace(_engine=engine)
            response = self.sql_builder.execute(db, intent)
        self._save_turn(memory, question, response)
        return response

    def add_instruction(self, instruction: str) -> str:
        memory = self.memory_repository.load()
        memory.add_instruction(instruction)
        self.memory_repository.save(memory)
        return "Instruction saved to agent memory."

    def reset_memory(self) -> str:
        self.memory_repository.save(SqlAgentMemory())
        return "Agent memory cleared."

    def update_schema_memory(self) -> str:
        memory = self.memory_repository.load()
        db = self.database_connector.build_database()
        schema_snapshot = build_schema_snapshot_from_engine(db._engine)
        if len(schema_snapshot) > MAX_SCHEMA_CHARS:
            schema_snapshot = schema_snapshot[:MAX_SCHEMA_CHARS] + "\n\n[Schema truncated]"
        memory.schema_snapshot = schema_snapshot
        self.memory_repository.save(memory)
        return "Database schema snapshot refreshed."

    def show_memory(self) -> str:
        memory = self.memory_repository.load()
        return json.dumps(
            {
                "instructions": memory.instructions,
                "conversation": memory.conversation,
                "schema_snapshot": memory.schema_snapshot,
            },
            ensure_ascii=False,
            indent=2,
        )

    def _save_turn(self, memory: SqlAgentMemory, question: str, answer: str) -> None:
        memory.add_turn(question, answer)
        self.memory_repository.save(memory)

    def _resolve_clarification_followup(
        self,
        question: str,
        memory: SqlAgentMemory,
    ) -> str:
        if not self._is_metric_clarification_answer(question):
            return question

        conversation = memory.conversation
        if len(conversation) < 2:
            return question

        last_message = conversation[-1]
        previous_message = conversation[-2]
        if last_message.get("role") != "assistant" or previous_message.get("role") != "user":
            return question

        last_content = last_message.get("content", "")
        if "лучший товар считать по количеству" not in last_content:
            return question

        return f"{previous_message.get('content', '')} {question}".strip()

    def _is_metric_clarification_answer(self, question: str) -> bool:
        lowered = question.lower()
        return any(
            marker in lowered
            for marker in (
                "по количеству",
                "количеству",
                "quantity",
                "по сумме",
                "сумме продаж",
                "сумма продаж",
                "amount",
                "выручк",
                "оборот",
            )
        )

    def _execute_raw_select(self, engine, sql: str) -> str:
        validate_readonly_select_sql(sql)
        columns, rows = run_sql_query_with_columns(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(columns, rows),
            explanation_text="Выполнен явный read-only SELECT-запрос пользователя без изменения SQL.",
        )


def ask_database(question: str) -> str:
    return SqlAgentService().ask_database(question)


def add_instruction(instruction: str) -> str:
    return SqlAgentService().add_instruction(instruction)


def reset_memory() -> str:
    return SqlAgentService().reset_memory()


def update_schema_memory() -> str:
    return SqlAgentService().update_schema_memory()


def show_memory() -> str:
    return SqlAgentService().show_memory()
