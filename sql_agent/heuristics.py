from __future__ import annotations

from langchain_community.utilities.sql_database import SQLDatabase
from sqlalchemy import inspect

from sql_agent.config import CURRENCY_ALIAS_MAP
from sql_agent.query_utils import (
    build_where_clause,
    extract_column_name,
    extract_table_name,
    find_table_reference,
    format_rows,
    format_sql_response,
    get_table_columns,
    is_aggregate_question,
    is_price_question,
    is_schema_question,
    parse_numeric_threshold,
    parse_requested_limit,
    qualify_table_name,
    run_sql_query,
)


def _top_clause(limit: int | None) -> str:
    return f"TOP {limit} " if limit is not None else ""


def answer_schema_question(db: SQLDatabase, question: str) -> str | None:
    if not is_schema_question(question):
        return None

    engine = db._engine
    inspector = inspect(engine)
    table_candidates = []
    for schema_name in inspector.get_schema_names():
        if schema_name.lower() in {"information_schema", "sys"}:
            continue
        try:
            for table_name in inspector.get_table_names(schema=schema_name):
                table_candidates.append(f"{schema_name}.{table_name}")
                table_candidates.append(table_name)
        except Exception:
            continue

    table_name = extract_table_name(question, table_candidates)
    if not table_name:
        return "Не удалось определить таблицу из запроса. Укажите точное имя таблицы."

    schema_name = None
    base_table_name = table_name
    if "." in table_name:
        schema_name, base_table_name = table_name.split(".", 1)

    try:
        if schema_name:
            columns = inspector.get_columns(base_table_name, schema=schema_name)
        else:
            matched_schema = None
            columns = []
            for candidate_schema in inspector.get_schema_names():
                try:
                    candidate_columns = inspector.get_columns(base_table_name, schema=candidate_schema)
                except Exception:
                    continue
                if candidate_columns:
                    matched_schema = candidate_schema
                    columns = candidate_columns
                    break
            schema_name = matched_schema
    except Exception:
        return (
            f"Не удалось прочитать схему таблицы `{table_name}`. "
            "Проверьте имя таблицы или обновите schema snapshot."
        )

    if not columns:
        return f"У таблицы `{table_name}` не удалось найти столбцы."

    sql = (
        "SELECT COLUMN_NAME, DATA_TYPE "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA = '{schema_name}' AND TABLE_NAME = '{base_table_name}' "
        "ORDER BY ORDINAL_POSITION"
    )
    formatted_columns = "\n".join(
        f"- {column['name']} ({column.get('type', 'unknown')})"
        for column in columns
    )
    qualified_name = f"{schema_name}.{base_table_name}" if schema_name else base_table_name
    return format_sql_response(
        sql=sql,
        result_text=f"Таблица `{qualified_name}` имеет столбцы:\n{formatted_columns}",
        explanation_text="Показана структура таблицы по данным INFORMATION_SCHEMA.COLUMNS.",
    )


def answer_simple_data_question(db: SQLDatabase, question: str) -> str | None:
    engine = db._engine
    table_ref = find_table_reference(engine, question)
    if table_ref is None and is_price_question(question):
        table_ref = ("LLM", "price")
    if not table_ref:
        return None

    schema_name, table_name = table_ref
    inspector = inspect(engine)
    columns = get_table_columns(inspector, schema_name, table_name)
    if not columns:
        return None

    limit = parse_requested_limit(question)
    preferred_columns = [
        column_name
        for column_name in [
            "price_date",
            "ware_id",
            "full_retail_price_kzt",
            "full_retail_price_eur",
            "full_retail_price_usd",
            "full_price_level_kzt",
            "full_price_level_usd",
            "full_price_level_eur",
            "_RANK",
            "brand",
        ]
        if column_name in columns
    ]
    selected_columns = preferred_columns or columns[: min(5, len(columns))]
    where_clause = build_where_clause(question, columns)

    order_column = None
    for candidate in ("price_date", "date", "created_at", "updated_at", "id"):
        if candidate in columns:
            order_column = candidate
            break

    sql = (
        f"SELECT {_top_clause(limit)}"
        + ", ".join(f"[{column_name}]" for column_name in selected_columns)
        + f" FROM {qualify_table_name(schema_name, table_name)}"
    )
    sql += where_clause
    if order_column:
        sql += f" ORDER BY [{order_column}] DESC"

    rows = run_sql_query(engine, sql)
    return format_sql_response(
        sql=sql,
        result_text=format_rows(selected_columns, rows),
        explanation_text=(
            f"Показаны до {limit} строк из таблицы {qualify_table_name(schema_name, table_name)}"
            + (" с применёнными фильтрами." if where_clause else ".")
        ),
    )


