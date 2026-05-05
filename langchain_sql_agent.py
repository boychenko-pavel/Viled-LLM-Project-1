from __future__ import annotations

from sql_agent.cli import build_parser, main
from sql_agent.config import (
    CURRENCY_ALIAS_MAP,
    DEFAULT_PREVIEW_ROWS,
    ENV_FILE,
    LM_STUDIO_BASE_URL,
    LM_STUDIO_MODEL,
    MAX_HISTORY_MESSAGES,
    MAX_SCHEMA_CHARS,
    MEMORY_DIR,
    MEMORY_FILE,
    REQUIRED_KEYS,
)
from sql_agent.database import (
    build_database,
    build_pymssql_engine,
    build_pyodbc_engine,
    build_sqlalchemy_engine,
    escape_odbc_value,
    load_db_config,
)
from sql_agent.heuristics import (
    answer_currency_aggregate_question,
    answer_explicit_field_aggregate_question,
    answer_ranked_or_filtered_price_question,
    answer_schema_question,
    answer_simple_aggregate_question,
    answer_simple_data_question,
)
from sql_agent.langchain_factory import build_agent, build_llm
from sql_agent.memory import SqlAgentMemory
from sql_agent.prompts import build_agent_input, build_system_prompt
from sql_agent.query_utils import (
    build_where_clause,
    extract_column_name,
    extract_table_name,
    find_table_reference,
    format_rows,
    format_sql_response,
    get_table_columns,
    is_aggregate_question,
    is_preview_question,
    is_schema_question,
    normalize_whitespace,
    parse_date_filters,
    parse_numeric_threshold,
    parse_requested_limit,
    parse_ware_id_filter,
    run_sql_query,
)
from sql_agent.schema import build_schema_snapshot_from_engine, refresh_schema_snapshot
from sql_agent.service import (
    add_instruction,
    ask_database,
    reset_memory,
    show_memory,
    update_schema_memory,
)

__all__ = [
    "CURRENCY_ALIAS_MAP",
    "DEFAULT_PREVIEW_ROWS",
    "ENV_FILE",
    "LM_STUDIO_BASE_URL",
    "LM_STUDIO_MODEL",
    "MAX_HISTORY_MESSAGES",
    "MAX_SCHEMA_CHARS",
    "MEMORY_DIR",
    "MEMORY_FILE",
    "REQUIRED_KEYS",
    "SqlAgentMemory",
    "add_instruction",
    "answer_currency_aggregate_question",
    "answer_explicit_field_aggregate_question",
    "answer_ranked_or_filtered_price_question",
    "answer_schema_question",
    "answer_simple_aggregate_question",
    "answer_simple_data_question",
    "ask_database",
    "build_agent",
    "build_agent_input",
    "build_database",
    "build_llm",
    "build_parser",
    "build_pymssql_engine",
    "build_pyodbc_engine",
    "build_schema_snapshot_from_engine",
    "build_sqlalchemy_engine",
    "build_system_prompt",
    "build_where_clause",
    "escape_odbc_value",
    "extract_column_name",
    "extract_table_name",
    "find_table_reference",
    "format_rows",
    "format_sql_response",
    "get_table_columns",
    "is_aggregate_question",
    "is_preview_question",
    "is_schema_question",
    "load_db_config",
    "main",
    "normalize_whitespace",
    "parse_date_filters",
    "parse_numeric_threshold",
    "parse_requested_limit",
    "parse_ware_id_filter",
    "refresh_schema_snapshot",
    "reset_memory",
    "run_sql_query",
    "show_memory",
    "update_schema_memory",
]


if __name__ == "__main__":
    main()
