from __future__ import annotations

import re
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta

from sqlalchemy import inspect, text

from sql_agent.config import CURRENCY_ALIAS_MAP, DEFAULT_PREVIEW_ROWS


RUSSIAN_MONTHS = {
    "январь": 1,
    "января": 1,
    "январе": 1,
    "февраль": 2,
    "февраля": 2,
    "феврале": 2,
    "ферваль": 2,
    "ферваля": 2,
    "фервале": 2,
    "феврал": 2,
    "март": 3,
    "марта": 3,
    "марте": 3,
    "апрель": 4,
    "апреля": 4,
    "апреле": 4,
    "май": 5,
    "мая": 5,
    "мае": 5,
    "июнь": 6,
    "июня": 6,
    "июне": 6,
    "июль": 7,
    "июля": 7,
    "июле": 7,
    "август": 8,
    "августа": 8,
    "августе": 8,
    "сентябрь": 9,
    "сентября": 9,
    "сентябре": 9,
    "октябрь": 10,
    "октября": 10,
    "октябре": 10,
    "ноябрь": 11,
    "ноября": 11,
    "ноябре": 11,
    "декабрь": 12,
    "декабря": 12,
    "декабре": 12,
}


def normalize_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def run_sql_query(engine, sql: str) -> list[tuple]:
    with engine.connect() as connection:
        result = connection.execute(text(sql))
        return result.fetchall()


def run_sql_query_with_columns(engine, sql: str) -> tuple[list[str], list[tuple]]:
    with engine.connect() as connection:
        result = connection.execute(text(sql))
        return list(result.keys()), result.fetchall()


def extract_select_statement(question: str) -> str | None:
    match = re.search(r"\bselect\b", question, flags=re.IGNORECASE)
    if not match:
        return None

    sql = question[match.start():].strip()
    return sql[:-1].strip() if sql.endswith(";") else sql


def validate_readonly_select_sql(sql: str) -> None:
    normalized = normalize_whitespace(sql).lower()
    if not normalized.startswith("select "):
        raise ValueError("Можно выполнять только SELECT-запросы.")

    if ";" in normalized:
        raise ValueError("Можно выполнять только один SELECT-запрос за раз.")

    forbidden_keywords = (
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "truncate",
        "merge",
        "exec",
        "execute",
        "grant",
        "revoke",
    )
    if re.search(r"\b(" + "|".join(forbidden_keywords) + r")\b", normalized):
        raise ValueError("Разрешены только read-only SELECT-запросы.")


def format_cell_value(value) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw_value = bytes(value)
        if len(raw_value) == 16:
            return str(uuid.UUID(bytes_le=raw_value))
        return "0x" + raw_value.hex()
    return str(value)


def format_rows(columns: list[str], rows: list[tuple]) -> str:
    if not rows:
        return "No rows found."

    lines = [", ".join(columns)]
    for row in rows:
        lines.append(", ".join(format_cell_value(value) for value in row))
    return "\n".join(lines)


