from __future__ import annotations

import csv
import io
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

MAX_WEB_RESULT_BYTES = 5 * 1024 * 1024
MAX_WEB_CELL_BYTES = 512 * 1024


def normalize_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def run_sql_query(engine, sql: str) -> list[tuple]:
    with engine.connect() as connection:
        result = connection.execute(text(sql))
        return _read_web_safe_rows(result)


def run_sql_query_with_columns(engine, sql: str) -> tuple[list[str], list[tuple]]:
    with engine.connect() as connection:
        result = connection.execute(text(sql))
        return list(result.keys()), _read_web_safe_rows(result)


def _read_web_safe_rows(result) -> list[tuple]:
    rows: list[tuple] = []
    result_size = 0
    for raw_row in result:
        row = tuple(raw_row)
        for value in row:
            if value is None:
                cell_size = 0
            elif isinstance(value, (bytes, bytearray, memoryview)):
                cell_size = len(value)
            elif isinstance(value, str):
                cell_size = len(value) * 4
            else:
                cell_size = len(str(value)) * 4
            if cell_size > MAX_WEB_CELL_BYTES:
                raise ValueError(
                    "Одна ячейка результата слишком велика для веб-чата. "
                    "Используйте файловый экспорт."
                )
            result_size += cell_size
            if result_size > MAX_WEB_RESULT_BYTES:
                raise ValueError(
                    "Результат слишком велик для веб-чата. "
                    "Используйте пагинацию или файловый экспорт."
                )
        rows.append(row)
    return rows


def extract_select_statement(question: str) -> str | None:
    masked_question = _mask_sql_literals_identifiers_and_comments(question)
    top_level_tokens = _top_level_sql_tokens(question)
    select_token = next(
        (token for token in top_level_tokens if token[0] == "select"),
        None,
    )
    if select_token is None:
        return None

    sql_start = select_token[1]
    for token in reversed(top_level_tokens):
        if token[1] >= select_token[1] or token[0] != "with":
            continue
        between = masked_question[token[2] : select_token[1]]
        if re.search(r"\bas\s*\(", between, flags=re.IGNORECASE):
            sql_start = token[1]
            break
    sql = question[sql_start:].strip()
    return sql[:-1].strip() if sql.endswith(";") else sql


def _mask_sql_literals_identifiers_and_comments(sql: str) -> str:
    masked = list(sql)
    index = 0
    length = len(sql)
    state: str | None = None

    while index < length:
        char = sql[index]
        following = sql[index + 1] if index + 1 < length else ""

        if state == "line_comment":
            if char in "\r\n":
                state = None
            else:
                masked[index] = " "
            index += 1
            continue
        if state == "block_comment":
            masked[index] = " "
            if char == "*" and following == "/":
                masked[index + 1] = " "
                state = None
                index += 2
            else:
                index += 1
            continue
        if state == "single_quote":
            masked[index] = " "
            if char == "'" and following == "'":
                masked[index + 1] = " "
                index += 2
            elif char == "'":
                state = None
                index += 1
            else:
                index += 1
            continue
        if state == "double_quote":
            masked[index] = " "
            if char == '"' and following == '"':
                masked[index + 1] = " "
                index += 2
            elif char == '"':
                state = None
                index += 1
            else:
                index += 1
            continue
        if state == "brackets":
            masked[index] = " "
            if char == "]" and following == "]":
                masked[index + 1] = " "
                index += 2
            elif char == "]":
                state = None
                index += 1
            else:
                index += 1
            continue

        if char == "-" and following == "-":
            masked[index] = masked[index + 1] = " "
            state = "line_comment"
            index += 2
            continue
        if char == "/" and following == "*":
            masked[index] = masked[index + 1] = " "
            state = "block_comment"
            index += 2
            continue
        if char == "'":
            masked[index] = " "
            state = "single_quote"
        elif char == '"':
            masked[index] = " "
            state = "double_quote"
        elif char == "[":
            masked[index] = " "
            state = "brackets"
        index += 1

    return "".join(masked)


def _top_level_sql_tokens(sql: str) -> list[tuple[str, int, int]]:
    masked = _mask_sql_literals_identifiers_and_comments(sql)
    tokens: list[tuple[str, int, int]] = []
    depth = 0
    index = 0
    while index < len(masked):
        char = masked[index]
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == 0 and (char.isalnum() or char == "_"):
            start = index
            index += 1
            while index < len(masked) and (
                masked[index].isalnum() or masked[index] == "_"
            ):
                index += 1
            tokens.append((masked[start:index].lower(), start, index))
            continue
        index += 1
    return tokens


