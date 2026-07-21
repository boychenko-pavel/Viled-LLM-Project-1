from __future__ import annotations

from typing import Callable

from sqlalchemy import inspect

from sql_agent.intents import QueryIntent
from sql_agent.query_utils import format_rows, format_sql_response, run_sql_query

SqlReadyCallback = Callable[[str], None]


PREFERRED_COLUMNS = {
    "retail_price": [
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
    ],
    "sales": [
        "sale_date",
        "document_number",
        "product_id",
        "division_id",
        "quantity",
        "amount",
        "amount_usd",
        "amount_eur",
    ],
    "product_cost": [
        "db",
        "date",
        "op_type",
        "doc_num",
        "product_id",
        "quantity",
        "cost",
        "cost_per_unit",
        "qnt_sum",
        "cost_sum",
        "zeroed",
    ],
    "stock": [
        "source_database",
        "date",
        "recorder_type",
        "recorder_type_guid",
        "recorder_guid",
        "warehouse_id",
        "product_id",
        "quantity",
        "amount",
        "document_id",
        "movement_index",
    ],
    "purchases": [
        "source_database",
        "purchase_date",
        "recorder_type",
        "recorder_number",
        "product_id",
        "quantity",
        "division_id",
        "amount_kzt",
        "NDS_kzt",
        "amount_usd",
        "NDS_usd",
        "amount_eur",
        "NDS_eur",
        "amount_chf",
        "NDS_chf",
    ],
    "product_dimension": [
        "product_id",
        "article",
        "style",
        "fabric",
        "color_code",
        "name",
        "breadcrumbs",
        "bu",
        "category",
        "group",
        "subgroup",
        "product",
        "department",
        "subdepartment",
        "department_vs",
        "subdepartment_vs",
        "brand",
        "season_year",
        "season_short",
        "season",
        "gender",
        "sizechart_type",
        "sizechart",
        "common_size",
        "italian_size",
        "color_eng",
        "color_rus",
        "country",
        "buyer",
        "buyer_assistant",
        "composition",
        "fur",
        "heel",
        "brand_category",
        "individual_number",
        "consigment",
        "carryover",
        "stock_year",
        "world_retail_price",
        "collection_jw",
        "store_jw",
        "volume",
        "tone",
        "line",
        "department_en",
        "url",
        "image_url",
        "barcode",
        "buyer_assistant_vs",
        "buyer_vs",
        "full_composition",
        "size_type",
        "AML",
    ],
    "division_dimension": ["id", "division", "city"],
}


