from __future__ import annotations

import json

from openai import APIError

from sql_agent.config import MAX_SCHEMA_CHARS, MEMORY_FILE
from sql_agent.database import DatabaseConnector, build_sqlalchemy_engine
from sql_agent.heuristics import HeuristicSqlResponder
from sql_agent.langchain_factory import LangChainSqlAgentFactory
from sql_agent.memory import SqlAgentMemory, SqlAgentMemoryRepository
from sql_agent.prompts import PromptBuilder
from sql_agent.schema import build_schema_snapshot_from_engine


class SqlAgentService:
    def __init__(
        self,
        memory_repository: SqlAgentMemoryRepository | None = None,
        database_connector: DatabaseConnector | None = None,
        agent_factory: LangChainSqlAgentFactory | None = None,
        prompt_builder: PromptBuilder | None = None,
    ):
        self.memory_repository = memory_repository or SqlAgentMemoryRepository(MEMORY_FILE)
        self.database_connector = database_connector or DatabaseConnector()
        self.agent_factory = agent_factory or LangChainSqlAgentFactory()
        self.prompt_builder = prompt_builder or PromptBuilder()

    def ask_database(self, question: str) -> str:
        memory = self.memory_repository.load()
        db = self.database_connector.build_database()

        heuristic_answer = HeuristicSqlResponder(db).answer(question)
        if heuristic_answer is not None:
            self._save_turn(memory, question, heuristic_answer)
            return heuristic_answer

        try:
            agent = self.agent_factory.build_agent(db, memory)
            result = agent.invoke({"input": self.prompt_builder.build_agent_input(memory, question)})
            assistant_message = str(result["output"])
        except APIError as exc:
            message = str(exc)
            if "context length" in message.lower() or "n_keep" in message.lower():
                assistant_message = (
                    "Не удалось обработать запрос через LLM: prompt превысил доступный контекст модели. "
                    "Попробуйте обновить schema snapshot, очистить память командой `reset-memory` "
                    "или задать более узкий запрос."
                )
            else:
                raise
        self._save_turn(memory, question, assistant_message)
        return assistant_message

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
        engine = build_sqlalchemy_engine()
        schema_snapshot = build_schema_snapshot_from_engine(engine)
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