def answer_explicit_field_aggregate_question(db: SQLDatabase, question: str) -> str | None:
    lowered = question.lower()
    if not any(marker in lowered for marker in ("поле", "field", "значение", "value")):
        return None

    engine = db._engine
    inspector = inspect(engine)

    table_candidates: list[tuple[str, str]] = []
    for schema_name in inspector.get_schema_names():
        if schema_name.lower() in {"information_schema", "sys"}:
            continue
        try:
            table_names = inspector.get_table_names(schema=schema_name)
        except Exception:
            continue
        for table_name in table_names:
            table_candidates.append((schema_name, table_name))

    for schema_name, table_name in table_candidates:
        columns = get_table_columns(inspector, schema_name, table_name)
        column_name = extract_column_name(question, columns)
        if not column_name:
            continue

        where_clause = build_where_clause(question, columns)
        if (
            table_name in {"sales", "sales_table"}
            and column_name == "quantity"
            and ("сколько" in lowered or "count" in lowered or "количество" in lowered)
        ):
            sql = f"SELECT SUM([quantity]) AS sum_value FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
            rows = run_sql_query(engine, sql)
            return format_sql_response(
                sql=sql,
                result_text=format_rows(["sum_value"], rows),
                explanation_text="Показана сумма по полю [quantity].",
            )
        if any(marker in lowered for marker in ("максим", "max", "самое высокое", "highest")):
            sql = f"SELECT MAX([{column_name}]) AS max_value FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
            rows = run_sql_query(engine, sql)
            return format_sql_response(
                sql=sql,
                result_text=format_rows(["max_value"], rows),
                explanation_text=f"Показано максимальное значение поля [{column_name}].",
            )
        if any(marker in lowered for marker in ("миним", "min", "самое низкое", "lowest")):
            sql = f"SELECT MIN([{column_name}]) AS min_value FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
            rows = run_sql_query(engine, sql)
            return format_sql_response(
                sql=sql,
                result_text=format_rows(["min_value"], rows),
                explanation_text=f"Показано минимальное значение поля [{column_name}].",
            )
        if any(marker in lowered for marker in ("средн", "avg", "average")):
            sql = (
                f"SELECT AVG(CAST([{column_name}] AS FLOAT)) AS avg_value "
                f"FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
            )
            rows = run_sql_query(engine, sql)
            return format_sql_response(
                sql=sql,
                result_text=format_rows(["avg_value"], rows),
                explanation_text=f"Показано среднее значение поля [{column_name}].",
            )
        if any(marker in lowered for marker in ("сумм", "sum", "итого")):
            sql = f"SELECT SUM([{column_name}]) AS sum_value FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
            rows = run_sql_query(engine, sql)
            return format_sql_response(
                sql=sql,
                result_text=format_rows(["sum_value"], rows),
                explanation_text=f"Показана сумма по полю [{column_name}].",
            )

    return None


def answer_ranked_or_filtered_price_question(db: SQLDatabase, question: str) -> str | None:
    lowered = question.lower()
    trigger_markers = (
        "топ",
        "top",
        "выше",
        "ниже",
        "больше",
        "меньше",
        "цена у товара",
        "цена товара",
        "price for",
    )
    if not any(marker in lowered for marker in trigger_markers):
        return None

    engine = db._engine
    table_ref = find_table_reference(engine, question) or ("LLM", "price")
    schema_name, table_name = table_ref

    inspector = inspect(engine)
    columns = get_table_columns(inspector, schema_name, table_name)
    if not columns:
        return None

    column_name = extract_column_name(question, columns) or next(
        (
            name
            for name in [
                "full_retail_price_kzt",
                "full_retail_price_eur",
                "full_retail_price_usd",
            ]
            if name in columns
        ),
        None,
    )
    if not column_name:
        return None

    limit = parse_requested_limit(question)
    where_parts = []

    base_where = build_where_clause(question, columns)
    if base_where:
        where_parts.append(base_where.replace(" WHERE ", "", 1))

    threshold = parse_numeric_threshold(question)
    if threshold:
        op, value = threshold
        where_parts.append(f"[{column_name}] {op} {value}")

    where_clause = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""

    if ("цена у товара" in lowered or "цена товара" in lowered) and "ware_id" in columns:
        sql = (
            f"SELECT {_top_clause(limit)}[price_date], [ware_id], [{column_name}] "
            f"FROM {qualify_table_name(schema_name, table_name)}"
            f"{where_clause} ORDER BY [price_date] DESC"
        )
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["price_date", "ware_id", column_name], rows),
            explanation_text=f"Показана цена по полю [{column_name}] для выбранного товара.",
        )

    if "топ" in lowered or "top" in lowered:
        sql = (
            f"SELECT {_top_clause(limit)}[price_date], [ware_id], [{column_name}] "
            f"FROM {qualify_table_name(schema_name, table_name)}"
            f"{where_clause} ORDER BY [{column_name}] DESC, [price_date] DESC"
        )
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["price_date", "ware_id", column_name], rows),
            explanation_text=f"Показаны top {limit} записей по полю [{column_name}].",
        )

    if threshold:
        sql = (
            f"SELECT {_top_clause(limit)}[price_date], [ware_id], [{column_name}] "
            f"FROM {qualify_table_name(schema_name, table_name)}"
            f"{where_clause} ORDER BY [{column_name}] DESC, [price_date] DESC"
        )
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["price_date", "ware_id", column_name], rows),
            explanation_text=f"Показаны записи с фильтром по полю [{column_name}].",
        )

    return None


