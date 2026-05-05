from __future__ import annotations

from langchain_community.utilities.sql_database import SQLDatabase
from sqlalchemy import inspect

from sql_agent.config import MAX_SCHEMA_CHARS
from sql_agent.memory import SqlAgentMemory


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


class SchemaSnapshotService:
    def build_from_engine(self, engine) -> str:
        return build_schema_snapshot_from_engine(engine)

    def refresh(self, db: SQLDatabase, memory: SqlAgentMemory) -> str:
        return refresh_schema_snapshot(db, memory)

    def truncate(self, schema_snapshot: str) -> str:
        if len(schema_snapshot) > MAX_SCHEMA_CHARS:
            return schema_snapshot[:MAX_SCHEMA_CHARS] + "\n\n[Schema truncated]"
        return schema_snapshot
