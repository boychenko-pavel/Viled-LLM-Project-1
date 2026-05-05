from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, quote_plus

import pyodbc
from dotenv import dotenv_values
from langchain_community.agent_toolkits.sql.base import create_sql_agent
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_openai import ChatOpenAI
from sqlalchemy import create_engine, inspect, text


ENV_FILE = Path(r"C:\Users\p.boychenko\secrets\SQL_Password.env")
MEMORY_DIR = Path(__file__).resolve().parent / ".agent_memory"
MEMORY_FILE = MEMORY_DIR / "sql_agent_memory.json"
REQUIRED_KEYS = ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME")
LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
LM_STUDIO_MODEL = "llama-3.2-3b-instruct"
MAX_HISTORY_MESSAGES = 12
MAX_SCHEMA_CHARS = 18000
DEFAULT_PREVIEW_ROWS = 10
CURRENCY_ALIAS_MAP = {
    "usd": "full_retail_price_usd",
    "dol": "full_retail_price_usd",
    "dollar": "full_retail_price_usd",
    "dollars": "full_retail_price_usd",
    "\u0434\u043e\u043b": "full_retail_price_usd",
    "\u0434\u043e\u043b\u043b\u0430\u0440": "full_retail_price_usd",
    "\u0434\u043e\u043b\u043b\u0430\u0440\u044b": "full_retail_price_usd",
    "kzt": "full_retail_price_kzt",
    "nyu": "full_retail_price_kzt",
    "tenge": "full_retail_price_kzt",
    "\u0442\u0435\u043d\u0433\u0435": "full_retail_price_kzt",
    "eur": "full_retail_price_eur",
    "euro": "full_retail_price_eur",
    "\u0435\u0432\u0440\u043e": "full_retail_price_eur",
}


@dataclass
class SqlAgentMemory:
    instructions: list[str] = field(default_factory=list)
    conversation: list[dict[str, str]] = field(default_factory=list)
    schema_snapshot: str = ""

    @classmethod
    def load(cls, memory_path: Path) -> "SqlAgentMemory":
        if not memory_path.exists():
            return cls()

        data = json.loads(memory_path.read_text(encoding="utf-8"))
        conversation = [
            item
            for item in list(data.get("conversation", []))
            if str(item.get("content", "")).strip()
        ]
        return cls(
            instructions=list(data.get("instructions", [])),
            conversation=conversation,
            schema_snapshot=str(data.get("schema_snapshot", "")),
        )

    def save(self, memory_path: Path) -> None:
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned_conversation = [
            item
            for item in self.conversation[-MAX_HISTORY_MESSAGES:]
            if item.get("content", "").strip()
        ]
        payload = {
            "instructions": self.instructions,
            "conversation": cleaned_conversation,
            "schema_snapshot": self.schema_snapshot,
        }
        memory_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_instruction(self, instruction: str) -> None:
        cleaned = instruction.strip()
        if cleaned:
            self.instructions.append(cleaned)

    def add_turn(self, user_message: str, assistant_message: str) -> None:
        user_message = user_message.strip()
        assistant_message = assistant_message.strip()
        if user_message:
            self.conversation.append({"role": "user", "content": user_message})
        if assistant_message:
            self.conversation.append({"role": "assistant", "content": assistant_message})
        self.conversation = self.conversation[-MAX_HISTORY_MESSAGES:]


