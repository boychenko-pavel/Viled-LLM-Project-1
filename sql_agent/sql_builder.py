from __future__ import annotations

from sqlalchemy import inspect

from sql_agent.intents import QueryIntent
from sql_agent.query_utils import format_rows, format_sql_response, run_sql_query


PREFERRED_COLUMNS = {
    "retail_price": [
        "price_date",
        "ware_id",
        "full_retail_price_kzt",
        "full_retail_price_eur",
        "full_retail_price_usd",
    ],
    "sales": [
        "sale_date",
        "document_number",
        "product_id",
        "quantity",
        "amount",
        "amount_usd",
        "amount_eur",
    ],
}


class SqlBuilder:
    def execute(self, db, intent: QueryIntent) -> str:
        if intent.operation == "schema":
            return self._answer_schema(db, intent)
        if intent.operation == "aggregate":
            return self._answer_aggregate(db, intent)
        if intent.operation == "select":
            return self._answer_select(db, intent)
        return (
            "Не удалось определить намерение запроса. "
            "Сформулируйте вопрос точнее: укажите метрику, дату, таблицу или тип агрегации."
        )

    def _answer_schema(self, db, intent: QueryIntent) -> str:
        inspector = inspect(db._engine)
        columns = inspector.get_columns(intent.table_name, schema=intent.schema_name)
        formatted_columns = "\n".join(
            f"- {column['name']} ({column.get('type', 'unknown')})"
            for column in columns
        )
        sql = (
            "SELECT COLUMN_NAME, DATA_TYPE "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = '{intent.schema_name}' AND TABLE_NAME = '{intent.table_name}' "
            "ORDER BY ORDINAL_POSITION"
        )
        return format_sql_response(
            sql=sql,
            result_text=f"Таблица `{intent.schema_name}.{intent.table_name}` имеет столбцы:\n{formatted_columns}",
            explanation_text="Показана структура таблицы по данным INFORMATION_SCHEMA.COLUMNS.",
        )

    def _answer_select(self, db, intent: QueryIntent) -> str:
        columns = self._resolve_select_columns(intent)
        where_clause = self._build_where_clause(intent)
        order_clause = self._build_order_clause(intent, columns)
        top_clause = f"TOP {intent.limit} " if intent.limit is not None else ""
        sql = (
            f"SELECT {top_clause}"
            + ", ".join(f"[{column_name}]" for column_name in columns)
            + f" FROM {intent.qualified_table_name}"
            + where_clause
            + order_clause
        )
        rows = run_sql_query(db._engine, sql)
        row_limit_text = "все строки" if intent.limit is None else f"до {intent.limit} строк"
        return format_sql_response(
            sql=sql,
            result_text=format_rows(columns, rows),
            explanation_text=(
                f"Показаны {row_limit_text} из таблицы [{intent.schema_name}].[{intent.table_name}]"
                + (" с применёнными фильтрами." if where_clause else ".")
            ),
        )

    def _answer_aggregate(self, db, intent: QueryIntent) -> str:
        metric_column = intent.metric_column
        where_clause = self._build_where_clause(intent)
        top_clause = f"TOP {intent.limit} " if intent.limit is not None and intent.group_by else ""
        group_by_column = intent.group_by

        if intent.aggregate_function == "count":
            aggregate_sql = "COUNT(*)"
            aggregate_alias = "row_count"
        elif intent.aggregate_function == "max":
            aggregate_sql = f"MAX([{metric_column}])"
            aggregate_alias = "max_value"
        elif intent.aggregate_function == "min":
            aggregate_sql = f"MIN([{metric_column}])"
            aggregate_alias = "min_value"
        elif intent.aggregate_function == "sum":
            aggregate_sql = f"SUM([{metric_column}])"
            aggregate_alias = "sum_value"
        else:
            aggregate_sql = f"AVG(CAST([{metric_column}] AS FLOAT))"
            aggregate_alias = "avg_value"

        if group_by_column:
            if intent.aggregate_function == "count":
                select_columns = [group_by_column, "row_count"]
                sql = (
                    f"SELECT {top_clause}[{group_by_column}], COUNT(*) AS row_count "
                    f"FROM {intent.qualified_table_name}"
                    f"{where_clause} GROUP BY [{group_by_column}]"
                )
            else:
                select_columns = [group_by_column, aggregate_alias]
                sql = (
                    f"SELECT {top_clause}[{group_by_column}], {aggregate_sql} AS {aggregate_alias} "
                    f"FROM {intent.qualified_table_name}"
                    f"{where_clause} GROUP BY [{group_by_column}]"
                )
            if group_by_column in {"price_date", "sale_date"}:
                sql += f" ORDER BY [{group_by_column}] DESC"
            elif group_by_column in {"ware_id", "product_id"}:
                if intent.aggregate_function == "count":
                    sql += f" ORDER BY row_count DESC, [{group_by_column}]"
                else:
                    sql += f" ORDER BY {aggregate_alias} DESC, [{group_by_column}]"
            else:
                sql += f" ORDER BY [{group_by_column}]"
            rows = run_sql_query(db._engine, sql)
            metric_label = "количеству строк" if intent.aggregate_function == "count" else f"полю [{metric_column or '*'}]"
            return format_sql_response(
                sql=sql,
                result_text=format_rows(select_columns, rows),
                explanation_text=f"Показана агрегированная статистика по {metric_label} в разрезе [{group_by_column}].",
            )

        sql = f"SELECT {aggregate_sql} AS {aggregate_alias} FROM {intent.qualified_table_name}{where_clause}"
        rows = run_sql_query(db._engine, sql)
        metric_label = "количеству строк" if intent.aggregate_function == "count" else f"полю [{metric_column or '*'}]"
        return format_sql_response(
            sql=sql,
            result_text=format_rows([aggregate_alias], rows),
            explanation_text=f"Показан результат агрегирующего запроса по {metric_label}.",
        )

    def _resolve_select_columns(self, intent: QueryIntent) -> list[str]:
        if intent.requested_columns:
            return intent.requested_columns
        return list(PREFERRED_COLUMNS.get(intent.domain, PREFERRED_COLUMNS["retail_price"]))

    def _build_where_clause(self, intent: QueryIntent) -> str:
        filters = []
        if intent.filters.identifier_column and intent.filters.identifier_value:
            safe_value = intent.filters.identifier_value.replace("'", "''")
            filters.append(f"[{intent.filters.identifier_column}] = '{safe_value}'")

        if intent.filters.date_column:
            if intent.filters.date_eq:
                filters.append(f"[{intent.filters.date_column}] = '{intent.filters.date_eq}'")
            elif intent.filters.date_from and intent.filters.date_to:
                filters.append(
                    f"[{intent.filters.date_column}] BETWEEN '{intent.filters.date_from}' AND '{intent.filters.date_to}'"
                )
            else:
                if intent.filters.date_from:
                    filters.append(f"[{intent.filters.date_column}] >= '{intent.filters.date_from}'")
                if intent.filters.date_to:
                    filters.append(f"[{intent.filters.date_column}] <= '{intent.filters.date_to}'")

        if (
            intent.filters.threshold_column
            and intent.filters.threshold_operator
            and intent.filters.threshold_value
        ):
            filters.append(
                f"[{intent.filters.threshold_column}] {intent.filters.threshold_operator} {intent.filters.threshold_value}"
            )

        if not filters:
            return ""
        return " WHERE " + " AND ".join(filters)

    def _build_order_clause(self, intent: QueryIntent, selected_columns: list[str]) -> str:
        if not intent.sort_column:
            return ""
        direction = "ASC" if intent.sort_direction.lower() == "asc" else "DESC"
        if intent.sort_column in selected_columns or intent.sort_column in {"price_date", "sale_date", "ware_id", "product_id"}:
            return f" ORDER BY [{intent.sort_column}] {direction}"
        return ""