def _split_top_level_commas(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    in_string = False
    index = 0

    while index < len(value):
        char = value[index]
        if char == "'":
            in_string = not in_string
            if index + 1 < len(value) and value[index + 1] == "'":
                index += 1
        elif not in_string:
            if char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
            elif char == "," and depth == 0:
                parts.append(value[start:index].strip())
                start = index + 1
        index += 1

    parts.append(value[start:].strip())
    return [part for part in parts if part]


def _indent_sql_lines(sql: str) -> str:
    lines = []
    indent = 0
    for raw_line in sql.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith(")") or stripped == ")":
            indent = max(0, indent - 1)
        line_indent = len(raw_line) - len(raw_line.lstrip(" "))
        lines.append(("    " * indent) + (" " * line_indent) + stripped)
        indent += stripped.count("(") - stripped.count(")")
        indent = max(0, indent)
    return "\n".join(lines)


def _newline_before_top_level_phrase(sql: str, phrase: str) -> str:
    result = []
    depth = 0
    in_string = False
    index = 0
    pattern = re.compile(r"\b" + r"\s+".join(re.escape(part) for part in phrase.split()) + r"\b", re.IGNORECASE)

    while index < len(sql):
        char = sql[index]
        if char == "'":
            in_string = not in_string
            result.append(char)
            if index + 1 < len(sql) and sql[index + 1] == "'":
                result.append(sql[index + 1])
                index += 2
                continue
            index += 1
            continue
        if not in_string:
            if char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
            match = pattern.match(sql, index)
            if match and depth == 0:
                result.append("\n" + match.group(0))
                index = match.end()
                continue
        result.append(char)
        index += 1

    return "".join(result)


def format_sql_for_display(sql: str) -> str:
    compact_sql = normalize_whitespace(sql)
    if not compact_sql:
        return ""

    formatted = compact_sql
    formatted = re.sub(r"\bWITH\b", "WITH", formatted, flags=re.IGNORECASE)
    formatted = re.sub(r"\bSELECT\b", "\nSELECT", formatted, flags=re.IGNORECASE)
    formatted = re.sub(r"\bFROM\b", "\nFROM", formatted, flags=re.IGNORECASE)
    formatted = re.sub(r"\bWHERE\b", "\nWHERE", formatted, flags=re.IGNORECASE)
    formatted = re.sub(r"\bGROUP\s+BY\b", "\nGROUP BY", formatted, flags=re.IGNORECASE)
    formatted = re.sub(r"\bHAVING\b", "\nHAVING", formatted, flags=re.IGNORECASE)
    formatted = _newline_before_top_level_phrase(formatted, "ORDER BY")
    formatted = re.sub(r"\bUNION\s+ALL\b", "\nUNION ALL", formatted, flags=re.IGNORECASE)
    formatted = re.sub(r"\bUNION\b", "\nUNION", formatted, flags=re.IGNORECASE)
    formatted = re.sub(r"\)\s+SELECT\b", ")\nSELECT", formatted, flags=re.IGNORECASE)

    lines = []
    for line in formatted.strip().splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("SELECT "):
            select_body = stripped[len("SELECT ") :]
            if "\nFROM" not in select_body:
                select_parts = _split_top_level_commas(select_body)
                if len(select_parts) > 1:
                    lines.append("SELECT")
                    lines.extend(f"    {part}," for part in select_parts[:-1])
                    lines.append(f"    {select_parts[-1]}")
                    continue
        if upper.startswith("WHERE "):
            conditions = re.split(r"\s+AND\s+", stripped[len("WHERE ") :], flags=re.IGNORECASE)
            if len(conditions) > 1:
                lines.append("WHERE")
                lines.extend(f"    {condition} AND" for condition in conditions[:-1])
                lines.append(f"    {conditions[-1]}")
                continue
        lines.append(stripped)

    return _indent_sql_lines("\n".join(lines))


def format_sql_response(sql: str, result_text: str, explanation_text: str) -> str:
    return (
        f"SQL:\n{format_sql_for_display(sql)}\n\n"
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
    explicit_limit_patterns = (
        r"\btop\s+(\d+)\b",
        r"\bтоп\s+(\d+)\b",
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
    if match:
        return max(1, min(int(match.group(1)), 1000))

    no_limit_patterns = (
        r"\ball\b",
        r"\bвс[её]\b",
        r"\bвсе\s+(?:строки|записи|данные|продажи)\b",
        r"\bвсю\b",
        r"\bвесь\b",
        r"\bза\s+весь\s+период\b",
        r"\bбез\s+лимита\b",
        r"\bне\s+используй\s+лимит\b",
        r"\bлимит\s+не\s+используй\b",
        r"\bбез\s+ограничени(?:я|й)\b",
    )
    for pattern in no_limit_patterns:
        if re.search(pattern, question, flags=re.IGNORECASE):
            return None

    return default_limit


def get_table_columns(inspector, schema_name: str, table_name: str) -> list[str]:
    return [column["name"] for column in inspector.get_columns(table_name, schema=schema_name)]


def qualify_table_name(schema_name: str, table_name: str) -> str:
    if schema_name == "LLM" and table_name == "price":
        return "[DWH].[LLM].[price]"
    return f"[{schema_name}].[{table_name}]"


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
    values = parse_ware_id_filters(question)
    return values[0] if values else None


def parse_ware_id_filters(question: str) -> list[str]:
    values: list[str] = []

    match = re.search(r"ware_id\s*[=:]?\s*([A-Za-z0-9_-]+)", question, flags=re.IGNORECASE)
    if match:
        values.append(match.group(1))

    match = re.search(
        r"(?:\u043a\u043e\u0434(?:\u043e\u043c)?\s+\u0441\u043f\u0440\u0443\u0442\u0430|\u0441\u043f\u0440\u0443\u0442(?:\u0430|\u0443)?|sprut(?:\s+code)?)\s*[#:\u2116=\-]?\s*([A-Za-z0-9_ ,;\-]+)",
        question,
        flags=re.IGNORECASE,
    )
    if match:
        values.extend(re.findall(r"[A-Za-z0-9_-]+", match.group(1)))

    match = re.search(
        r"(?:\u0441\u043a\u043b\u0430\u0434[ауюем]?|\u0441\u043a\u043b\u0430\u0434\u044b|\u0434\u043b\u044f\s+\u0441\u043a\u043b\u0430\u0434\u0430|\u0443\s+\u0441\u043a\u043b\u0430\u0434\u0430|\u043f\u043e\s+\u0441\u043a\u043b\u0430\u0434\u0443|\u043a\u043e\u0434\s+\u0441\u043a\u043b\u0430\u0434\u0430)\s+([A-Za-z0-9_-]+)",
        question,
        flags=re.IGNORECASE,
    )
    if match:
        values.append(match.group(1))

    if re.search(r"\b\u0442\u043e\u0432\u0430\u0440", question, flags=re.IGNORECASE):
        tail_match = re.search(r"\bтовар\w*\s+(.+)", question, flags=re.IGNORECASE)
        item_match = re.search(r"\bтовар\w*\s+((?:\d+[\s,;]*)+)", question, flags=re.IGNORECASE)
        if tail_match and item_match:
            tail = tail_match.group(1)
            has_additional_requisite = re.search(
                r"\b(?:бренд\w*|brand|артикул\w*|artikul|article|sku)\b",
                tail,
                flags=re.IGNORECASE,
            )
            if not has_additional_requisite:
                values.extend(re.findall(r"\b\d+\b", item_match.group(1)))
        return list(dict.fromkeys(values))

    match = re.search(
        r"(?:товар[ауом]?|товары|для\s+товара|у\s+товара)\s+([A-Za-z0-9_-]+)",
        question,
        flags=re.IGNORECASE,
    )
    if match:
        values.append(match.group(1))
    return list(dict.fromkeys(values))


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

    relative_filters = parse_relative_date_filters(question)
    if relative_filters:
        return relative_filters

    month_filters = parse_russian_month_filters(question)
    if month_filters:
        return month_filters

    year_match = re.search(
        r"(?:\bin\s+)?\b(20\d{2})\b(?:\s*[-/]\s*(20\d{2}))?\s*(?:year|years|г(?:од|ода|оду)?|yy)?",
        question,
        flags=re.IGNORECASE,
    )
    if year_match:
        start_year = int(year_match.group(1))
        end_year = int(year_match.group(2) or year_match.group(1))
        if start_year > end_year:
            start_year, end_year = end_year, start_year
        filters.append(("between", f"{start_year:04d}-01-01"))
        filters.append(("between_end", f"{end_year:04d}-12-31"))
        return filters

    return filters


def parse_relative_date_filters(
    question: str,
    today: date | None = None,
) -> list[tuple[str, str]]:
    current_date = today or date.today()
    lowered = question.lower()

    if re.search(r"\bс\s+начала\s+года\b", lowered):
        return [
            ("between", f"{current_date.year:04d}-01-01"),
            ("between_end", current_date.isoformat()),
        ]

    if re.search(r"\bс\s+начала\s+месяца\b", lowered):
        return [
            ("between", current_date.replace(day=1).isoformat()),
            ("between_end", current_date.isoformat()),
        ]

    if re.search(r"\bвчера\b", lowered):
        yesterday = current_date - timedelta(days=1)
        return [("eq", yesterday.isoformat())]

    if re.search(r"\bпрошл(?:ый|ого|ом)\s+месяц(?:а|е)?\b", lowered):
        current_month_start = current_date.replace(day=1)
        previous_month_end = current_month_start - timedelta(days=1)
        previous_month_start = previous_month_end.replace(day=1)
        return [
            ("between", previous_month_start.isoformat()),
            ("between_end", previous_month_end.isoformat()),
        ]

    if re.search(r"\bпрошл(?:ый|ого|ом)\s+год(?:а|у|е)?\b", lowered):
        previous_year = current_date.year - 1
        return [
            ("between", f"{previous_year:04d}-01-01"),
            ("between_end", f"{previous_year:04d}-12-31"),
        ]

    half_year_match = re.search(
        r"\b([12])(?:-?(?:е|ое))?\s+полугоди(?:е|я)\b(?:\s+(?:за\s+)?(20\d{2})(?:\s+года)?)?",
        lowered,
    )
    if half_year_match:
        half_year = int(half_year_match.group(1))
        year = int(half_year_match.group(2) or current_date.year)
        start_month = 1 if half_year == 1 else 7
        end_month = 6 if half_year == 1 else 12
        return [
            ("between", f"{year:04d}-{start_month:02d}-01"),
            ("between_end", _month_end(year, end_month)),
        ]

    quarter_match = re.search(
        r"\b([1-4])(?:-?(?:й|ый))?\s+квартал(?:а|е)?\b(?:\s+(?:за\s+)?(20\d{2})(?:\s+года)?)?",
        lowered,
    )
    if quarter_match:
        quarter = int(quarter_match.group(1))
        year = int(quarter_match.group(2) or current_date.year)
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        return [
            ("between", f"{year:04d}-{start_month:02d}-01"),
            ("between_end", _month_end(year, end_month)),
        ]

    return []


def parse_russian_month_filters(question: str) -> list[tuple[str, str]]:
    month_pattern = "|".join(sorted(RUSSIAN_MONTHS, key=len, reverse=True))
    range_match = re.search(
        rf"\b({month_pattern})\b\s*(?:-|–|—|по|до)\s*\b({month_pattern})\b\s+(20\d{{2}})\b",
        question,
        flags=re.IGNORECASE,
    )
    if range_match:
        start_month = RUSSIAN_MONTHS[range_match.group(1).lower()]
        end_month = RUSSIAN_MONTHS[range_match.group(2).lower()]
        year = int(range_match.group(3))
        if start_month > end_month:
            start_month, end_month = end_month, start_month
        return [
            ("between", f"{year:04d}-{start_month:02d}-01"),
            ("between_end", _month_end(year, end_month)),
        ]

    month_year_match = re.search(
        rf"\b({month_pattern})\b\s+(20\d{{2}})\b",
        question,
        flags=re.IGNORECASE,
    )
    if month_year_match:
        month = RUSSIAN_MONTHS[month_year_match.group(1).lower()]
        year = int(month_year_match.group(2))
        return [
            ("between", f"{year:04d}-{month:02d}-01"),
            ("between_end", _month_end(year, month)),
        ]

    year_month_match = re.search(
        rf"\b(20\d{{2}})\b\s+(?:г(?:од|ода|оду)?\s+)?\b({month_pattern})\b",
        question,
        flags=re.IGNORECASE,
    )
    if year_month_match:
        year = int(year_month_match.group(1))
        month = RUSSIAN_MONTHS[year_month_match.group(2).lower()]
        return [
            ("between", f"{year:04d}-{month:02d}-01"),
            ("between_end", _month_end(year, month)),
        ]

    return []


def _month_end(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}"


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
        if "dwh.llm.price" in lowered_question or "[dwh].[llm].[price]" in lowered_question:
            return "LLM", "price"
        if table_name.lower() in lowered_question or qualified_name in lowered_question:
            return schema_name, table_name
    return None


def is_price_question(question: str) -> bool:
    lowered = question.lower()
    price_markers = (
        "price",
        "prices",
        "retail",
        "цен",
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
    qualify_table_name = staticmethod(qualify_table_name)
    extract_column_name = staticmethod(extract_column_name)
    parse_ware_id_filter = staticmethod(parse_ware_id_filter)
    parse_ware_id_filters = staticmethod(parse_ware_id_filters)
    parse_date_filters = staticmethod(parse_date_filters)
    parse_numeric_threshold = staticmethod(parse_numeric_threshold)
    find_table_reference = staticmethod(find_table_reference)
    is_price_question = staticmethod(is_price_question)
    build_where_clause = staticmethod(build_where_clause)