def validate_readonly_select_sql(sql: str) -> None:
    code_only = normalize_whitespace(
        _mask_sql_literals_identifiers_and_comments(sql)
    ).lower()
    if code_only.endswith(";"):
        code_only = code_only[:-1].rstrip()

    if not (code_only.startswith("select ") or code_only.startswith("with ")):
        raise ValueError("Можно выполнять только SELECT-запросы.")

    if ";" in code_only:
        raise ValueError("Можно выполнять только один SELECT-запрос за раз.")

    top_level_selects = [
        token for token in _top_level_sql_tokens(sql) if token[0] == "select"
    ]
    if len(top_level_selects) != 1:
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
        "into",
        "backup",
        "restore",
        "dbcc",
        "waitfor",
        "kill",
        "shutdown",
        "use",
        "print",
        "declare",
        "disable",
        "enable",
        "deny",
        "set",
        "checkpoint",
        "reconfigure",
        "dump",
        "revert",
        "commit",
        "rollback",
        "save",
        "raiserror",
        "throw",
        "send",
        "receive",
        "writetext",
        "updatetext",
        "openquery",
        "openrowset",
        "opendatasource",
    )
    if re.search(r"\b(" + "|".join(forbidden_keywords) + r")\b", code_only):
        raise ValueError("Разрешены только read-only SELECT-запросы.")
    if re.search(r"\bnext\s+value\s+for\b", code_only):
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

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(format_cell_value(value) for value in row)
    return output.getvalue().rstrip("\n")


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


