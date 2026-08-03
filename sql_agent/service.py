from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Callable

from sqlalchemy.exc import DBAPIError, OperationalError

from sql_agent.config import MAX_SCHEMA_CHARS, MEMORY_FILE
from sql_agent.database import DatabaseConnector
from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemory, SqlAgentMemoryRepository
from sql_agent.query_utils import (
    _mask_sql_literals_identifiers_and_comments,
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

    def ask_database(
        self,
        question: str,
        on_sql_ready: Callable[[str], None] | None = None,
        *,
        sql_override: str | None = None,
    ) -> str:
        memory = self.memory_repository.load()
        effective_question = self._resolve_clarification_followup(question, memory)
        last_sql: str | None = None

        def remember_sql(sql: str) -> None:
            nonlocal last_sql
            last_sql = sql
            if on_sql_ready is not None:
                on_sql_ready(sql)

        raw_sql = sql_override or extract_select_statement(effective_question)
        if not raw_sql:
            clarification = self.intent_parser.get_clarification(effective_question)
            if clarification:
                self._save_turn(memory, question, clarification)
                return clarification

        try:
            if raw_sql:
                engine = self.database_connector.build_engine()
                response = self._execute_raw_select(
                    engine,
                    raw_sql,
                    remember_sql,
                    generated_by_openai=sql_override is not None,
                )
            else:
                intent = self.intent_parser.parse(effective_question, memory)
                engine = self.database_connector.build_engine()
                db = SimpleNamespace(_engine=engine)
                response = self.sql_builder.execute(db, intent, on_sql_ready=remember_sql)
        except (OperationalError, DBAPIError) as exc:
            response = self._format_database_error(last_sql, exc)
        except ValueError as exc:
            response = str(exc)
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
        conversation = memory.conversation
        if len(conversation) < 2:
            return question

        last_message = conversation[-1]
        previous_message = conversation[-2]
        if last_message.get("role") != "assistant" or previous_message.get("role") != "user":
            return question

        last_content = last_message.get("content", "")
        previous_content = previous_message.get("content", "")
        lowered_answer = question.lower()
        if (
            "лучший товар считать по количеству" in last_content
            and self._is_metric_clarification_answer(question)
        ):
            return f"{previous_content} {question}".strip()
        if "общая себестоимость" in last_content.lower():
            if any(marker in lowered_answer for marker in ("текущ", "баланс", "cost_sum")):
                return f"{previous_content} текущая себестоимость".strip()
            if any(marker in lowered_answer for marker in ("sum(cost)", "операц", "сумм")):
                return f"{previous_content} сумма себестоимости операций".strip()
        if "среднюю себестоимость" in last_content.lower():
            if "взвеш" in lowered_answer:
                return f"{previous_content} взвешенная".strip()
            if any(marker in lowered_answer for marker in ("avg", "cost_per_unit", "по операциям")):
                return f"{previous_content} себестоимость единицы".strip()
        return question

    def _is_metric_clarification_answer(self, question: str) -> bool:
        lowered = question.lower()
        return any(
            marker in lowered
            for marker in (
                "по количеству",
                "количеству",
                "количество",
                "quantity",
                "по сумме",
                "сумме продаж",
                "сумма продаж",
                "сумма",
                "amount",
                "выручк",
                "оборот",
            )
        )

    def _execute_raw_select(
        self,
        engine,
        sql: str,
        on_sql_ready: Callable[[str], None] | None = None,
        *,
        generated_by_openai: bool = False,
    ) -> str:
        validate_readonly_select_sql(sql)
        if self._is_unbounded_detail_select(sql):
            raise ValueError(
                "Безлимитный подробный SELECT не выполняется в веб-чате. "
                "Добавьте TOP/OFFSET либо используйте пагинацию/экспорт."
            )
        if on_sql_ready is not None:
            on_sql_ready(sql)
        columns, rows = run_sql_query_with_columns(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(columns, rows),
            explanation_text=(
                "Выполнен read-only SELECT-запрос, сформированный OpenAI API. "
                "Результат выполнения не передавался в OpenAI API."
                if generated_by_openai
                else "Выполнен явный read-only SELECT-запрос пользователя без изменения SQL."
            ),
        )

    def _is_unbounded_detail_select(self, sql: str) -> bool:
        outer_tokens = self._top_level_sql_tokens(sql)
        if sum(token[0] == "select" for token in outer_tokens) != 1:
            return True
        select_token = next(
            (token for token in outer_tokens if token[0] == "select"),
            None,
        )
        if select_token is None:
            return True

        from_token = next(
            (
                token
                for token in outer_tokens
                if token[0] == "from" and token[1] > select_token[1]
            ),
            None,
        )
        if from_token is None:
            masked_sql = _mask_sql_literals_identifiers_and_comments(sql)
            return bool(re.search(r"\bfrom\b", masked_sql, flags=re.IGNORECASE))

        tokens_after_select = [
            token
            for token in outer_tokens
            if token[1] > select_token[1]
        ]
        if any(
            token[0] in {"union", "intersect", "except"}
            for token in tokens_after_select
        ):
            return True

        select_clause = _mask_sql_literals_identifiers_and_comments(
            sql[select_token[2] : from_token[1]]
        ).strip()
        top_match = re.match(
            r"(?is)^(?:distinct\s+|all\s+)?top\s*"
            r"(?:\(\s*(\d+)\s*\)|(\d+))"
            r"(\s+percent)?(\s+with\s+ties)?(?=\s|$)",
            select_clause,
        )
        if top_match:
            row_limit = int(top_match.group(1) or top_match.group(2))
            return bool(
                row_limit > 100
                or top_match.group(3)
                or top_match.group(4)
            )

        normalized_outer = " ".join(token[0] for token in tokens_after_select)
        fetch_match = re.search(
            r"\bfetch\s+(?:first|next)\s+(\d+)\s+rows?\s+only\b",
            normalized_outer,
        )
        if fetch_match:
            return int(fetch_match.group(1)) > 100
        if re.search(r"\boffset\b", normalized_outer):
            return True

        if re.search(r"\bover\s*\(", select_clause, flags=re.IGNORECASE):
            return True
        if re.search(r"(^|,)\s*(?:\w+\.)?\*\s*(?:,|$)", select_clause):
            return True
        if "group by" in normalized_outer:
            return True

        expressions = self._split_top_level_expressions(select_clause)
        aggregate_pattern = re.compile(
            r"\b(?:count|sum|avg|min|max)\s*\(",
            flags=re.IGNORECASE,
        )
        return not expressions or any(
            aggregate_pattern.search(expression) is None
            or re.search(r"\bselect\b", expression, flags=re.IGNORECASE)
            for expression in expressions
        )

    @staticmethod
    def _top_level_sql_tokens(sql: str) -> list[tuple[str, int, int]]:
        tokens: list[tuple[str, int, int]] = []
        depth = 0
        index = 0
        length = len(sql)
        in_single_quote = False
        in_double_quote = False
        in_brackets = False
        in_line_comment = False
        in_block_comment = False

        while index < length:
            char = sql[index]
            following = sql[index + 1] if index + 1 < length else ""

            if in_line_comment:
                if char in "\r\n":
                    in_line_comment = False
                index += 1
                continue
            if in_block_comment:
                if char == "*" and following == "/":
                    in_block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if in_single_quote:
                if char == "'" and following == "'":
                    index += 2
                elif char == "'":
                    in_single_quote = False
                    index += 1
                else:
                    index += 1
                continue
            if in_double_quote:
                if char == '"' and following == '"':
                    index += 2
                elif char == '"':
                    in_double_quote = False
                    index += 1
                else:
                    index += 1
                continue
            if in_brackets:
                if char == "]" and following == "]":
                    index += 2
                elif char == "]":
                    in_brackets = False
                    index += 1
                else:
                    index += 1
                continue

            if char == "-" and following == "-":
                in_line_comment = True
                index += 2
                continue
            if char == "/" and following == "*":
                in_block_comment = True
                index += 2
                continue
            if char == "'":
                in_single_quote = True
                index += 1
                continue
            if char == '"':
                in_double_quote = True
                index += 1
                continue
            if char == "[":
                in_brackets = True
                index += 1
                continue
            if char == "(":
                depth += 1
                index += 1
                continue
            if char == ")":
                depth = max(0, depth - 1)
                index += 1
                continue
            if depth == 0 and (char.isalnum() or char == "_"):
                start = index
                index += 1
                while index < length and (sql[index].isalnum() or sql[index] == "_"):
                    index += 1
                tokens.append((sql[start:index].lower(), start, index))
                continue
            index += 1

        return tokens

    @staticmethod
    def _split_top_level_expressions(select_clause: str) -> list[str]:
        expressions: list[str] = []
        start = 0
        depth = 0
        index = 0
        in_string = False
        while index < len(select_clause):
            char = select_clause[index]
            following = (
                select_clause[index + 1]
                if index + 1 < len(select_clause)
                else ""
            )
            if in_string:
                if char == "'" and following == "'":
                    index += 2
                    continue
                if char == "'":
                    in_string = False
            elif char == "'":
                in_string = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif char == "," and depth == 0:
                expressions.append(select_clause[start:index].strip())
                start = index + 1
            index += 1
        expressions.append(select_clause[start:].strip())
        return [expression for expression in expressions if expression]

    def _format_database_error(self, sql: str | None, exc: DBAPIError) -> str:
        if isinstance(exc, OperationalError):
            explanation = (
                "SQL был сформирован, но SQL Server недоступен или отклонил подключение. "
                "Проверьте VPN/сеть, доступность сервера и настройки SSL/сертификата ODBC."
            )
        else:
            explanation = (
                "SQL был сформирован, но база данных вернула ошибку при выполнении. "
                "Проверьте таблицы, колонки, права доступа и параметры подключения."
            )
        return format_sql_response(
            sql=sql or "-- SQL не был сформирован до ошибки подключения",
            result_text="Запрос не выполнен из-за ошибки подключения к SQL Server.",
            explanation_text=explanation,
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