def load_db_config(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        raise FileNotFoundError(f"Secrets file not found: {env_path}")

    config = {key: (value or "").strip() for key, value in dotenv_values(env_path).items()}
    for key, value in os.environ.items():
        if key.startswith("DB_") and value:
            config[key] = value.strip()
    missing_keys = [key for key in REQUIRED_KEYS if not config.get(key)]
    if missing_keys:
        raise ValueError(
            "Missing values in SQL_Password.env: " + ", ".join(missing_keys)
        )

    return config


def escape_odbc_value(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def build_pyodbc_engine(config: dict[str, str]):
    available_drivers = pyodbc.drivers()
    preferred_driver = config.get("DB_DRIVER", "").strip()
    driver_candidates = [preferred_driver] if preferred_driver else []
    driver_candidates.extend(
        [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "SQL Server",
        ]
    )
    driver = next(
        (
            item
            for item in driver_candidates
            if item in available_drivers
        ),
        None,
    )
    if not driver:
        raise RuntimeError(
            "ODBC driver for SQL Server was not found. Install ODBC Driver 17 or 18 for SQL Server."
        )

    encrypt_settings = config.get("DB_ODBC_ENCRYPT_SETTINGS", "").strip()
    if not encrypt_settings:
        encrypt_settings = (
            "Encrypt=yes;TrustServerCertificate=yes;"
            if driver == "ODBC Driver 18 for SQL Server"
            else "Encrypt=no;"
        )

    server = config["DB_HOST"]
    if config.get("DB_PORT"):
        server = f"{server},{config['DB_PORT']}"
    connection_string = (
        f"DRIVER={escape_odbc_value(driver)};"
        f"SERVER={escape_odbc_value(server)};"
        f"DATABASE={escape_odbc_value(config['DB_NAME'])};"
        f"UID={escape_odbc_value(config['DB_USER'])};"
        f"PWD={escape_odbc_value(config['DB_PASSWORD'])};"
        f"{encrypt_settings}"
    )

    return create_engine(
        f"mssql+pyodbc:///?odbc_connect={quote_plus(connection_string)}",
        pool_pre_ping=True,
    )


def build_pymssql_engine(config: dict[str, str]):
    if importlib.util.find_spec("pymssql") is None:
        raise RuntimeError(
            "pymssql is not installed. Install it with: python -m pip install pymssql"
        )

    port = config.get("DB_PORT", "").strip()
    host = config["DB_HOST"]
    if port:
        host = f"{host}:{port}"

    return create_engine(
        "mssql+pymssql://"
        f"{quote(config['DB_USER'])}:{quote(config['DB_PASSWORD'])}"
        f"@{host}/{quote(config['DB_NAME'])}",
        pool_pre_ping=True,
    )


def build_sqlalchemy_engine(config: dict[str, str] | None = None):
    config = config or load_db_config(ENV_FILE)
    driver_mode = config.get("DB_DRIVER_MODE", "pyodbc").strip().lower()

    if driver_mode == "pymssql":
        return build_pymssql_engine(config)

    return build_pyodbc_engine(config)


def build_database() -> SQLDatabase:
    config = load_db_config(ENV_FILE)
    driver_mode = config.get("DB_DRIVER_MODE", "pyodbc").strip().lower()

    if driver_mode == "pymssql":
        engine = build_pymssql_engine(config)
        return SQLDatabase(engine=engine, sample_rows_in_table_info=2)

    pyodbc_engine = build_pyodbc_engine(config)
    try:
        return SQLDatabase(engine=pyodbc_engine, sample_rows_in_table_info=2)
    except Exception as exc:
        if importlib.util.find_spec("pymssql") is not None:
            pymssql_engine = build_pymssql_engine(config)
            return SQLDatabase(engine=pymssql_engine, sample_rows_in_table_info=2)
        raise RuntimeError(
            "Failed to connect to SQL Server through pyodbc while reading database metadata. "
            "Install pymssql and set DB_DRIVER_MODE=pymssql in "
            f"{ENV_FILE} to try the fallback driver. Original error: {exc}"
        ) from exc


def build_schema_snapshot_from_engine(engine) -> str:
    inspector = inspect(engine)
    schema_lines = []
    visible_tables = []

    for schema_name in inspector.get_schema_names():
        if schema_name.lower() in {
            "information_schema",
            "sys",
            "guest",
            "db_owner",
            "db_accessadmin",
            "db_securityadmin",
            "db_ddladmin",
            "db_backupoperator",
            "db_datareader",
            "db_datawriter",
            "db_denydatareader",
            "db_denydatawriter",
        }:
            continue

        try:
            table_names = inspector.get_table_names(schema=schema_name)
        except Exception:
            continue

        for table_name in table_names:
            visible_tables.append(f"{schema_name}.{table_name}")
            columns = inspector.get_columns(table_name, schema=schema_name)
            column_defs = ", ".join(
                f"{column['name']} ({column.get('type', 'unknown')})"
                for column in columns
            )
            schema_lines.append(f"{schema_name}.{table_name}: {column_defs}")

    table_names = ", ".join(sorted(visible_tables))
    table_info = "\n".join(schema_lines)
    return f"Tables:\n{table_names}\n\nSchema:\n{table_info}".strip()


def refresh_schema_snapshot(db: SQLDatabase, memory: SqlAgentMemory) -> str:
    schema_snapshot = build_schema_snapshot_from_engine(db._engine)
    if len(schema_snapshot) > MAX_SCHEMA_CHARS:
        schema_snapshot = schema_snapshot[:MAX_SCHEMA_CHARS] + "\n\n[Schema truncated]"
    memory.schema_snapshot = schema_snapshot
    return schema_snapshot


def build_system_prompt(memory: SqlAgentMemory, db: SQLDatabase) -> str:
    if not memory.schema_snapshot:
        refresh_schema_snapshot(db, memory)

    instructions_block = "\n".join(
        f"{index}. {instruction}" for index, instruction in enumerate(memory.instructions, start=1)
    )
    if not instructions_block:
        instructions_block = "No saved user instructions yet."

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
{memory.schema_snapshot}
""".strip()


def build_agent_input(memory: SqlAgentMemory, user_message: str) -> str:
    history_lines = []
    for item in memory.conversation[-MAX_HISTORY_MESSAGES:]:
        role = item.get("role", "user").upper()
        content = item.get("content", "")
        history_lines.append(f"{role}: {content}")

    history_block = "\n".join(history_lines) if history_lines else "No prior conversation."
    return (
        "Conversation history:\n"
        f"{history_block}\n\n"
        "Current user request:\n"
        f"{user_message}\n\n"
        "Important: Prefer taking tool actions over asking the user for clarification."
    )


def normalize_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def run_sql_query(engine, sql: str) -> list[tuple]:
    with engine.connect() as connection:
        result = connection.execute(text(sql))
        return result.fetchall()


def format_rows(columns: list[str], rows: list[tuple]) -> str:
    if not rows:
        return "No rows found."

    lines = [", ".join(columns)]
    for row in rows:
        lines.append(", ".join(str(value) for value in row))
    return "\n".join(lines)


def format_sql_response(sql: str, result_text: str, explanation_text: str) -> str:
    return (
        f"SQL:\n{sql}\n\n"
        f"Result:\n{result_text}\n\n"
        f"Explanation:\n{explanation_text}"
    )


def extract_table_name(question: str, known_tables: list[str]) -> str | None:
    lowered_question = question.lower()
    for table_name in sorted(known_tables, key=len, reverse=True):
        if table_name.lower() in lowered_question:
            return table_name

    match = re.search(r"table\s+([a-zA-Z0-9_\.\[\]]+)", question, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip("[]")
    match = re.search(r"\u0442\u0430\u0431\u043b\u0438\u0446[\u0430\u044b]?\s+([a-zA-Z0-9_\.\[\]]+)", question, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip("[]")
    match = re.search(r"\b([a-zA-Z][a-zA-Z0-9_]{2,})\b", question)
    if match:
        return match.group(1)
    return None


def is_schema_question(question: str) -> bool:
    lowered = question.lower()
    schema_keywords = (
        "\u043a\u0430\u043a\u0438\u0435 \u0441\u0442\u043e\u043b\u0431\u0446\u044b",
        "\u043a\u0430\u043a\u0438\u0435 \u043a\u043e\u043b\u043e\u043d\u043a\u0438",
        "\u043a\u0430\u043a\u0438\u0435 \u043f\u043e\u043b\u044f",
        "columns",
        "schema",
        "\u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440",
        "\u043a\u043e\u043b\u043e\u043d\u043a\u0438",
        "\u0441\u0442\u043e\u043b\u0431\u0446\u044b",
        "\u043f\u043e\u043b\u044f \u0442\u0430\u0431\u043b\u0438\u0446\u044b",
    )
    return any(keyword in lowered for keyword in schema_keywords)


def is_preview_question(question: str) -> bool:
    lowered = question.lower()
    preview_keywords = (
        "\u043f\u043e\u043a\u0430\u0436\u0438",
        "\u043f\u043e\u043a\u0430\u0437\u0430\u0442\u044c",
        "\u043f\u043e\u0441\u043b\u0435\u0434\u043d",
        "latest",
        "last",
        "recent",
        "\u0437\u0430\u043f\u0438\u0441",
        "\u0441\u0442\u0440\u043e\u043a",
        "rows",
    )
    return any(keyword in lowered for keyword in preview_keywords)


def is_aggregate_question(question: str) -> bool:
    lowered = question.lower()
    aggregate_keywords = (
        "\u0441\u043a\u043e\u043b\u044c\u043a\u043e",
        "count",
        "\u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e",
        "\u043c\u0430\u043a\u0441\u0438\u043c",
        "\u043c\u0438\u043d\u0438\u043c",
        "average",
        "avg",
        "\u0441\u0440\u0435\u0434\u043d",
        "sum",
        "\u0441\u0443\u043c\u043c",
        "\u0438\u0442\u043e\u0433\u043e",
        "group by",
        "\u043f\u043e \u0434\u0430\u0442\u0435",
        "\u043f\u043e \u0442\u043e\u0432\u0430\u0440\u0430",
        "\u043f\u043e ware_id",
    )
    return any(keyword in lowered for keyword in aggregate_keywords)


def parse_requested_limit(question: str, default_limit: int = DEFAULT_PREVIEW_ROWS) -> int:
    match = re.search(r"\b(\d+)\b", question)
    if not match:
        return default_limit
    return max(1, min(int(match.group(1)), 1000))


def get_table_columns(inspector, schema_name: str, table_name: str) -> list[str]:
    return [column["name"] for column in inspector.get_columns(table_name, schema=schema_name)]


def extract_column_name(question: str, columns: list[str]) -> str | None:
    lowered_question = question.lower()
    for column_name in sorted(columns, key=len, reverse=True):
        if column_name.lower() in lowered_question:
            return column_name

    for alias, column_name in CURRENCY_ALIAS_MAP.items():
        if alias in lowered_question and column_name in columns:
            return column_name
    return None


def parse_ware_id_filter(question: str) -> str | None:
    match = re.search(r"ware_id\s*[=:]?\s*([A-Za-z0-9_-]+)", question, flags=re.IGNORECASE)
    if match:
        return match.group(1)

    match = re.search(
        r"(?:товар[ауом]?|товары|для\s+товара|у\s+товара)\s+([A-Za-z0-9_-]+)",
        question,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return None


def parse_date_filters(question: str) -> list[tuple[str, str]]:
    filters: list[tuple[str, str]] = []
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", question)
    if len(dates) >= 2:
        filters.append(("between", dates[0]))
        filters.append(("between_end", dates[1]))
        return filters
    if len(dates) == 1:
        filters.append(("eq", dates[0]))

    return filters


def parse_numeric_threshold(question: str) -> tuple[str, str] | None:
    match = re.search(r"(?:выше|больше|more than|greater than)\s+(\d+(?:\.\d+)?)", question, flags=re.IGNORECASE)
    if match:
        return (">", match.group(1))

    match = re.search(r"(?:ниже|меньше|less than)\s+(\d+(?:\.\d+)?)", question, flags=re.IGNORECASE)
    if match:
        return ("<", match.group(1))
    return None


def find_table_reference(engine, question: str) -> tuple[str, str] | None:
    inspector = inspect(engine)
    candidates: list[tuple[str, str]] = []
    for schema_name in inspector.get_schema_names():
        if schema_name.lower() in {"information_schema", "sys"}:
            continue
        try:
            table_names = inspector.get_table_names(schema=schema_name)
        except Exception:
            continue
        for table_name in table_names:
            candidates.append((schema_name, table_name))

    lowered_question = question.lower()
    for schema_name, table_name in sorted(candidates, key=lambda item: len(item[1]), reverse=True):
        qualified_name = f"{schema_name}.{table_name}".lower()
        if table_name.lower() in lowered_question or qualified_name in lowered_question:
            return schema_name, table_name
    return None


def build_where_clause(question: str, columns: list[str]) -> str:
    filters = []
    ware_id_value = parse_ware_id_filter(question)
    if ware_id_value and "ware_id" in columns:
        safe_value = ware_id_value.replace("'", "''")
        filters.append(f"[ware_id] = '{safe_value}'")

    if "price_date" in columns:
        date_filters = parse_date_filters(question)
        filter_map = {key: value for key, value in date_filters}
        if "between" in filter_map and "between_end" in filter_map:
            filters.append(
                f"[price_date] BETWEEN '{filter_map['between']}' AND '{filter_map['between_end']}'"
            )
        else:
            if "eq" in filter_map:
                filters.append(f"[price_date] = '{filter_map['eq']}'")
            if "gte" in filter_map:
                filters.append(f"[price_date] >= '{filter_map['gte']}'")
            if "lte" in filter_map:
                filters.append(f"[price_date] <= '{filter_map['lte']}'")

    if not filters:
        return ""
    return " WHERE " + " AND ".join(filters)


def answer_schema_question(db: SQLDatabase, question: str) -> str | None:
    if not is_schema_question(question):
        return None

    engine = db._engine
    inspector = inspect(engine)
    table_candidates = []
    for schema_name in inspector.get_schema_names():
        if schema_name.lower() in {"information_schema", "sys"}:
            continue
        try:
            for table_name in inspector.get_table_names(schema=schema_name):
                table_candidates.append(f"{schema_name}.{table_name}")
                table_candidates.append(table_name)
        except Exception:
            continue

    table_name = extract_table_name(question, table_candidates)
    if not table_name:
        return "Не удалось определить таблицу из запроса. Укажите точное имя таблицы."

    schema_name = None
    base_table_name = table_name
    if "." in table_name:
        schema_name, base_table_name = table_name.split(".", 1)

    try:
        if schema_name:
            columns = inspector.get_columns(base_table_name, schema=schema_name)
        else:
            matched_schema = None
            columns = []
            for candidate_schema in inspector.get_schema_names():
                try:
                    candidate_columns = inspector.get_columns(base_table_name, schema=candidate_schema)
                except Exception:
                    continue
                if candidate_columns:
                    matched_schema = candidate_schema
                    columns = candidate_columns
                    break
            schema_name = matched_schema
    except Exception:
        return (
            f"Не удалось прочитать схему таблицы `{table_name}`. "
            "Проверьте имя таблицы или обновите schema snapshot."
        )

    if not columns:
        return f"У таблицы `{table_name}` не удалось найти столбцы."

    sql = (
        "SELECT COLUMN_NAME, DATA_TYPE "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA = '{schema_name}' AND TABLE_NAME = '{base_table_name}' "
        "ORDER BY ORDINAL_POSITION"
    )
    formatted_columns = "\n".join(
        f"- {column['name']} ({column.get('type', 'unknown')})"
        for column in columns
    )
    qualified_name = f"{schema_name}.{base_table_name}" if schema_name else base_table_name
    return format_sql_response(
        sql=sql,
        result_text=f"Таблица `{qualified_name}` имеет столбцы:\n{formatted_columns}",
        explanation_text="Показана структура таблицы по данным INFORMATION_SCHEMA.COLUMNS.",
    )


def answer_simple_data_question(db: SQLDatabase, question: str) -> str | None:
    engine = db._engine
    table_ref = find_table_reference(engine, question)
    if not table_ref:
        return None

    schema_name, table_name = table_ref
    inspector = inspect(engine)
    columns = get_table_columns(inspector, schema_name, table_name)
    if not columns:
        return None

    limit = parse_requested_limit(question)
    preferred_columns = [
        column_name
        for column_name in [
            "price_date",
            "ware_id",
            "full_retail_price_kzt",
            "full_retail_price_eur",
            "full_retail_price_usd",
        ]
        if column_name in columns
    ]
    selected_columns = preferred_columns or columns[: min(5, len(columns))]
    where_clause = build_where_clause(question, columns)

    order_column = None
    for candidate in ("price_date", "date", "created_at", "updated_at", "id"):
        if candidate in columns:
            order_column = candidate
            break

    sql = (
        f"SELECT TOP {limit} "
        + ", ".join(f"[{column_name}]" for column_name in selected_columns)
        + f" FROM [{schema_name}].[{table_name}]"
    )
    sql += where_clause
    if order_column:
        sql += f" ORDER BY [{order_column}] DESC"

    rows = run_sql_query(engine, sql)
    return format_sql_response(
        sql=sql,
        result_text=format_rows(selected_columns, rows),
        explanation_text=(
            f"Показаны до {limit} строк из таблицы [{schema_name}].[{table_name}]"
            + (" с применёнными фильтрами." if where_clause else ".")
        ),
    )


def answer_explicit_field_aggregate_question(db: SQLDatabase, question: str) -> str | None:
    lowered = question.lower()
    if not any(marker in lowered for marker in ("поле", "field", "значение", "value")):
        return None

    engine = db._engine
    inspector = inspect(engine)

    table_candidates: list[tuple[str, str]] = []
    for schema_name in inspector.get_schema_names():
        if schema_name.lower() in {"information_schema", "sys"}:
            continue
        try:
            table_names = inspector.get_table_names(schema=schema_name)
        except Exception:
            continue
        for table_name in table_names:
            table_candidates.append((schema_name, table_name))

    for schema_name, table_name in table_candidates:
        columns = get_table_columns(inspector, schema_name, table_name)
        column_name = extract_column_name(question, columns)
        if not column_name:
            continue

        where_clause = build_where_clause(question, columns)
        if any(marker in lowered for marker in ("максим", "max", "самое высокое", "highest")):
            sql = f"SELECT MAX([{column_name}]) AS max_value FROM [{schema_name}].[{table_name}]{where_clause}"
            rows = run_sql_query(engine, sql)
            return format_sql_response(
                sql=sql,
                result_text=format_rows(["max_value"], rows),
                explanation_text=f"Показано максимальное значение поля [{column_name}].",
            )
        if any(marker in lowered for marker in ("миним", "min", "самое низкое", "lowest")):
            sql = f"SELECT MIN([{column_name}]) AS min_value FROM [{schema_name}].[{table_name}]{where_clause}"
            rows = run_sql_query(engine, sql)
            return format_sql_response(
                sql=sql,
                result_text=format_rows(["min_value"], rows),
                explanation_text=f"Показано минимальное значение поля [{column_name}].",
            )
        if any(marker in lowered for marker in ("средн", "avg", "average")):
            sql = (
                f"SELECT AVG(CAST([{column_name}] AS FLOAT)) AS avg_value "
                f"FROM [{schema_name}].[{table_name}]{where_clause}"
            )
            rows = run_sql_query(engine, sql)
            return format_sql_response(
                sql=sql,
                result_text=format_rows(["avg_value"], rows),
                explanation_text=f"Показано среднее значение поля [{column_name}].",
            )
        if any(marker in lowered for marker in ("сумм", "sum", "итого")):
            sql = f"SELECT SUM([{column_name}]) AS sum_value FROM [{schema_name}].[{table_name}]{where_clause}"
            rows = run_sql_query(engine, sql)
            return format_sql_response(
                sql=sql,
                result_text=format_rows(["sum_value"], rows),
                explanation_text=f"Показана сумма по полю [{column_name}].",
            )

    return None


def answer_ranked_or_filtered_price_question(db: SQLDatabase, question: str) -> str | None:
    lowered = question.lower()
    trigger_markers = (
        "топ",
        "top",
        "выше",
        "ниже",
        "больше",
        "меньше",
        "цена у товара",
        "цена товара",
        "price for",
    )
    if not any(marker in lowered for marker in trigger_markers):
        return None

    engine = db._engine
    table_ref = find_table_reference(engine, question) or ("BI", "actual_retail_price")
    schema_name, table_name = table_ref

    inspector = inspect(engine)
    columns = get_table_columns(inspector, schema_name, table_name)
    if not columns:
        return None

    column_name = extract_column_name(question, columns) or next(
        (
            name
            for name in [
                "full_retail_price_kzt",
                "full_retail_price_eur",
                "full_retail_price_usd",
            ]
            if name in columns
        ),
        None,
    )
    if not column_name:
        return None

    limit = parse_requested_limit(question)
    where_parts = []

    base_where = build_where_clause(question, columns)
    if base_where:
        where_parts.append(base_where.replace(" WHERE ", "", 1))

    threshold = parse_numeric_threshold(question)
    if threshold:
        op, value = threshold
        where_parts.append(f"[{column_name}] {op} {value}")

    where_clause = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""

    if ("цена у товара" in lowered or "цена товара" in lowered) and "ware_id" in columns:
        sql = (
            f"SELECT TOP {limit} [price_date], [ware_id], [{column_name}] "
            f"FROM [{schema_name}].[{table_name}]"
            f"{where_clause} ORDER BY [price_date] DESC"
        )
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["price_date", "ware_id", column_name], rows),
            explanation_text=f"Показана цена по полю [{column_name}] для выбранного товара.",
        )

    if "топ" in lowered or "top" in lowered:
        sql = (
            f"SELECT TOP {limit} [price_date], [ware_id], [{column_name}] "
            f"FROM [{schema_name}].[{table_name}]"
            f"{where_clause} ORDER BY [{column_name}] DESC, [price_date] DESC"
        )
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["price_date", "ware_id", column_name], rows),
            explanation_text=f"Показаны top {limit} записей по полю [{column_name}].",
        )

    if threshold:
        sql = (
            f"SELECT TOP {limit} [price_date], [ware_id], [{column_name}] "
            f"FROM [{schema_name}].[{table_name}]"
            f"{where_clause} ORDER BY [{column_name}] DESC, [price_date] DESC"
        )
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["price_date", "ware_id", column_name], rows),
            explanation_text=f"Показаны записи с фильтром по полю [{column_name}].",
        )

    return None


def answer_currency_aggregate_question(db: SQLDatabase, question: str) -> str | None:
    lowered = question.lower()
    if not any(alias in lowered for alias in CURRENCY_ALIAS_MAP):
        return None

    engine = db._engine
    table_ref = find_table_reference(engine, question) or ("BI", "actual_retail_price")
    schema_name, table_name = table_ref

    inspector = inspect(engine)
    columns = get_table_columns(inspector, schema_name, table_name)
    if not columns:
        return None

    column_name = extract_column_name(question, columns)
    if not column_name:
        return None

    where_clause = build_where_clause(question, columns)
    limit = parse_requested_limit(question)
    aggregate_sql = None
    aggregate_alias = None

    if any(marker in lowered for marker in ("максим", "max", "самое высокое", "highest")):
        aggregate_sql = f"MAX([{column_name}])"
        aggregate_alias = "max_value"
    elif any(marker in lowered for marker in ("миним", "min", "самое низкое", "lowest")):
        aggregate_sql = f"MIN([{column_name}])"
        aggregate_alias = "min_value"
    elif any(marker in lowered for marker in ("средн", "avg", "average")):
        aggregate_sql = f"AVG(CAST([{column_name}] AS FLOAT))"
        aggregate_alias = "avg_value"
    elif any(marker in lowered for marker in ("сумм", "sum", "итого")):
        aggregate_sql = f"SUM([{column_name}])"
        aggregate_alias = "sum_value"

    if ("\u043f\u043e \u0434\u0430\u0442\u0435" in lowered or "\u043f\u043e \u0434\u0430\u0442\u0430\u043c" in lowered) and "price_date" in columns:
        aggregate_sql = aggregate_sql or f"AVG(CAST([{column_name}] AS FLOAT))"
        aggregate_alias = aggregate_alias or "avg_value"
        sql = (
            f"SELECT TOP {limit} [price_date], COUNT(*) AS row_count, "
            f"{aggregate_sql} AS {aggregate_alias} "
            f"FROM [{schema_name}].[{table_name}]"
            f"{where_clause} GROUP BY [price_date] ORDER BY [price_date] DESC"
        )
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["price_date", "row_count", aggregate_alias], rows),
            explanation_text=f"Показана агрегированная статистика по полю [{column_name}] в разрезе дат.",
        )

    if ("\u043f\u043e ware_id" in lowered or "\u043f\u043e \u0442\u043e\u0432\u0430\u0440\u0430" in lowered or "\u043f\u043e \u0442\u043e\u0432\u0430\u0440" in lowered) and "ware_id" in columns:
        aggregate_sql = aggregate_sql or f"AVG(CAST([{column_name}] AS FLOAT))"
        aggregate_alias = aggregate_alias or "avg_value"
        sql = (
            f"SELECT TOP {limit} [ware_id], COUNT(*) AS row_count, "
            f"{aggregate_sql} AS {aggregate_alias} "
            f"FROM [{schema_name}].[{table_name}]"
            f"{where_clause} GROUP BY [ware_id] ORDER BY row_count DESC, [ware_id]"
        )
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["ware_id", "row_count", aggregate_alias], rows),
            explanation_text=f"Показана агрегированная статистика по полю [{column_name}] в разрезе товаров.",
        )

    if any(marker in lowered for marker in ("\u043c\u0430\u043a\u0441\u0438\u043c", "max", "\u0441\u0430\u043c\u043e\u0435 \u0432\u044b\u0441\u043e\u043a\u043e\u0435", "highest")):
        sql = f"SELECT MAX([{column_name}]) AS max_value FROM [{schema_name}].[{table_name}]{where_clause}"
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["max_value"], rows),
            explanation_text=f"Показано максимальное значение поля [{column_name}].",
        )

    if any(marker in lowered for marker in ("\u043c\u0438\u043d\u0438\u043c", "min", "\u0441\u0430\u043c\u043e\u0435 \u043d\u0438\u0437\u043a\u043e\u0435", "lowest")):
        sql = f"SELECT MIN([{column_name}]) AS min_value FROM [{schema_name}].[{table_name}]{where_clause}"
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["min_value"], rows),
            explanation_text=f"Показано минимальное значение поля [{column_name}].",
        )

    if any(marker in lowered for marker in ("\u0441\u0440\u0435\u0434\u043d", "avg", "average")):
        sql = (
            f"SELECT AVG(CAST([{column_name}] AS FLOAT)) AS avg_value "
            f"FROM [{schema_name}].[{table_name}]{where_clause}"
        )
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["avg_value"], rows),
            explanation_text=f"Показано среднее значение поля [{column_name}].",
        )

    if any(marker in lowered for marker in ("\u0441\u0443\u043c\u043c", "sum", "\u0438\u0442\u043e\u0433\u043e")):
        sql = f"SELECT SUM([{column_name}]) AS sum_value FROM [{schema_name}].[{table_name}]{where_clause}"
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["sum_value"], rows),
            explanation_text=f"Показана сумма по полю [{column_name}].",
        )

    return None


def answer_simple_aggregate_question(db: SQLDatabase, question: str) -> str | None:
    if not is_aggregate_question(question):
        return None

    engine = db._engine
    table_ref = find_table_reference(engine, question)
    if not table_ref:
        return None

    schema_name, table_name = table_ref
    inspector = inspect(engine)
    columns = get_table_columns(inspector, schema_name, table_name)
    if not columns:
        return None

    lowered = question.lower()
    where_clause = build_where_clause(question, columns)
    limit = parse_requested_limit(question)
    price_column = next(
        (
            name
            for name in [
                "full_retail_price_kzt",
                "full_retail_price_eur",
                "full_retail_price_usd",
            ]
            if name in columns
        ),
        None,
    )

    sql = None
    output_columns: list[str] = []

    if ("сколько" in lowered or "count" in lowered or "количество" in lowered):
        sql = f"SELECT COUNT(*) AS row_count FROM [{schema_name}].[{table_name}]{where_clause}"
        output_columns = ["row_count"]
    elif ("по дате" in lowered or "по датам" in lowered) and "price_date" in columns:
        metric_column = price_column or columns[0]
        sql = (
            f"SELECT TOP {limit} [price_date], COUNT(*) AS row_count, "
            f"AVG(CAST([{metric_column}] AS FLOAT)) AS avg_value "
            f"FROM [{schema_name}].[{table_name}]"
            f"{where_clause} GROUP BY [price_date] ORDER BY [price_date] DESC"
        )
        output_columns = ["price_date", "row_count", "avg_value"]
    elif ("по ware_id" in lowered or "по товара" in lowered or "по товар" in lowered) and "ware_id" in columns:
        metric_column = price_column or columns[0]
        sql = (
            f"SELECT TOP {limit} [ware_id], COUNT(*) AS row_count, "
            f"AVG(CAST([{metric_column}] AS FLOAT)) AS avg_value "
            f"FROM [{schema_name}].[{table_name}]"
            f"{where_clause} GROUP BY [ware_id] ORDER BY row_count DESC, [ware_id]"
        )
        output_columns = ["ware_id", "row_count", "avg_value"]
    elif ("максим" in lowered or "max" in lowered) and price_column:
        sql = (
            f"SELECT MAX([{price_column}]) AS max_value "
            f"FROM [{schema_name}].[{table_name}]{where_clause}"
        )
        output_columns = ["max_value"]
    elif ("миним" in lowered or "min" in lowered) and price_column:
        sql = (
            f"SELECT MIN([{price_column}]) AS min_value "
            f"FROM [{schema_name}].[{table_name}]{where_clause}"
        )
        output_columns = ["min_value"]
    elif ("средн" in lowered or "avg" in lowered or "average" in lowered) and price_column:
        sql = (
            f"SELECT AVG(CAST([{price_column}] AS FLOAT)) AS avg_value "
            f"FROM [{schema_name}].[{table_name}]{where_clause}"
        )
        output_columns = ["avg_value"]
    elif ("сумм" in lowered or "sum" in lowered or "итого" in lowered) and price_column:
        sql = (
            f"SELECT SUM([{price_column}]) AS sum_value "
            f"FROM [{schema_name}].[{table_name}]{where_clause}"
        )
        output_columns = ["sum_value"]

    if not sql:
        return None

    rows = run_sql_query(engine, sql)
    return format_sql_response(
        sql=sql,
        result_text=format_rows(output_columns, rows),
        explanation_text="Показан результат агрегирующего запроса.",
    )


def build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=LM_STUDIO_MODEL,
        base_url=LM_STUDIO_BASE_URL,
        api_key="lm-studio",
        temperature=0,
    )


def build_agent(db: SQLDatabase, memory: SqlAgentMemory):
    llm = build_llm()
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    system_prompt = build_system_prompt(memory, db)
    return create_sql_agent(
        llm=llm,
        toolkit=toolkit,
        prefix=system_prompt,
        verbose=False,
        max_iterations=20,
        agent_executor_kwargs={"handle_parsing_errors": True},
    )


def ask_database(question: str) -> str:
    memory = SqlAgentMemory.load(MEMORY_FILE)
    db = build_database()
    schema_answer = answer_schema_question(db, question)
    if schema_answer is not None:
        memory.add_turn(question, schema_answer)
        memory.save(MEMORY_FILE)
        return schema_answer

    explicit_field_aggregate_answer = answer_explicit_field_aggregate_question(db, question)
    if explicit_field_aggregate_answer is not None:
        memory.add_turn(question, explicit_field_aggregate_answer)
        memory.save(MEMORY_FILE)
        return explicit_field_aggregate_answer

    currency_aggregate_answer = answer_currency_aggregate_question(db, question)
    if currency_aggregate_answer is not None:
        memory.add_turn(question, currency_aggregate_answer)
        memory.save(MEMORY_FILE)
        return currency_aggregate_answer

    ranked_or_filtered_answer = answer_ranked_or_filtered_price_question(db, question)
    if ranked_or_filtered_answer is not None:
        memory.add_turn(question, ranked_or_filtered_answer)
        memory.save(MEMORY_FILE)
        return ranked_or_filtered_answer

    aggregate_answer = answer_simple_aggregate_question(db, question)
    if aggregate_answer is not None:
        memory.add_turn(question, aggregate_answer)
        memory.save(MEMORY_FILE)
        return aggregate_answer

    simple_answer = answer_simple_data_question(db, question)
    if simple_answer is not None:
        memory.add_turn(question, simple_answer)
        memory.save(MEMORY_FILE)
        return simple_answer

    agent = build_agent(db, memory)
    result = agent.invoke({"input": build_agent_input(memory, question)})
    assistant_message = result["output"]

    memory.add_turn(question, str(assistant_message))
    memory.save(MEMORY_FILE)
    return str(assistant_message)


def add_instruction(instruction: str) -> str:
    memory = SqlAgentMemory.load(MEMORY_FILE)
    memory.add_instruction(instruction)
    memory.save(MEMORY_FILE)
    return "Instruction saved to agent memory."


def reset_memory() -> str:
    memory = SqlAgentMemory()
    memory.save(MEMORY_FILE)
    return "Agent memory cleared."


def update_schema_memory() -> str:
    memory = SqlAgentMemory.load(MEMORY_FILE)
    engine = build_sqlalchemy_engine()
    schema_snapshot = build_schema_snapshot_from_engine(engine)
    if len(schema_snapshot) > MAX_SCHEMA_CHARS:
        schema_snapshot = schema_snapshot[:MAX_SCHEMA_CHARS] + "\n\n[Schema truncated]"
    memory.schema_snapshot = schema_snapshot
    memory.save(MEMORY_FILE)
    return "Database schema snapshot refreshed."


def show_memory() -> str:
    memory = SqlAgentMemory.load(MEMORY_FILE)
    return json.dumps(
        {
            "instructions": memory.instructions,
            "conversation": memory.conversation,
            "schema_snapshot": memory.schema_snapshot,
        },
        ensure_ascii=False,
        indent=2,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LangChain SQL agent for LM Studio and SQL Server."
    )
    subparsers = parser.add_subparsers(dest="command")

    ask_parser = subparsers.add_parser("ask", help="Ask a question about the database.")
    ask_parser.add_argument("query_text", nargs="+", help="Text request for the SQL agent.")

    instruction_parser = subparsers.add_parser(
        "add-instruction",
        help="Save a persistent instruction in agent memory.",
    )
    instruction_parser.add_argument("instruction", nargs="+", help="Instruction text.")

    subparsers.add_parser("refresh-schema", help="Refresh the saved table schema snapshot.")
    subparsers.add_parser("show-memory", help="Show current memory contents.")
    subparsers.add_parser("reset-memory", help="Clear agent memory.")

    parser.add_argument(
        "free_text",
        nargs="*",
        help="If no command is provided, the text is treated as a question for the agent.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    argv = sys.argv[1:]
    known_commands = {"ask", "add-instruction", "refresh-schema", "show-memory", "reset-memory"}
    if argv and argv[0] not in known_commands and not argv[0].startswith("-"):
        argv = ["ask", *argv]

    args = parser.parse_args(argv)

    if args.command == "add-instruction":
        print(add_instruction(" ".join(args.instruction)))
        return

    if args.command == "refresh-schema":
        print(update_schema_memory())
        return

    if args.command == "show-memory":
        print(show_memory())
        return

    if args.command == "reset-memory":
        print(reset_memory())
        return

    if args.command == "ask":
        print(ask_database(" ".join(args.query_text)))
        return

    if args.free_text:
        print(ask_database(" ".join(args.free_text)))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
