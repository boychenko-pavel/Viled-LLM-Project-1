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
CURRENCY_ORDER = ["USD", "EUR", "RUB", "KGS", "UZS", "CHF"]
CURRENCY_SORT_ORDER = {currency: index for index, currency in enumerate(CURRENCY_ORDER)}


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
        self._ensure_storage()

    def ask(self, message: str) -> str:
        cleaned_message = message.strip()
        if not cleaned_message:
            raise ValueError("Message is empty.")

        with self._lock:
            dataframe = self.load_dataframe()
            viled_inform_dataframe = self._build_viled_inform_dataframe(dataframe)
            viled_inform_dataframe = self._save_currency_inform(viled_inform_dataframe)

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

    def load_current_viled_inform_form(self) -> list[dict[str, object]]:
        with self._lock:
            dataframe = self._build_viled_inform_dataframe(self.load_dataframe())
            currencies = [
                str(currency).upper()
                for currency in dataframe.get("Currency", pd.Series(dtype=str)).dropna().tolist()
            ]
            current_values = self._load_latest_current_values()

        return [
            {
                "currency": currency,
                "viled_inform": current_values.get(currency, ""),
            }
            for currency in currencies
        ]

    def save_current_viled_inform(self, values: dict[str, object]) -> int:
        cleaned_values: dict[str, Decimal] = {}
        allowed_currencies = set(CURRENCY_ORDER)
        for currency, value in values.items():
            currency_key = str(currency).strip().upper()
            if currency_key not in allowed_currencies:
                raise ValueError(f"Unknown currency: {currency}")

            text_value = str(value).strip()
            if not text_value:
                continue

            try:
                cleaned_values[currency_key] = Decimal(text_value.replace(" ", "").replace(",", "."))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"Invalid Viled Inform Fact value for {currency_key}.") from exc

        if not cleaned_values:
            raise ValueError("Enter at least one Viled Inform Fact value.")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = [
            (timestamp, currency, str(value))
            for currency, value in cleaned_values.items()
        ]

        with self._lock:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.db_path, timeout=20)
            try:
                self._ensure_currency_inform_current_table(connection)
                self._migrate_currency_inform_current_table(connection)
                self._ensure_currency_pricing_table(connection)
                connection.executemany(
                    """
                    INSERT INTO currency_inform_current (Date, currency, "Viled Inform Fact")
                    VALUES (?, ?, ?)
                    """,
                    rows,
                )
                connection.commit()
            finally:
                connection.close()

        return len(rows)

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

            allowed_currencies = set(CURRENCY_ORDER)
            dataframe = dataframe[dataframe["currency"].isin(allowed_currencies)]
            dataframe = (
                dataframe.assign(_currency_sort=dataframe["currency"].map(CURRENCY_SORT_ORDER))
                .sort_values("_currency_sort", kind="stable")
                .drop(columns=["_currency_sort"])
            )

            dataframe["Viled Inform CALC"] = dataframe.apply(
                lambda row: self._calculate_viled_inform(row["buy"], row["currency"]),
                axis=1,
            )
            dataframe["buy"] = dataframe.apply(
                lambda row: self._normalize_report_buy(row["buy"], row["currency"]),
                axis=1,
            )
            dataframe["Viled Inform Fact"] = ""
            dataframe["dif"] = ""

            current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            dataframe.insert(0, "Date", current_datetime)
            dataframe = dataframe[["Date", "currency", "buy", "Viled Inform Fact", "Viled Inform CALC", "dif"]]
            dataframe = dataframe.rename(columns={"currency": "Currency"})

        return dataframe

    def _save_currency_inform(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        dataframe = dataframe.rename(columns={"Currency": "currency", "Viled Inform": "Viled Inform Fact"})
        required_columns = {"Date", "buy", "currency", "Viled Inform CALC", "Viled Inform Fact"}
        if dataframe.empty or not required_columns.issubset(dataframe.columns):
            return dataframe

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=20)
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS currency_inform (
                    date TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
                    currency TEXT NOT NULL,
                    buy NUMERIC NOT NULL,
                    "Viled Inform CALC" NUMERIC,
                    "Viled Inform Fact" NUMERIC
                )
                """
            )
            self._migrate_currency_inform_table(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS currency_inform_current (
                    Date TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    "Viled Inform Fact" NUMERIC
                )
                """
            )
            self._ensure_currency_inform_current_table(connection)
            self._migrate_currency_inform_current_table(connection)
            self._ensure_currency_pricing_table(connection)
            current_viled_inform = self._latest_current_viled_inform(connection)
            dataframe = dataframe.copy()
            dataframe["Viled Inform Fact"] = dataframe["currency"].map(current_viled_inform).fillna("")
            dataframe["dif"] = dataframe.apply(
                lambda row: self._calculate_dif(row["Viled Inform CALC"], row["Viled Inform Fact"]),
                axis=1,
            )
            rows = [
                (
                    str(row["Date"]),
                    str(row["currency"]),
                    str(row["buy"]),
                    "" if pd.isna(row["Viled Inform CALC"]) else str(row["Viled Inform CALC"]),
                    "" if pd.isna(row["Viled Inform Fact"]) else str(row["Viled Inform Fact"]),
                )
                for _, row in dataframe.iterrows()
            ]
            connection.executemany(
                """
                INSERT INTO currency_inform (
                    date,
                    currency,
                    buy,
                    "Viled Inform CALC",
                    "Viled Inform Fact"
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            connection.commit()
        finally:
            connection.close()

        return dataframe.rename(columns={"currency": "Currency"})[
            ["Date", "Currency", "buy", "Viled Inform Fact", "Viled Inform CALC", "dif"]
        ]

    def _load_latest_current_values(self) -> dict[str, object]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=20)
        try:
            self._ensure_currency_inform_current_table(connection)
            self._migrate_currency_inform_current_table(connection)
            self._ensure_currency_pricing_table(connection)
            return self._latest_current_viled_inform(connection)
        finally:
            connection.close()

    def _ensure_storage(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=20)
        try:
            self._ensure_currency_pricing_table(connection)
            connection.commit()
        finally:
            connection.close()

    def _ensure_currency_inform_current_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS currency_inform_current (
                Date TEXT NOT NULL,
                currency TEXT NOT NULL,
                    "Viled Inform Fact" NUMERIC
            )
            """
        )

    def _ensure_currency_pricing_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS currency_pricing (
                DATE TEXT NOT NULL,
                Currency TEXT NOT NULL,
                rate NUMERIC
            )
            """
        )

    def _latest_current_viled_inform(self, connection: sqlite3.Connection) -> dict[str, object]:
        self._migrate_currency_inform_current_table(connection)
        latest_by_currency: dict[str, object] = {}
        for currency, viled_inform in connection.execute(
            """
            SELECT currency, "Viled Inform Fact"
            FROM currency_inform_current
            WHERE "Viled Inform Fact" IS NOT NULL
                AND TRIM(CAST("Viled Inform Fact" AS TEXT)) != ''
            ORDER BY Date DESC, rowid DESC
            """
        ):
            currency_key = str(currency).upper()
            if currency_key not in latest_by_currency:
                latest_by_currency[currency_key] = viled_inform
        return latest_by_currency

    def _migrate_currency_inform_table(self, connection: sqlite3.Connection) -> None:
        columns = self._sqlite_columns(connection, "currency_inform")
        if "Viled Inform CALC" not in columns:
            if "Viled Inform" in columns:
                connection.execute(
                    'ALTER TABLE currency_inform RENAME COLUMN "Viled Inform" TO "Viled Inform CALC"'
                )
                columns = self._sqlite_columns(connection, "currency_inform")
            elif "viled_inform" in columns:
                connection.execute(
                    'ALTER TABLE currency_inform RENAME COLUMN viled_inform TO "Viled Inform CALC"'
                )
                columns = self._sqlite_columns(connection, "currency_inform")

        if "Viled Inform Fact" not in columns:
            if "Viled Inform" in columns:
                connection.execute(
                    'ALTER TABLE currency_inform RENAME COLUMN "Viled Inform" TO "Viled Inform Fact"'
                )
            else:
                connection.execute('ALTER TABLE currency_inform ADD COLUMN "Viled Inform Fact" NUMERIC')

    def _migrate_currency_inform_current_table(self, connection: sqlite3.Connection) -> None:
        columns = self._sqlite_columns(connection, "currency_inform_current")
        if "Viled Inform Fact" not in columns:
            if "Viled Inform" in columns:
                connection.execute(
                    'ALTER TABLE currency_inform_current RENAME COLUMN "Viled Inform" TO "Viled Inform Fact"'
                )
            else:
                connection.execute(
                    'ALTER TABLE currency_inform_current ADD COLUMN "Viled Inform Fact" NUMERIC'
                )

    def _sqlite_columns(self, connection: sqlite3.Connection, table_name: str) -> set[str]:
        return {
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{table_name}")')
        }

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

    def _normalize_report_buy(self, buy: object, currency: str) -> object:
        if currency != "UZS":
            return buy

        try:
            buy_value = Decimal(str(buy).replace(" ", "").replace(",", "."))
        except (InvalidOperation, ValueError):
            return buy

        return buy_value / Decimal("100")

    def _calculate_dif(self, calculated: object, current: object) -> Decimal | str:
        try:
            calculated_value = Decimal(str(calculated).replace(" ", "").replace(",", "."))
            current_value = Decimal(str(current).replace(" ", "").replace(",", "."))
        except (InvalidOperation, ValueError):
            return ""

        difference = calculated_value - current_value
        if difference == 0:
            return "-"
        return difference

    def _floor_to_step(self, value: Decimal, step: Decimal) -> Decimal:
        return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


CurrencyAgent = CurrencyTool
