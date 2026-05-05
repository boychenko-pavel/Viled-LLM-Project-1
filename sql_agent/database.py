from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from urllib.parse import quote, quote_plus

import pyodbc
from dotenv import dotenv_values
from langchain_community.utilities.sql_database import SQLDatabase
from sqlalchemy import create_engine

from sql_agent.config import ENV_FILE, REQUIRED_KEYS


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


class DatabaseConnector:
    def __init__(self, env_file: Path = ENV_FILE):
        self.env_file = env_file

    def load_config(self) -> dict[str, str]:
        return load_db_config(self.env_file)

    def build_engine(self, config: dict[str, str] | None = None):
        return build_sqlalchemy_engine(config or self.load_config())

    def build_database(self) -> SQLDatabase:
        config = self.load_config()
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
                f"{self.env_file} to try the fallback driver. Original error: {exc}"
            ) from exc
