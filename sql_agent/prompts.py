from __future__ import annotations

from langchain_community.utilities.sql_database import SQLDatabase

from sql_agent.config import (
    MAX_HISTORY_CHARS,
    MAX_HISTORY_MESSAGES,
    MAX_INSTRUCTIONS_CHARS,
    MAX_PROMPT_SCHEMA_CHARS,
)
from sql_agent.memory import SqlAgentMemory
from sql_agent.schema import refresh_schema_snapshot


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "\n[Truncated]"


def build_system_prompt(memory: SqlAgentMemory, db: SQLDatabase) -> str:
    if not memory.schema_snapshot:
        refresh_schema_snapshot(db, memory)

    instructions_block = "\n".join(
        f"{index}. {instruction}" for index, instruction in enumerate(memory.instructions, start=1)
    )
    if not instructions_block:
        instructions_block = "No saved user instructions yet."
    instructions_block = _truncate_text(instructions_block, MAX_INSTRUCTIONS_CHARS)
    schema_snapshot = _truncate_text(memory.schema_snapshot, MAX_PROMPT_SCHEMA_CHARS)

    return f"""
You are a SQL assistant for Microsoft SQL Server.
Answer in Russian.

Main goal:
- Convert the user's request into a correct SQL query and execute it with tools.

Rules:
- SQL dialect: {{dialect}}
- Use only SELECT queries and CTEs.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, EXEC.
- Unless the user asks for more, return at most {{top_k}} rows.
- Always check SQL with sql_db_query_checker before sql_db_query.

Work strategy:
- Do not ask clarifying questions if you can answer by inspecting the schema or trying a safe read-only query.
- First use sql_db_list_tables when the table is uncertain.
- Use sql_db_schema to inspect the most relevant tables.
- Build the SQL, check it, run it, then give a short final answer.
- Always show the final SQL script before the answer.
- If the user names columns or a table, trust that hint and proceed.
- If a request says "latest" or "last", prefer ORDER BY date-like columns DESC.
- If the exact table is unclear, choose the closest matching table from schema and continue.
- Only ask a clarifying question when several materially different interpretations are equally plausible.

Saved instructions:
{instructions_block}

Database schema snapshot:
{schema_snapshot}
""".strip()


def build_agent_input(memory: SqlAgentMemory, user_message: str) -> str:
    history_lines = []
    for item in memory.conversation[-MAX_HISTORY_MESSAGES:]:
        role = item.get("role", "user").upper()
        content = item.get("content", "")
        history_lines.append(f"{role}: {content}")

    history_block = "\n".join(history_lines) if history_lines else "No prior conversation."
    history_block = _truncate_text(history_block, MAX_HISTORY_CHARS)
    return (
        "Conversation history:\n"
        f"{history_block}\n\n"
        "Current user request:\n"
        f"{user_message}\n\n"
        "Important: Prefer taking tool actions over asking the user for clarification."
    )


class PromptBuilder:
    def build_system_prompt(self, memory: SqlAgentMemory, db: SQLDatabase) -> str:
        return build_system_prompt(memory, db)

    def build_agent_input(self, memory: SqlAgentMemory, user_message: str) -> str:
        return build_agent_input(memory, user_message)