class SqlBuilder:
    def execute(
        self,
        db,
        intent: QueryIntent,
        on_sql_ready: SqlReadyCallback | None = None,
    ) -> str:
        if intent.operation == "schema":
            return self._answer_schema(db, intent, on_sql_ready)
        if intent.operation == "aggregate":
            return self._answer_aggregate(db, intent, on_sql_ready)
        if intent.operation == "stock_balance":
            return self._answer_stock_balance(db, intent, on_sql_ready)
        if intent.operation == "select":
            return self._answer_select(db, intent, on_sql_ready)
        return (
            "Не удалось определить намерение запроса. "
            "Сформулируйте вопрос точнее: укажите метрику, дату, таблицу или тип агрегации."
        )

    def _emit_sql_ready(self, sql: str, on_sql_ready: SqlReadyCallback | None) -> None:
        if on_sql_ready is not None:
            on_sql_ready(sql)

    def _answer_schema(
        self,
        db,
        intent: QueryIntent,
        on_sql_ready: SqlReadyCallback | None = None,
    ) -> str:
        if intent.database_name:
            sql = (
                "SELECT COLUMN_NAME, DATA_TYPE "
                f"FROM [{intent.database_name}].INFORMATION_SCHEMA.COLUMNS "
                f"WHERE TABLE_SCHEMA = '{intent.schema_name}' AND TABLE_NAME = '{intent.table_name}' "
                "ORDER BY ORDINAL_POSITION"
            )
            self._emit_sql_ready(sql, on_sql_ready)
            rows = run_sql_query(db._engine, sql)
            return format_sql_response(
                sql=sql,
                result_text=format_rows(["COLUMN_NAME", "DATA_TYPE"], rows),
                explanation_text="Показана структура таблицы по данным INFORMATION_SCHEMA.COLUMNS.",
            )

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
        self._emit_sql_ready(sql, on_sql_ready)
        return format_sql_response(
            sql=sql,
            result_text=f"Таблица `{intent.qualified_table_name}` имеет столбцы:\n{formatted_columns}",
            explanation_text="Показана структура таблицы по данным INFORMATION_SCHEMA.COLUMNS.",
        )

    def _answer_select(
        self,
        db,
        intent: QueryIntent,
        on_sql_ready: SqlReadyCallback | None = None,
    ) -> str:
        columns = self._resolve_select_columns(intent)
        if intent.latest_per_identifier:
            return self._answer_latest_per_identifier(db, intent, columns, on_sql_ready)

        where_clause = self._build_where_clause(intent)
        order_clause = self._build_order_clause(intent, columns)
        top_clause = f"TOP {intent.limit} " if intent.limit is not None else ""
        from_clause = self._build_from_clause(intent)
        sql = (
            f"SELECT {top_clause}"
            + ", ".join(self._column_expr(intent, column_name) for column_name in columns)
            + f" FROM {from_clause}"
            + where_clause
            + order_clause
        )
        self._emit_sql_ready(sql, on_sql_ready)
        rows = run_sql_query(db._engine, sql)
        row_limit_text = "все строки" if intent.limit is None else f"до {intent.limit} строк"
        return format_sql_response(
            sql=sql,
            result_text=format_rows(columns, rows),
            explanation_text=(
                f"Показаны {row_limit_text} из таблицы {intent.qualified_table_name}"
                + (" с применёнными фильтрами." if where_clause else ".")
            ),
        )

    def _answer_latest_per_identifier(
        self,
        db,
        intent: QueryIntent,
        columns: list[str],
        on_sql_ready: SqlReadyCallback | None = None,
    ) -> str:
        columns = self._resolve_latest_price_columns(columns)
        where_clause = self._build_latest_price_where_clause(intent)
        select_columns = ", ".join(f"[{column_name}]" for column_name in columns)
        cte_columns = ", ".join(
            f"{self._column_expr(intent, column_name)} AS [{column_name}]"
            for column_name in columns
        )
        ware_id = self._column_expr(intent, "ware_id")
        price_date = self._column_expr(intent, "price_date")
        sql = (
            "WITH latest_price AS ("
            f"SELECT {cte_columns}, "
            f"ROW_NUMBER() OVER (PARTITION BY {ware_id} ORDER BY {price_date} DESC) AS rn "
            f"FROM {self._build_from_clause(intent)}"
            f"{where_clause}"
            ") "
            f"SELECT {select_columns} FROM latest_price "
            "WHERE rn = 1 ORDER BY [price_date] DESC, [ware_id]"
        )
        self._emit_sql_ready(sql, on_sql_ready)
        rows = run_sql_query(db._engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(columns, rows),
            explanation_text=(
                "Показана последняя цена по [price_date] для каждого указанного [ware_id]."
            ),
        )

    def _build_latest_price_where_clause(self, intent: QueryIntent) -> str:
        where_clause = self._build_where_clause(intent, include_date=False)
        if intent.filters.date_eq:
            date_filter = f"[price_date] <= '{intent.filters.date_eq}'"
        elif intent.filters.date_to:
            date_filter = f"[price_date] <= '{intent.filters.date_to}'"
        else:
            return where_clause
        if where_clause:
            return where_clause + " AND " + date_filter
        return " WHERE " + date_filter

    def _resolve_latest_price_columns(self, columns: list[str]) -> list[str]:
        price_columns = [
            "full_retail_price_kzt",
            "full_retail_price_eur",
            "full_retail_price_usd",
        ]
        resolved = list(columns)
        for column_name in ("price_date", "ware_id"):
            if column_name not in resolved:
                resolved.insert(0 if column_name == "price_date" else len(resolved), column_name)
        if not any(column_name in resolved for column_name in price_columns):
            resolved.extend(price_columns)
        return self._dedupe(resolved)

    def _answer_aggregate(
        self,
        db,
        intent: QueryIntent,
        on_sql_ready: SqlReadyCallback | None = None,
    ) -> str:
        metric_column = intent.metric_column
        aggregate_function = intent.aggregate_function
        if (
            intent.domain == "sales"
            and aggregate_function == "count"
            and metric_column == "quantity"
        ):
            aggregate_function = "sum"

        where_clause = self._build_where_clause(intent)
        from_clause = self._build_from_clause(intent)
        top_clause = f"TOP {intent.limit} " if intent.limit is not None and intent.group_by else ""
        group_by_column = intent.group_by or self._default_stock_balance_group_by(intent)

        if aggregate_function == "count":
            aggregate_sql = "COUNT(*)"
            aggregate_alias = "row_count"
        elif aggregate_function == "max":
            aggregate_sql = f"MAX([{metric_column}])"
            aggregate_alias = "max_value"
        elif aggregate_function == "min":
            aggregate_sql = f"MIN([{metric_column}])"
            aggregate_alias = "min_value"
        elif aggregate_function == "sum":
            aggregate_sql = f"SUM([{metric_column}])"
            aggregate_alias = "sum_value"
        else:
            aggregate_sql = f"AVG(CAST([{metric_column}] AS FLOAT))"
            aggregate_alias = "avg_value"

        if group_by_column:
            group_by_expr = self._column_expr(intent, group_by_column)
            if aggregate_function == "count":
                select_columns = [group_by_column, "row_count"]
                sql = (
                    f"SELECT {top_clause}{group_by_expr}, COUNT(*) AS row_count "
                    f"FROM {from_clause}"
                    f"{where_clause} GROUP BY {group_by_expr}"
                )
            else:
                select_columns = [group_by_column, aggregate_alias]
                sql = (
                    f"SELECT {top_clause}{group_by_expr}, {self._aggregate_sql(intent, aggregate_function, metric_column)} AS {aggregate_alias} "
                    f"FROM {from_clause}"
                    f"{where_clause} GROUP BY {group_by_expr}"
                )
            if group_by_column in {"price_date", "sale_date", "date", "purchase_date"}:
                sql += f" ORDER BY {group_by_expr} DESC"
            elif group_by_column in {"ware_id", "product_id"}:
                if aggregate_function == "count":
                    sql += f" ORDER BY row_count DESC, {group_by_expr}"
                else:
                    sql += f" ORDER BY {aggregate_alias} DESC, {group_by_expr}"
            else:
                sql += f" ORDER BY {group_by_expr}"
            self._emit_sql_ready(sql, on_sql_ready)
            rows = run_sql_query(db._engine, sql)
            metric_label = "количеству строк" if aggregate_function == "count" else f"полю [{metric_column or '*'}]"
            return format_sql_response(
                sql=sql,
                result_text=format_rows(select_columns, rows),
                explanation_text=f"Показана агрегированная статистика по {metric_label} в разрезе [{group_by_column}].",
            )

        aggregate_sql = self._aggregate_sql(intent, aggregate_function, metric_column)
        sql = f"SELECT {aggregate_sql} AS {aggregate_alias} FROM {from_clause}{where_clause}"
        self._emit_sql_ready(sql, on_sql_ready)
        rows = run_sql_query(db._engine, sql)
        metric_label = "количеству строк" if aggregate_function == "count" else f"полю [{metric_column or '*'}]"
        return format_sql_response(
            sql=sql,
            result_text=format_rows([aggregate_alias], rows),
            explanation_text=f"Показан результат агрегирующего запроса по {metric_label}.",
        )

    def _answer_stock_balance(
        self,
        db,
        intent: QueryIntent,
        on_sql_ready: SqlReadyCallback | None = None,
    ) -> str:
        where_clause = self._build_where_clause(intent, include_date=False)
        from_clause = self._build_from_clause(intent)
        group_by_column = intent.group_by or self._default_stock_balance_group_by(intent)
        group_by_expr = self._column_expr(intent, group_by_column) if group_by_column else None
        group_prefix = f"{group_by_expr}, " if group_by_expr else ""
        group_clause = f" GROUP BY {group_by_expr}" if group_by_expr else ""
        order_clause = f" ORDER BY {group_by_expr}" if group_by_expr else ""

        start_date, end_date = self._stock_balance_dates(intent)
        mode = intent.balance_mode or "end"
        if mode == "period":
            start_filter = self._stock_start_date_filter(intent, start_date)
            end_filter = self._stock_end_date_filter(intent, end_date)
            select_columns = ([group_by_column] if group_by_column else []) + [
                "stock_quantity_start",
                "stock_quantity_end",
            ]
            sql = (
                f"SELECT {group_prefix}"
                f"SUM(CASE WHEN {start_filter} THEN {self._column_expr(intent, 'quantity')} ELSE 0 END) AS stock_quantity_start, "
                f"SUM(CASE WHEN {end_filter} THEN {self._column_expr(intent, 'quantity')} ELSE 0 END) AS stock_quantity_end "
                f"FROM {from_clause}"
                + where_clause
                + group_clause
                + order_clause
            )
        elif mode == "start":
            select_columns = ([group_by_column] if group_by_column else []) + ["stock_quantity_start"]
            sql = (
                f"SELECT {group_prefix}SUM({self._column_expr(intent, 'quantity')}) AS stock_quantity_start "
                f"FROM {from_clause}"
                + self._append_date_filter(where_clause, self._stock_start_date_filter(intent, start_date))
                + group_clause
                + order_clause
            )
        else:
            select_columns = ([group_by_column] if group_by_column else []) + ["stock_quantity_end"]
            if self._has_stock_balance_date_filter(intent):
                where_clause = self._append_date_filter(where_clause, self._stock_end_date_filter(intent, end_date))
            sql = (
                f"SELECT {group_prefix}SUM({self._column_expr(intent, 'quantity')}) AS stock_quantity_end "
                f"FROM {from_clause}"
                + where_clause
                + group_clause
                + order_clause
            )

        self._emit_sql_ready(sql, on_sql_ready)
        rows = run_sql_query(db._engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(select_columns, rows),
            explanation_text=(
                "Остаток рассчитан по таблице "
                f"{intent.qualified_table_name}: сумма signed [quantity] до даты начала "
                "или включая дату окончания периода."
            ),
        )

    def _stock_balance_dates(self, intent: QueryIntent) -> tuple[str, str]:
        if intent.filters.date_from and intent.filters.date_to:
            return intent.filters.date_from, intent.filters.date_to
        if intent.filters.date_eq:
            return intent.filters.date_eq, intent.filters.date_eq
        if intent.filters.date_to:
            return intent.filters.date_to, intent.filters.date_to
        if intent.filters.date_from:
            return intent.filters.date_from, intent.filters.date_from
        return "9999-12-31", "9999-12-31"

    def _default_stock_balance_group_by(self, intent: QueryIntent) -> str | None:
        if len(intent.filters.identifier_values) > 1:
            return intent.filters.identifier_column
        return None

    def _stock_start_date_filter(self, intent: QueryIntent, date_value: str) -> str:
        return f"{self._column_expr(intent, 'date')} < {self._sql_datetime_literal(date_value)}"

    def _stock_end_date_filter(self, intent: QueryIntent, date_value: str) -> str:
        return f"{self._column_expr(intent, 'date')} <= {self._sql_datetime_literal(date_value)}"

    def _sql_datetime_literal(self, date_value: str) -> str:
        return f"CONVERT(datetime2, '{date_value.replace('-', '')}', 112)"

    def _has_stock_balance_date_filter(self, intent: QueryIntent) -> bool:
        return bool(
            intent.filters.date_eq
            or intent.filters.date_from
            or intent.filters.date_to
        )

    def _append_date_filter(self, where_clause: str, date_filter: str) -> str:
        if where_clause:
            return where_clause + " AND " + date_filter
        return " WHERE " + date_filter

    def _resolve_select_columns(self, intent: QueryIntent) -> list[str]:
        if intent.requested_columns:
            return intent.requested_columns
        return list(PREFERRED_COLUMNS.get(intent.domain, PREFERRED_COLUMNS["retail_price"]))

    def _dedupe(self, columns: list[str]) -> list[str]:
        deduped: list[str] = []
        for column_name in columns:
            if column_name not in deduped:
                deduped.append(column_name)
        return deduped

    def _build_where_clause(self, intent: QueryIntent, include_date: bool = True) -> str:
        filters = []
        if intent.filters.identifier_column:
            identifier_values = intent.filters.identifier_values
            if not identifier_values and intent.filters.identifier_value:
                identifier_values = [intent.filters.identifier_value]
            if len(identifier_values) == 1:
                safe_value = identifier_values[0].replace("'", "''")
                filters.append(f"{self._column_expr(intent, intent.filters.identifier_column)} = '{safe_value}'")
            elif len(identifier_values) > 1:
                safe_values = ", ".join(
                    "'" + value.replace("'", "''") + "'" for value in identifier_values
                )
                filters.append(f"{self._column_expr(intent, intent.filters.identifier_column)} IN ({safe_values})")

        if include_date and intent.filters.date_column:
            if intent.filters.date_eq:
                filters.append(f"{self._column_expr(intent, intent.filters.date_column)} = '{intent.filters.date_eq}'")
            elif intent.filters.date_from and intent.filters.date_to:
                filters.append(
                    f"{self._column_expr(intent, intent.filters.date_column)} BETWEEN '{intent.filters.date_from}' AND '{intent.filters.date_to}'"
                )
            else:
                if intent.filters.date_from:
                    filters.append(f"{self._column_expr(intent, intent.filters.date_column)} >= '{intent.filters.date_from}'")
                if intent.filters.date_to:
                    filters.append(f"{self._column_expr(intent, intent.filters.date_column)} <= '{intent.filters.date_to}'")

        if (
            intent.filters.threshold_column
            and intent.filters.threshold_operator
            and intent.filters.threshold_value
        ):
            filters.append(
                f"{self._column_expr(intent, intent.filters.threshold_column)} {intent.filters.threshold_operator} {intent.filters.threshold_value}"
            )

        for column_name, value in intent.filters.equality_filters.items():
            safe_value = value.replace("'", "''")
            filters.append(f"{self._column_expr(intent, column_name)} = '{safe_value}'")

        for column_name, value in intent.filters.dimension_filters.items():
            safe_value = value.replace("'", "''")
            filters.append(f"{self._dimension_column_expr(column_name)} = '{safe_value}'")

        for column_name, value in intent.filters.division_filters.items():
            safe_value = value.replace("'", "''")
            filters.append(f"{self._division_column_expr(column_name)} = '{safe_value}'")

        if not filters:
            return ""
        return " WHERE " + " AND ".join(filters)

    def _build_order_clause(self, intent: QueryIntent, selected_columns: list[str]) -> str:
        if not intent.sort_column:
            return ""
        direction = "ASC" if intent.sort_direction.lower() == "asc" else "DESC"
        sortable_columns = {
            column_name
            for columns in PREFERRED_COLUMNS.values()
            for column_name in columns
        }
        sortable_columns.update(
            {
                "price_date",
                "sale_date",
                "date",
                "purchase_date",
                "ware_id",
                "product_id",
                "warehouse_id",
                "division_id",
                "document_id",
                "recorder_number",
                "movement_index",
                "recorder_type",
                "source_database",
                "division",
                "city",
            }
        )
        if intent.sort_column in selected_columns or intent.sort_column in sortable_columns:
            return f" ORDER BY {self._column_expr(intent, intent.sort_column)} {direction}"
        return ""

    def _build_from_clause(self, intent: QueryIntent) -> str:
        uses_product_dimension = self._uses_dimension_join(intent)
        uses_division_dimension = self._uses_division_join(intent)
        if not uses_product_dimension and not uses_division_dimension:
            return intent.qualified_table_name
        from_clause = f"{intent.qualified_table_name} AS fact"
        if uses_product_dimension:
            fact_identifier = "ware_id" if intent.domain == "retail_price" else "product_id"
            from_clause += (
                " INNER JOIN [DWH].[LLM].[dimension_product] AS dim "
                f"ON fact.[{fact_identifier}] = dim.[product_id]"
            )
        if uses_division_dimension:
            from_clause += (
                " INNER JOIN [DWH].[LLM].[division] AS div "
                "ON fact.[division_id] = div.[id]"
            )
        return from_clause

    def _uses_dimension_join(self, intent: QueryIntent) -> bool:
        return intent.domain in {
            "sales",
            "retail_price",
            "product_cost",
            "stock",
            "purchases",
        } and bool(
            intent.filters.dimension_filters
            or (
                intent.group_by in PREFERRED_COLUMNS["product_dimension"]
                and intent.group_by != "product_id"
            )
        )

    def _uses_division_join(self, intent: QueryIntent) -> bool:
        return intent.domain == "sales" and bool(
            intent.filters.division_filters
            or intent.group_by in {"division", "city"}
        )

    def _column_expr(self, intent: QueryIntent, column_name: str | None) -> str:
        if column_name is None:
            return ""
        if self._uses_dimension_join(intent) or self._uses_division_join(intent):
            if column_name in PREFERRED_COLUMNS.get(intent.domain, ()):
                return self._fact_column_expr(column_name)
            if column_name in PREFERRED_COLUMNS["product_dimension"] and column_name != "product_id":
                return self._dimension_column_expr(column_name)
            if column_name in {"division", "city"}:
                return self._division_column_expr(column_name)
            return self._fact_column_expr(column_name)
        return f"[{column_name}]"

    def _fact_column_expr(self, column_name: str) -> str:
        return f"fact.[{column_name}]"

    def _dimension_column_expr(self, column_name: str) -> str:
        return f"dim.[{column_name}]"

    def _division_column_expr(self, column_name: str) -> str:
        return f"div.[{column_name}]"

    def _aggregate_sql(
        self,
        intent: QueryIntent,
        aggregate_function: str | None,
        metric_column: str | None,
    ) -> str:
        metric_expr = self._column_expr(intent, metric_column) if metric_column else "*"
        if aggregate_function == "max":
            return f"MAX({metric_expr})"
        if aggregate_function == "min":
            return f"MIN({metric_expr})"
        if aggregate_function == "sum":
            return f"SUM({metric_expr})"
        if aggregate_function == "count":
            return "COUNT(*)"
        return f"AVG(CAST({metric_expr} AS FLOAT))"