def answer_currency_aggregate_question(db: SQLDatabase, question: str) -> str | None:
    lowered = question.lower()
    if not any(alias in lowered for alias in CURRENCY_ALIAS_MAP):
        return None

    engine = db._engine
    table_ref = find_table_reference(engine, question) or ("LLM", "price")
    schema_name, table_name = table_ref

    inspector = inspect(engine)
    columns = get_table_columns(inspector, schema_name, table_name)
    if not columns:
        return None

    column_name = extract_column_name(question, columns)
    if not column_name:
        return None

    where_clause = build_where_clause(question, columns)
    limit = parse_requested_limit(question)
    aggregate_sql = None
    aggregate_alias = None

    if any(marker in lowered for marker in ("максим", "max", "самое высокое", "highest")):
        aggregate_sql = f"MAX([{column_name}])"
        aggregate_alias = "max_value"
    elif any(marker in lowered for marker in ("миним", "min", "самое низкое", "lowest")):
        aggregate_sql = f"MIN([{column_name}])"
        aggregate_alias = "min_value"
    elif any(marker in lowered for marker in ("средн", "avg", "average")):
        aggregate_sql = f"AVG(CAST([{column_name}] AS FLOAT))"
        aggregate_alias = "avg_value"
    elif any(marker in lowered for marker in ("сумм", "sum", "итого")):
        aggregate_sql = f"SUM([{column_name}])"
        aggregate_alias = "sum_value"

    if ("по дате" in lowered or "по датам" in lowered) and "price_date" in columns:
        aggregate_sql = aggregate_sql or f"AVG(CAST([{column_name}] AS FLOAT))"
        aggregate_alias = aggregate_alias or "avg_value"
        sql = (
            f"SELECT {_top_clause(limit)}[price_date], COUNT(*) AS row_count, "
            f"{aggregate_sql} AS {aggregate_alias} "
            f"FROM {qualify_table_name(schema_name, table_name)}"
            f"{where_clause} GROUP BY [price_date] ORDER BY [price_date] DESC"
        )
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["price_date", "row_count", aggregate_alias], rows),
            explanation_text=f"Показана агрегированная статистика по полю [{column_name}] в разрезе дат.",
        )

    if ("по ware_id" in lowered or "по товара" in lowered or "по товар" in lowered) and "ware_id" in columns:
        aggregate_sql = aggregate_sql or f"AVG(CAST([{column_name}] AS FLOAT))"
        aggregate_alias = aggregate_alias or "avg_value"
        sql = (
            f"SELECT {_top_clause(limit)}[ware_id], COUNT(*) AS row_count, "
            f"{aggregate_sql} AS {aggregate_alias} "
            f"FROM {qualify_table_name(schema_name, table_name)}"
            f"{where_clause} GROUP BY [ware_id] ORDER BY row_count DESC, [ware_id]"
        )
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["ware_id", "row_count", aggregate_alias], rows),
            explanation_text=f"Показана агрегированная статистика по полю [{column_name}] в разрезе товаров.",
        )

    if any(marker in lowered for marker in ("максим", "max", "самое высокое", "highest")):
        sql = f"SELECT MAX([{column_name}]) AS max_value FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["max_value"], rows),
            explanation_text=f"Показано максимальное значение поля [{column_name}].",
        )

    if any(marker in lowered for marker in ("миним", "min", "самое низкое", "lowest")):
        sql = f"SELECT MIN([{column_name}]) AS min_value FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["min_value"], rows),
            explanation_text=f"Показано минимальное значение поля [{column_name}].",
        )

    if any(marker in lowered for marker in ("средн", "avg", "average")):
        sql = (
            f"SELECT AVG(CAST([{column_name}] AS FLOAT)) AS avg_value "
            f"FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
        )
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["avg_value"], rows),
            explanation_text=f"Показано среднее значение поля [{column_name}].",
        )

    if any(marker in lowered for marker in ("сумм", "sum", "итого")):
        sql = f"SELECT SUM([{column_name}]) AS sum_value FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
        rows = run_sql_query(engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(["sum_value"], rows),
            explanation_text=f"Показана сумма по полю [{column_name}].",
        )

    return None


