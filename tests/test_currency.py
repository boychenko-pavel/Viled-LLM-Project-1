import csv
from decimal import Decimal
from io import StringIO

import pandas as pd

from sql_agent.currency import CurrencyAgent


def test_currency_output_uses_viled_inform_report_columns() -> None:
    dataframe = pd.DataFrame(
        [
            ["700", "CHF", "710"],
            ["650", "UZS", "660"],
            ["6.11", "KGS", "6.2"],
            ["5,37", "RUB", "5,5"],
            ["600", "EUR", "610"],
            ["512,4", "USD", "520"],
        ],
        columns=["Buy", "Currency", "Sell"],
    )

    answer = CurrencyAgent()._format_answer(dataframe)
    result = answer.split("Result:\n", maxsplit=1)[1]
    rows = list(csv.DictReader(StringIO(result)))

    assert result.splitlines()[0] == "Date,Currency,buy,Viled Inform Fact,Viled Inform CALC,dif"
    assert [row["Viled Inform CALC"] for row in rows] == [
        "505",
        "590",
        "5.2",
        "5.9",
        "6.11",
        "0",
    ]
    assert [row["Viled Inform Fact"] for row in rows] == ["", "", "", "", "", ""]
    assert [row["dif"] for row in rows] == ["", "", "", "", "", ""]
    assert [row["Currency"] for row in rows] == ["USD", "EUR", "RUB", "KGS", "UZS", "CHF"]
    assert rows[4]["buy"] == "6.5"
    assert "sell" not in rows[0]


def test_currency_save_migrates_and_keeps_current_table_static(tmp_path) -> None:
    db_path = tmp_path / "data.db"
    agent = CurrencyAgent(db_path=db_path)
    dataframe = pd.DataFrame(
        [
            ["2026-06-29 12:00:00", "USD", "512,4", "520", Decimal("505"), ""],
        ],
        columns=["Date", "currency", "buy", "sell", "Viled Inform CALC", "Viled Inform Fact"],
    )
    import sqlite3

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE currency_inform_current (
                Date TEXT NOT NULL,
                currency TEXT NOT NULL,
                "Viled Inform" NUMERIC
            )
            """
        )
        connection.execute(
            'INSERT INTO currency_inform_current (Date, currency, "Viled Inform") VALUES (?, ?, ?)',
            ("2026-06-28 09:00:00", "USD", "510"),
        )
        connection.execute(
            'INSERT INTO currency_inform_current (Date, currency, "Viled Inform") VALUES (?, ?, ?)',
            ("2026-06-28 18:00:00", "USD", "515"),
        )
        connection.execute(
            'INSERT INTO currency_inform_current (Date, currency, "Viled Inform") VALUES (?, ?, ?)',
            ("2026-06-28 09:00:00", "EUR", "610"),
        )
        connection.commit()
    finally:
        connection.close()

    report_dataframe = agent._save_currency_inform(dataframe)

    connection = sqlite3.connect(db_path)
    try:
        currency_columns = [
            row[1]
            for row in connection.execute('PRAGMA table_info("currency_inform")')
        ]
        current_columns = [
            row[1]
            for row in connection.execute('PRAGMA table_info("currency_inform_current")')
        ]
        pricing_columns = [
            row[1]
            for row in connection.execute('PRAGMA table_info("currency_pricing")')
        ]
        saved_rows = connection.execute(
            'SELECT date, currency, buy, "Viled Inform CALC", "Viled Inform Fact" FROM currency_inform'
        ).fetchall()
        current_rows = connection.execute(
            'SELECT Date, currency, "Viled Inform Fact" FROM currency_inform_current'
        ).fetchall()
    finally:
        connection.close()

    assert "Viled Inform CALC" in currency_columns
    assert "Viled Inform Fact" in currency_columns
    assert "Viled Inform" not in currency_columns
    assert current_columns == ["Date", "currency", "Viled Inform Fact"]
    assert pricing_columns == ["DATE", "Currency", "rate"]
    assert saved_rows == [("2026-06-29 12:00:00", "USD", "512,4", 505, 515)]
    assert report_dataframe.to_dict("records") == [
        {
            "Date": "2026-06-29 12:00:00",
            "Currency": "USD",
            "buy": "512,4",
            "Viled Inform Fact": 515,
            "Viled Inform CALC": Decimal("505"),
            "dif": Decimal("-10"),
        }
    ]
    assert current_rows == [
        ("2026-06-28 09:00:00", "USD", 510),
        ("2026-06-28 18:00:00", "USD", 515),
        ("2026-06-28 09:00:00", "EUR", 610),
    ]


def test_save_current_viled_inform_writes_current_table(tmp_path) -> None:
    db_path = tmp_path / "data.db"
    agent = CurrencyAgent(db_path=db_path)

    saved_count = agent.save_current_viled_inform({"usd": "515", "EUR": "610,5", "RUB": ""})

    import sqlite3

    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            'SELECT currency, "Viled Inform Fact" FROM currency_inform_current ORDER BY currency'
        ).fetchall()
    finally:
        connection.close()

    assert saved_count == 2
    assert rows == [("EUR", 610.5), ("USD", 515)]


def test_floor_to_step_uses_decimal_precision() -> None:
    agent = CurrencyAgent()

    assert agent._floor_to_step(Decimal("0.3"), Decimal("0.1")) == Decimal("0.3")


def test_currency_dif_returns_dash_for_zero() -> None:
    agent = CurrencyAgent()

    assert agent._calculate_dif(Decimal("505"), "505") == "-"
