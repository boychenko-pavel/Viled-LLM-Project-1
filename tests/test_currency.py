import csv
from decimal import Decimal
from io import StringIO

import pandas as pd

from sql_agent.currency import CurrencyAgent


def test_currency_output_replaces_sell_with_viled_inform() -> None:
    dataframe = pd.DataFrame(
        [
            ["512,4", "USD", "520"],
            ["600", "EUR", "610"],
            ["5,37", "RUB", "5,5"],
            ["6.11", "KGS", "6.2"],
            ["650", "UZS", "660"],
            ["700", "CHF", "710"],
        ],
        columns=["Buy", "Currency", "Sell"],
    )

    answer = CurrencyAgent()._format_answer(dataframe)
    result = answer.split("Result:\n", maxsplit=1)[1]
    rows = list(csv.DictReader(StringIO(result)))

    assert result.splitlines()[0] == "Date,buy,currency,Viled Inform"
    assert [row["Viled Inform"] for row in rows] == [
        "505",
        "590",
        "5.2",
        "5.9",
        "6.11",
        "0",
    ]
    assert "sell" not in result.lower()


def test_floor_to_step_uses_decimal_precision() -> None:
    agent = CurrencyAgent()

    assert agent._floor_to_step(Decimal("0.3"), Decimal("0.1")) == Decimal("0.3")
