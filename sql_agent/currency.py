from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from html import unescape
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
import sqlite3
from threading import Lock
from urllib.error import URLError
from urllib.request import Request, urlopen

import pandas as pd


MIG_ADDITIONAL_URL = "https://www.mig.kz/additional#main"
SQLITE_DB_PATH = Path(__file__).resolve().parent.parent / "sqlite" / "data.db"


class InformerAdditionalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._target_depth = 0
        self._table_depth = 0
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: value or "" for name, value in attrs}
        if tag == "div" and "informer-additional" in attrs_dict.get("class", "").split():
            self._target_depth = 1
            return

        if self._target_depth:
            self._target_depth += 1

        if not self._target_depth:
            return

        if tag == "table":
            self._table_depth += 1
        elif tag == "tr" and self._table_depth:
            self._in_row = True
            self._current_row = []
        elif tag in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._cell_parts = []
        elif tag == "br" and self._in_cell:
            self._cell_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._target_depth and tag in {"td", "th"} and self._in_cell:
            value = " ".join("".join(self._cell_parts).split())
            self._current_row.append(unescape(value))
            self._in_cell = False
            self._cell_parts = []
        elif self._target_depth and tag == "tr" and self._in_row:
            if any(cell for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = []
            self._in_row = False
        elif self._target_depth and tag == "table" and self._table_depth:
            self._table_depth -= 1

        if self._target_depth:
            self._target_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._target_depth and self._in_cell:
            self._cell_parts.append(data)


class CurrencyTool:
    def __init__(
        self,
        source_url: str = MIG_ADDITIONAL_URL,
        db_path: Path = SQLITE_DB_PATH,
    ) -> None:
        self.source_url = source_url
        self.db_path = db_path
        self._lock = Lock()

    def ask(self, message: str) -> str:
        cleaned_message = message.strip()
        if not cleaned_message:
            raise ValueError("Message is empty.")

        with self._lock:
            dataframe = self.load_dataframe()
            viled_inform_dataframe = self._build_viled_inform_dataframe(dataframe)
            self._save_currency_inform(viled_inform_dataframe)

        return self._format_prepared_answer(viled_inform_dataframe)

    def load_dataframe(self) -> pd.DataFrame:
        html = self._download_html()
        parser = InformerAdditionalParser()
        parser.feed(html)
        dataframe = self._rows_to_dataframe(parser.rows)
        if dataframe.empty:
            raise ValueError("No rows found in div.informer-additional on mig.kz.")
        return dataframe

    def load_conversation(self) -> list[dict[str, str]]:
        return []

    def reset_memory(self) -> str:
        return "Currency does not store chat memory."

    def _download_html(self) -> str:
        request = Request(
            self.source_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except URLError as exc:
            raise RuntimeError(f"Failed to load currency data from {self.source_url}.") from exc

    def _rows_to_dataframe(self, rows: list[list[str]]) -> pd.DataFrame:
        cleaned_rows = [[cell.strip() for cell in row] for row in rows if any(cell.strip() for cell in row)]
        if not cleaned_rows:
            return pd.DataFrame()

        width = max(len(row) for row in cleaned_rows)
        normalized_rows = [row + [""] * (width - len(row)) for row in cleaned_rows]
        if width == 3 and self._looks_like_currency_row(normalized_rows[0]):
            return pd.DataFrame(normalized_rows, columns=["buy", "currency", "sell"])

        header = normalized_rows[0]
        data_rows = normalized_rows[1:]

        if self._looks_like_header(header):
            columns = self._deduplicate_columns(header)
            return pd.DataFrame(data_rows, columns=columns)

        columns = [f"column_{index}" for index in range(1, width + 1)]
        return pd.DataFrame(normalized_rows, columns=columns)

    def _looks_like_header(self, row: list[str]) -> bool:
        if any(self._is_number(cell) for cell in row):
            return False
        non_empty = [cell for cell in row if cell]
        return bool(non_empty) and len(set(non_empty)) == len(non_empty)

    def _looks_like_currency_row(self, row: list[str]) -> bool:
        return len(row) == 3 and self._is_number(row[0]) and bool(row[1]) and self._is_number(row[2])

    def _is_number(self, value: str) -> bool:
        try:
            float(value.replace(" ", "").replace(",", "."))
        except ValueError:
            return False
        return True

    def _deduplicate_columns(self, columns: list[str]) -> list[str]:
        seen: dict[str, int] = {}
        deduplicated = []
        for index, column in enumerate(columns, start=1):
            base = column or f"column_{index}"
            count = seen.get(base, 0) + 1
            seen[base] = count
            deduplicated.append(base if count == 1 else f"{base}_{count}")
        return deduplicated

    def _format_answer(self, dataframe: pd.DataFrame) -> str:
        return self._format_prepared_answer(self._build_viled_inform_dataframe(dataframe))

    def _build_viled_inform_dataframe(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        standard_columns = {
            str(column).strip().lower(): column
            for column in dataframe.columns
        }
        dataframe = dataframe.rename(
            columns={
                original: normalized
                for normalized, original in standard_columns.items()
                if normalized in {"buy", "currency", "sell"}
            }
        )

        if "currency" in dataframe.columns:
            dataframe = dataframe.copy()
            dataframe["currency"] = dataframe["currency"].str[:3].str.upper()

            allowed_currencies = {"USD", "EUR", "RUB", "KGS", "UZS", "CHF"}
            dataframe = dataframe[dataframe["currency"].isin(allowed_currencies)]

            dataframe["Viled Inform"] = dataframe.apply(
                lambda row: self._calculate_viled_inform(row["buy"], row["currency"]),
                axis=1,
            )
            dataframe = dataframe.drop(columns=["sell"], errors="ignore")

            current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            dataframe.insert(0, "Date", current_datetime)
            dataframe = dataframe[["Date", "currency", "buy", "Viled Inform"]]

        return dataframe

    def _save_currency_inform(self, dataframe: pd.DataFrame) -> None:
        required_columns = {"Date", "buy", "currency", "Viled Inform"}
        if dataframe.empty or not required_columns.issubset(dataframe.columns):
            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            (
                str(row["Date"]),
                str(row["currency"]),
                str(row["buy"]),
                "" if pd.isna(row["Viled Inform"]) else str(row["Viled Inform"]),
            )
            for _, row in dataframe.iterrows()
        ]

        with sqlite3.connect(self.db_path, timeout=20) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS currency_inform (
                    date TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
                    currency TEXT NOT NULL,
                    buy NUMERIC NOT NULL,
                    viled_inform NUMERIC
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO currency_inform (
                    date,
                    currency,
                    buy,
                    viled_inform
                )
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )

    def _format_prepared_answer(self, dataframe: pd.DataFrame) -> str:
        buffer = StringIO()
        dataframe.to_csv(buffer, index=False, lineterminator="\n")
        result = buffer.getvalue().strip()
        return (
            f"Source: {self.source_url}\n"
            "Pandas object: pandas.DataFrame\n\n"
            "Result:\n"
            f"{result}"
        )

    def _calculate_viled_inform(self, buy: object, currency: str) -> Decimal | None:
        try:
            buy_value = Decimal(str(buy).replace(" ", "").replace(",", "."))
        except (InvalidOperation, ValueError):
            return None

        if currency == "CHF":
            return Decimal("0")
        if currency == "USD":
            return self._floor_to_step(buy_value * Decimal("0.99"), Decimal("5"))
        if currency == "EUR":
            return self._floor_to_step(buy_value * Decimal("0.985"), Decimal("5"))
        if currency in {"RUB", "KGS"}:
            return self._floor_to_step(buy_value * Decimal("0.97"), Decimal("0.1"))
        if currency == "UZS":
            return self._floor_to_step(buy_value * Decimal("0.94"), Decimal("0.1")) / Decimal("100")
        return None

    def _floor_to_step(self, value: Decimal, step: Decimal) -> Decimal:
        return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


CurrencyAgent = CurrencyTool
