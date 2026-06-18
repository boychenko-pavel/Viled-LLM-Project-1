from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import pyodbc
from dotenv import dotenv_values
from sqlalchemy import create_engine, text


ENV_FILE = Path(r"C:\Users\p.boychenko\secrets\SQL_Password.env")
QUERY = """
SELECT TOP (1000) [price_date]
      ,[ware_id]
      ,[full_retail_price_kzt]
      ,[full_retail_price_eur]
      ,[full_retail_price_usd]
      ,[full_price_level_kzt]
      ,[full_price_level_usd]
      ,[full_price_level_eur]
      ,[_RANK]
      ,[brand]
  FROM [DWH].[LLM].[price]
"""


def load_db_config(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        raise FileNotFoundError(f"Файл с секретами не найден: {env_path}")

    config = {
        key: (value or "").strip()
        for key, value in dotenv_values(env_path).items()
    }

    required_keys = ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME")
    missing_keys = [key for key in required_keys if not config.get(key)]
    if missing_keys:
        raise ValueError(
            "В файле SQL_Password.env отсутствуют значения: "
            + ", ".join(missing_keys)
        )

    return config


def build_engine():
    config = load_db_config(ENV_FILE)
    available_drivers = pyodbc.drivers()
    driver = next(
        (
            item
            for item in (
                "ODBC Driver 18 for SQL Server",
                "ODBC Driver 17 for SQL Server",
                "SQL Server",
            )
            if item in available_drivers
        ),
        None,
    )
    if not driver:
        raise RuntimeError(
            "Не найден ODBC-драйвер для SQL Server. "
            "Установите ODBC Driver 17/18 for SQL Server."
        )

    encrypt_settings = (
        "Encrypt=yes;TrustServerCertificate=yes;"
        if driver == "ODBC Driver 18 for SQL Server"
        else "Encrypt=no;"
    )

    connection_string = (
        f"DRIVER={{{driver}}};"
        f"SERVER={config['DB_HOST']};"
        f"DATABASE={config['DB_NAME']};"
        f"UID={config['DB_USER']};"
        f"PWD={config['DB_PASSWORD']};"
        f"{encrypt_settings}"
    )

    return create_engine(
        f"mssql+pyodbc:///?odbc_connect={quote_plus(connection_string)}"
    )


def main() -> None:
    engine = build_engine()
    with engine.connect() as connection:
        dataframe = pd.read_sql(text(QUERY), connection)

    print(dataframe.to_string(index=False))


if __name__ == "__main__":
    main()