def answer_simple_aggregate_question(db: SQLDatabase, question: str) -> str | None:
    if not is_aggregate_question(question):
        return None

    engine = db._engine
    table_ref = find_table_reference(engine, question)
    if not table_ref:
        return None

    schema_name, table_name = table_ref
    inspector = inspect(engine)
    columns = get_table_columns(inspector, schema_name, table_name)
    if not columns:
        return None

    lowered = question.lower()
    where_clause = build_where_clause(question, columns)
    limit = parse_requested_limit(question)
    price_column = next(
        (
            name
            for name in [
                "full_retail_price_kzt",
                "full_retail_price_eur",
                "full_retail_price_usd",
            ]
            if name in columns
        ),
        None,
    )

    sql = None
    output_columns: list[str] = []

    if (
        table_name in {"sales", "sales_table"}
        and "quantity" in columns
        and ("quantity" in lowered or "по полю quantity" in lowered)
        and ("сколько" in lowered or "count" in lowered or "количество" in lowered)
    ):
        sql = f"SELECT SUM([quantity]) AS sum_value FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
        output_columns = ["sum_value"]
    elif ("сколько" in lowered or "count" in lowered or "количество" in lowered):
        sql = f"SELECT COUNT(*) AS row_count FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
        output_columns = ["row_count"]
    elif ("по дате" in lowered or "по датам" in lowered) and "price_date" in columns:
        metric_column = price_column or columns[0]
        sql = (
            f"SELECT {_top_clause(limit)}[price_date], COUNT(*) AS row_count, "
            f"AVG(CAST([{metric_column}] AS FLOAT)) AS avg_value "
            f"FROM {qualify_table_name(schema_name, table_name)}"
            f"{where_clause} GROUP BY [price_date] ORDER BY [price_date] DESC"
        )
        output_columns = ["price_date", "row_count", "avg_value"]
    elif ("по ware_id" in lowered or "по товара" in lowered or "по товар" in lowered) and "ware_id" in columns:
        metric_column = price_column or columns[0]
        sql = (
            f"SELECT {_top_clause(limit)}[ware_id], COUNT(*) AS row_count, "
            f"AVG(CAST([{metric_column}] AS FLOAT)) AS avg_value "
            f"FROM {qualify_table_name(schema_name, table_name)}"
            f"{where_clause} GROUP BY [ware_id] ORDER BY row_count DESC, [ware_id]"
        )
        output_columns = ["ware_id", "row_count", "avg_value"]
    elif ("максим" in lowered or "max" in lowered) and price_column:
        sql = (
            f"SELECT MAX([{price_column}]) AS max_value "
            f"FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
        )
        output_columns = ["max_value"]
    elif ("миним" in lowered or "min" in lowered) and price_column:
        sql = (
            f"SELECT MIN([{price_column}]) AS min_value "
            f"FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
        )
        output_columns = ["min_value"]
    elif ("средн" in lowered or "avg" in lowered or "average" in lowered) and price_column:
        sql = (
            f"SELECT AVG(CAST([{price_column}] AS FLOAT)) AS avg_value "
            f"FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
        )
        output_columns = ["avg_value"]
    elif ("сумм" in lowered or "sum" in lowered or "итого" in lowered) and price_column:
        sql = (
            f"SELECT SUM([{price_column}]) AS sum_value "
            f"FROM {qualify_table_name(schema_name, table_name)}{where_clause}"
        )
        output_columns = ["sum_value"]

    if not sql:
        return None

    rows = run_sql_query(engine, sql)
    return format_sql_response(
        sql=sql,
        result_text=format_rows(output_columns, rows),
        explanation_text="Показан результат агрегирующего запроса.",
    )


class HeuristicSqlResponder:
    def __init__(self, db: SQLDatabase):
        self.db = db

    def answer_schema_question(self, question: str) -> str | None:
        return answer_schema_question(self.db, question)

    def answer_simple_data_question(self, question: str) -> str | None:
        return answer_simple_data_question(self.db, question)

    def answer_explicit_field_aggregate_question(self, question: str) -> str | None:
        return answer_explicit_field_aggregate_question(self.db, question)

    def answer_ranked_or_filtered_price_question(self, question: str) -> str | None:
        return answer_ranked_or_filtered_price_question(self.db, question)

    def answer_currency_aggregate_question(self, question: str) -> str | None:
        return answer_currency_aggregate_question(self.db, question)

    def answer_simple_aggregate_question(self, question: str) -> str | None:
        return answer_simple_aggregate_question(self.db, question)

    def answer(self, question: str) -> str | None:
        for responder in (
            self.answer_schema_question,
            self.answer_explicit_field_aggregate_question,
            self.answer_currency_aggregate_question,
            self.answer_ranked_or_filtered_price_question,
            self.answer_simple_aggregate_question,
            self.answer_simple_data_question,
        ):
            answer = responder(question)
            if answer is not None:
                return answer
        return None
