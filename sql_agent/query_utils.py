from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import inspect, text

from sql_agent.config import CURRENCY_ALIAS_MAP, DEFAULT_PREVIEW_ROWS


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

    match = re.search(r"таблиц[аы]?\s+([a-zA-Z0-9_\.\[\]]+)", question, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip("[]")

    match = re.search(r"\b([a-zA-Z][a-zA-Z0-9_]{2,})\b", question)
    if match:
        return match.group(1)
    return None


def is_schema_question(question: str) -> bool:
    lowered = question.lower()
    schema_keywords = (
        "какие столбцы",
        "какие колонки",
        "какие поля",
        "columns",
        "schema",
        "структур",
        "колонки",
        "столбцы",
        "поля таблицы",
    )
    return any(keyword in lowered for keyword in schema_keywords)


def is_preview_question(question: str) -> bool:
    lowered = question.lower()
    preview_keywords = (
        "покажи",
        "показать",
        "последн",
        "latest",
        "last",
        "recent",
        "запис",
        "строк",
        "rows",
    )
    return any(keyword in lowered for keyword in preview_keywords)


def is_aggregate_question(question: str) -> bool:
    lowered = question.lower()
    aggregate_keywords = (
        "сколько",
        "count",
        "количество",
        "максим",
        "миним",
        "average",
        "avg",
        "средн",
        "sum",
        "сумм",
        "итого",
        "group by",
        "по дате",
        "по товара",
        "по ware_id",
    )
    return any(keyword in lowered for keyword in aggregate_keywords)


def parse_requested_limit(question: str, default_limit: int = DEFAULT_PREVIEW_ROWS) -> int | None:
    no_limit_patterns = (
        r"\ball\b",
        r"\bвсе\b",
        r"\bвсю\b",
        r"\bвесь\b",
        r"\bбез\s+лимита\b",
        r"\bне\s+используй\s+лимит\b",
        r"\bлимит\s+не\s+используй\b",
        r"\bбез\s+ограничени(?:я|й)\b",
    )
    for pattern in no_limit_patterns:
        if re.search(pattern, question, flags=re.IGNORECASE):
            return None

    explicit_limit_patterns = (
        r"\btop\s+(\d+)\b",
        r"\blimit\s+(\d+)\b",
        r"\bпокажи\s+(\d+)\b",
        r"\bвыведи\s+(\d+)\b",
        r"\bпервые\s+(\d+)\b",
        r"\bпоследние\s+(\d+)\b",
    )
    match = None
    for pattern in explicit_limit_patterns:
        match = re.search(pattern, question, flags=re.IGNORECASE)
        if match:
            break
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
    normalized_dates: list[str] = []

    for value in re.findall(r"\d{4}-\d{2}-\d{2}", question):
        normalized_dates.append(value)

    for value in re.findall(r"\d{2}\.\d{2}\.\d{4}", question):
        try:
            normalized_dates.append(datetime.strptime(value, "%d.%m.%Y").strftime("%Y-%m-%d"))
        except ValueError:
            continue

    deduped_dates = list(dict.fromkeys(normalized_dates))
    if len(deduped_dates) >= 2:
        filters.append(("between", deduped_dates[0]))
        filters.append(("between_end", deduped_dates[1]))
        return filters
    if len(deduped_dates) == 1:
        filters.append(("eq", deduped_dates[0]))

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


def is_price_question(question: str) -> bool:
    lowered = question.lower()
    price_markers = (
        "price",
        "prices",
        "retail",
        "цена",
        "цены",
        "стоимость",
        "usd",
        "eur",
        "kzt",
        "доллар",
        "доллары",
        "евро",
        "тенге",
    )
    return any(marker in lowered for marker in price_markers)


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


class QueryFormatter:
    normalize_whitespace = staticmethod(normalize_whitespace)
    run_sql_query = staticmethod(run_sql_query)
    format_rows = staticmethod(format_rows)
    format_sql_response = staticmethod(format_sql_response)


class QuestionParser:
    extract_table_name = staticmethod(extract_table_name)
    is_schema_question = staticmethod(is_schema_question)
    is_preview_question = staticmethod(is_preview_question)
    is_aggregate_question = staticmethod(is_aggregate_question)
    parse_requested_limit = staticmethod(parse_requested_limit)
    get_table_columns = staticmethod(get_table_columns)
    extract_column_name = staticmethod(extract_column_name)
    parse_ware_id_filter = staticmethod(parse_ware_id_filter)
    parse_date_filters = staticmethod(parse_date_filters)
    parse_numeric_threshold = staticmethod(parse_numeric_threshold)
    find_table_reference = staticmethod(find_table_reference)
    is_price_question = staticmethod(is_price_question)
    build_where_clause = staticmethod(build_where_clause)