def _split_top_level_and_conditions(value: str) -> list[str]:
    masked_value = _mask_sql_literals_identifiers_and_comments(value)
    token_pattern = re.compile(r"\(|\)|\bBETWEEN\b|\bAND\b", flags=re.IGNORECASE)
    parts: list[str] = []
    start = 0
    depth = 0
    between_pending = False

    for match in token_pattern.finditer(masked_value):
        token = match.group().upper()
        if token == "(":
            depth += 1
        elif token == ")":
            depth = max(depth - 1, 0)
        elif depth == 0 and token == "BETWEEN":
            between_pending = True
        elif depth == 0 and token == "AND":
            if between_pending:
                between_pending = False
            else:
                parts.append(value[start : match.start()].strip())
                start = match.end()

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
            conditions = _split_top_level_and_conditions(stripped[len("WHERE ") :])
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
        r"\btop(?:\s*[-–—]\s*|\s+)(\d+)\b",
        r"\bтоп(?:\s*[-–—]\s*|\s+)(\d+)\b",
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
        r"\bбез\s+(?:top|топ(?:а)?)\b",
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

    bare_price_code_match = re.search(
        r"(?:\bистори[яи]\s+цен(?:ы)?|\bцен(?:а|ы))\s+(\d{5,})\s*[?.!]*$",
        question,
        flags=re.IGNORECASE,
    )
    if bare_price_code_match:
        values.append(bare_price_code_match.group(1))

    match = re.search(
        r"ware_id\s*[=:]?\s*([A-Za-z0-9_-]+(?:\s*(?:,|;|\bи\b|\band\b)\s*[A-Za-z0-9_-]+)*)",
        question,
        flags=re.IGNORECASE,
    )
    if match:
        values.extend(
            item
            for item in re.findall(r"[A-Za-z0-9_-]+", match.group(1))
            if item.lower() not in {"and"}
        )

    match = re.search(
        r"(?:код(?:ом)?\s+спрута|спрут(?:а|у)?|sprut(?:\s+code)?)\s*[#:№=\-]?\s*"
        r"([A-Za-z0-9_-]+(?:\s*(?:,|;|\bи\b|\band\b)\s*[A-Za-z0-9_-]+)*)",
        question,
        flags=re.IGNORECASE,
    )
    if match:
        values.extend(
            item
            for item in re.findall(r"[A-Za-z0-9_-]+", match.group(1))
            if item.lower() not in {"and"}
        )

    match = re.search(
        r"(?:склад[ауюем]?|склады|для\s+склада|у\s+склада|по\s+складу|код\s+склада)\s+([A-Za-z0-9_-]+)",
        question,
        flags=re.IGNORECASE,
    )
    if match:
        values.append(match.group(1))

    if re.search(r"\bтовар", question, flags=re.IGNORECASE):
        tail_match = re.search(r"\bтовар\w*\s+(.+)", question, flags=re.IGNORECASE)
        item_match = re.search(
            r"\bтовар\w*\s+([0-9][0-9,\s;]*(?:(?:\bи\b|\band\b)[0-9,\s;]+)*)",
            question,
            flags=re.IGNORECASE,
        )
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

    if has_invalid_explicit_date(question):
        return []

    for value in re.findall(r"\d{4}-\d{2}-\d{2}", question):
        normalized_dates.append(value)

    for value in re.findall(r"\d{2}\.\d{2}\.\d{4}", question):
        try:
            normalized_dates.append(datetime.strptime(value, "%d.%m.%Y").strftime("%Y-%m-%d"))
        except ValueError:
            continue

    deduped_dates = list(dict.fromkeys(normalized_dates))
    if len(deduped_dates) >= 2:
        start_date, end_date = deduped_dates[:2]
        if start_date > end_date:
            return []
        explicit_tokens = re.findall(
            r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}",
            question,
        )
        for token in explicit_tokens:
            normalized_token = (
                datetime.strptime(token, "%d.%m.%Y").strftime("%Y-%m-%d")
                if "." in token
                else token
            )
            if normalized_token != start_date:
                continue
            if re.search(
                rf"(?:\bпосле\b|\bпозже\b|\bafter\b|\blater\s+than\b)\s*{re.escape(token)}",
                question,
                flags=re.IGNORECASE,
            ):
                start_date = (
                    datetime.strptime(start_date, "%Y-%m-%d")
                    + timedelta(days=1)
                ).strftime("%Y-%m-%d")
            break
        end_token = explicit_tokens[1]
        if re.search(
            rf"(?:\bраньше\b|\bbefore\b|\bearlier\s+than\b)\s*{re.escape(end_token)}",
            question,
            flags=re.IGNORECASE,
        ):
            end_date = (
                datetime.strptime(end_date, "%Y-%m-%d")
                - timedelta(days=1)
            ).strftime("%Y-%m-%d")
        filters.append(("between", start_date))
        filters.append(("between_end", end_date))
        return filters
    if len(deduped_dates) == 1:
        date_value = deduped_dates[0]
        escaped_date = re.escape(
            next(
                value
                for value in re.findall(
                    r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}",
                    question,
                )
            )
        )
        if re.search(
            rf"(?:\bпосле\b|\bпозже\b|\bafter\b|\blater\s+than\b)\s*{escaped_date}",
            question,
            flags=re.IGNORECASE,
        ):
            next_date = (
                datetime.strptime(date_value, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
            filters.append(("between", next_date))
        elif re.search(
            rf"(?:\bс\b|\bот\b|начиная\s+с|не\s+ранее|\bsince\b|\bfrom\b)\s*{escaped_date}",
            question,
            flags=re.IGNORECASE,
        ):
            filters.append(("between", date_value))
        elif re.search(
            rf"(?:\bраньше\b|\bbefore\b|\bearlier\s+than\b)\s*{escaped_date}",
            question,
            flags=re.IGNORECASE,
        ):
            previous_date = (
                datetime.strptime(date_value, "%Y-%m-%d") - timedelta(days=1)
            ).strftime("%Y-%m-%d")
            filters.append(("between_end", previous_date))
        elif re.search(
            rf"(?:\bдо\b|\bпо\b|не\s+позднее)\s*{escaped_date}",
            question,
            flags=re.IGNORECASE,
        ):
            filters.append(("between_end", date_value))
        else:
            filters.append(("eq", date_value))
        return filters

    relative_filters = parse_relative_date_filters(question)
    if relative_filters:
        return relative_filters

    russian_day_filters = parse_russian_day_filters(question)
    if russian_day_filters:
        return russian_day_filters

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


def has_invalid_explicit_date(question: str) -> bool:
    for value in re.findall(r"\d{4}-\d{2}-\d{2}", question):
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return True
    for value in re.findall(r"\d{2}\.\d{2}\.\d{4}", question):
        try:
            datetime.strptime(value, "%d.%m.%Y")
        except ValueError:
            return True
    if any(not is_valid for _, _, is_valid in _russian_day_dates(question)):
        return True
    return False


def has_reversed_explicit_date_range(question: str) -> bool:
    normalized_dates: list[str] = []
    for token in re.findall(
        r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}",
        question,
    ):
        try:
            normalized_dates.append(
                datetime.strptime(
                    token,
                    "%d.%m.%Y" if "." in token else "%Y-%m-%d",
                ).strftime("%Y-%m-%d")
            )
        except ValueError:
            return False
    if len(normalized_dates) < 2:
        normalized_dates = [
            normalized_date
            for _, normalized_date, is_valid in _russian_day_dates(question)
            if is_valid
        ]
    deduped_dates = list(dict.fromkeys(normalized_dates))
    return len(deduped_dates) >= 2 and deduped_dates[0] > deduped_dates[1]


def _russian_day_dates(question: str) -> list[tuple[str, str, bool]]:
    month_pattern = "|".join(sorted(RUSSIAN_MONTHS, key=len, reverse=True))
    raw_matches = list(
        re.finditer(
            rf"\b([0-3]?\d)\s+({month_pattern})(?:\s+(20\d{{2}}))?\b",
            question,
            flags=re.IGNORECASE,
        )
    )
    if not raw_matches:
        return []
    explicit_years = [match.group(3) for match in raw_matches if match.group(3)]
    shared_year = int(explicit_years[0]) if len(set(explicit_years)) == 1 else date.today().year
    parsed: list[tuple[str, str, bool]] = []
    for match in raw_matches:
        day = int(match.group(1))
        month = RUSSIAN_MONTHS[match.group(2).lower()]
        year = int(match.group(3) or shared_year)
        normalized_date = f"{year:04d}-{month:02d}-{day:02d}"
        try:
            datetime.strptime(normalized_date, "%Y-%m-%d")
        except ValueError:
            parsed.append((match.group(0), normalized_date, False))
        else:
            parsed.append((match.group(0), normalized_date, True))
    return parsed


def parse_russian_day_filters(question: str) -> list[tuple[str, str]]:
    parsed_dates = _russian_day_dates(question)
    if not parsed_dates or any(not is_valid for _, _, is_valid in parsed_dates):
        return []
    deduped = list(dict.fromkeys((token, value) for token, value, _ in parsed_dates))
    if len(deduped) >= 2:
        start_token, start_date = deduped[0]
        end_token, end_date = deduped[1]
        if start_date > end_date:
            return []
        if re.search(
            rf"(?:\bпосле\b|\bпозже\b)\s*{re.escape(start_token)}",
            question,
            flags=re.IGNORECASE,
        ):
            start_date = (
                datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
        if re.search(
            rf"\bраньше\b\s*{re.escape(end_token)}",
            question,
            flags=re.IGNORECASE,
        ):
            end_date = (
                datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=1)
            ).strftime("%Y-%m-%d")
        return [("between", start_date), ("between_end", end_date)]

    token, date_value = deduped[0]
    escaped_token = re.escape(token)
    if re.search(
        rf"(?:\bпосле\b|\bпозже\b)\s*{escaped_token}",
        question,
        flags=re.IGNORECASE,
    ):
        next_date = (
            datetime.strptime(date_value, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        return [("between", next_date)]
    if re.search(
        rf"\bраньше\b\s*{escaped_token}",
        question,
        flags=re.IGNORECASE,
    ):
        previous_date = (
            datetime.strptime(date_value, "%Y-%m-%d") - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        return [("between_end", previous_date)]
    if re.search(
        rf"(?:\bс\b|\bот\b|начиная\s+с|не\s+ранее)\s*{escaped_token}",
        question,
        flags=re.IGNORECASE,
    ):
        return [("between", date_value)]
    if re.search(
        rf"(?:\bдо\b|\bпо\b|не\s+позднее)\s*{escaped_token}",
        question,
        flags=re.IGNORECASE,
    ):
        return [("between_end", date_value)]
    return [("eq", date_value)]


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
    number_pattern = r"(-?\d+(?:[.,]\d+)?)(?![-.\d])"
    explicit_equality = re.search(
        r"(?:количеств\w*|сумм\w*(?:\s+продаж\w*)?|выручк\w*|оборот\w*|"
        r"остат\w*|марж\w*|"
        r"amount|quantity|cost|price)\s*=\s*" + number_pattern,
        question,
        flags=re.IGNORECASE,
    )
    if explicit_equality:
        return "=", explicit_equality.group(1).replace(",", ".")
    operator_patterns = (
        (">=", r"(?:не\s+менее|как\s+минимум|at\s+least|>=|от)"),
        ("<=", r"(?:не\s+более|как\s+максимум|at\s+most|<=|до)"),
        (">", r"(?:выше|больше|более|more\s+than|greater\s+than|>)"),
        ("<", r"(?:ниже|меньше|less\s+than|<)"),
        ("=", r"(?:равн(?:о|а|ой|ую|ые|ый)?|ровно|equals?)"),
    )
    for operator, marker_pattern in operator_patterns:
        match = re.search(
            rf"{marker_pattern}\s*{number_pattern}",
            question,
            flags=re.IGNORECASE,
        )
        if match:
            return operator, match.group(1).replace(",", ".")
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
