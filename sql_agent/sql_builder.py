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

PRODUCT_FACT_DOMAINS = {
    "sales",
    "retail_price",
    "product_cost",
    "stock",
    "purchases",
}

SALES_PRODUCT_COLUMNS = [
    "brand",
    "article",
    "individual_number",
    "name",
]

SALES_TOTAL_COLUMNS = [
    "quantity",
    "amount",
    "amount_usd",
    "amount_eur",
]


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
        if intent.operation == "gross_margin":
            return self._answer_gross_margin(db, intent, on_sql_ready)
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

    def _answer_gross_margin(
        self,
        db,
        intent: QueryIntent,
        on_sql_ready: SqlReadyCallback | None = None,
    ) -> str:
        as_of_filter = self._gross_margin_as_of_filter(intent)
        product_scope_cte = self._build_product_scope_cte(
            intent,
            include_identifier_filters=True,
            required_columns=("article", "brand", "name"),
        )
        stock_having_clause = (
            " HAVING SUM(stock_fact.[quantity]) > 0"
            if intent.filters.in_stock_only
            else ""
        )
        stock_join_clause = (
            "INNER JOIN stock_balance AS stock "
            if intent.filters.in_stock_only
            else "LEFT JOIN stock_balance AS stock "
        )
        base_price_expression = (
            "CAST(price.[full_retail_price_kzt] AS decimal(38, 6))"
        )
        price_expression = base_price_expression
        if intent.discount_percent is not None:
            discount_multiplier = 1 - (intent.discount_percent / 100)
            price_expression += (
                f" * CAST({discount_multiplier:.6f} AS decimal(38, 6))"
            )
        top_clause = f"TOP {intent.limit} " if intent.limit is not None else ""
        order_columns = {
            "article": "dim.[article], margin.[product_id]",
            "brand": "dim.[brand], dim.[article], margin.[product_id]",
            "product_id": "margin.[product_id]",
        }
        order_by = order_columns.get(intent.group_by or "product_id", "margin.[product_id]")
        columns = [
            "остаток",
            "product_id",
            "article",
            "brand",
            "name",
            "price_date",
            "cost_date",
        ]
        if intent.discount_percent is not None:
            columns.extend(
                [
                    "retail_price_kzt_before_discount",
                    "discount_percent",
                    "retail_price_kzt_after_discount",
                ]
            )
            margin_base_price_columns = (
                f"{base_price_expression} AS retail_price_kzt_before_discount, "
                f"CAST({intent.discount_percent:.6f} AS decimal(38, 6)) "
                "AS discount_percent, "
                f"{price_expression} AS retail_price_kzt_after_discount, "
            )
            result_price_columns = (
                "CAST(ROUND(margin.retail_price_kzt_before_discount, 2) "
                "AS decimal(38, 2)) AS retail_price_kzt_before_discount, "
                "CAST(ROUND(margin.discount_percent, 2) "
                "AS decimal(38, 2)) AS discount_percent, "
                "CAST(ROUND(margin.retail_price_kzt_after_discount, 2) "
                "AS decimal(38, 2)) AS retail_price_kzt_after_discount, "
            )
        else:
            columns.append("retail_price_kzt_incl_vat")
            margin_base_price_columns = (
                f"{price_expression} AS retail_price_kzt_vat_included, "
            )
            result_price_columns = (
                "CAST(ROUND(margin.retail_price_kzt_vat_included, 2) "
                "AS decimal(38, 2)) AS retail_price_kzt_incl_vat, "
            )
        columns.extend(
            [
                "retail_price_kzt_excl_vat",
                "cost_kzt_per_unit",
                "gross_profit_kzt_per_unit",
                "gross_margin_percent",
            ]
        )
        sql = (
            f"WITH {product_scope_cte}, stock_balance AS ("
            "SELECT stock_fact.[product_id], "
            "SUM(stock_fact.[quantity]) AS stock_quantity "
            "FROM [DWH].[LLM].[stock] AS stock_fact "
            "INNER JOIN product_scope AS scope "
            "ON stock_fact.[product_id] = scope.[product_id] "
            f"WHERE stock_fact.[date] <= {as_of_filter} "
            f"GROUP BY stock_fact.[product_id]{stock_having_clause}"
            "), ranked_price AS ("
            "SELECT price_fact.[ware_id] AS product_id, price_fact.[price_date], "
            "price_fact.[full_retail_price_kzt], "
            "ROW_NUMBER() OVER (PARTITION BY price_fact.[ware_id] "
            "ORDER BY price_fact.[price_date] DESC) AS rn "
            "FROM [DWH].[LLM].[price] AS price_fact "
            "INNER JOIN product_scope AS scope "
            "ON price_fact.[ware_id] = scope.[product_id] "
            f"WHERE price_fact.[price_date] <= {as_of_filter}"
            "), ranked_cost AS ("
            "SELECT cost_fact.[product_id], cost_fact.[date] AS cost_date, "
            "cost_fact.[qnt_sum], cost_fact.[cost_sum], "
            "ROW_NUMBER() OVER (PARTITION BY cost_fact.[product_id] "
            "ORDER BY cost_fact.[date] DESC) AS rn "
            "FROM [DWH].[LLM].[cost] AS cost_fact "
            "INNER JOIN product_scope AS scope "
            "ON cost_fact.[product_id] = scope.[product_id] "
            f"WHERE cost_fact.[date] <= {as_of_filter}"
            "), margin_base AS ("
            "SELECT price.[product_id], COALESCE(stock.stock_quantity, 0) "
            "AS stock_quantity, price.[price_date], "
            f"{margin_base_price_columns}"
            f"{price_expression} / CAST(1.16 AS decimal(38, 6)) "
            "AS retail_price_kzt_vat_excluded, "
            "cost.cost_date, "
            "CAST(cost.[cost_sum] AS decimal(38, 6)) / "
            "NULLIF(CAST(cost.[qnt_sum] AS decimal(38, 6)), 0) AS unit_cost_kzt "
            "FROM ranked_price AS price "
            f"{stock_join_clause}ON price.[product_id] = stock.[product_id] "
            "INNER JOIN ranked_cost AS cost ON price.[product_id] = cost.[product_id] "
            "WHERE price.rn = 1 AND cost.rn = 1"
            "), margin AS ("
            "SELECT *, retail_price_kzt_vat_excluded - unit_cost_kzt AS gross_margin_kzt, "
            "(retail_price_kzt_vat_excluded - unit_cost_kzt) * CAST(100.0 AS decimal(38, 6)) / "
            "NULLIF(retail_price_kzt_vat_excluded, 0) AS gross_margin_percent "
            "FROM margin_base"
            ") "
            f"SELECT {top_clause}margin.stock_quantity AS [остаток], "
            "margin.[product_id], dim.[article], dim.[brand], dim.[name], "
            "margin.[price_date], margin.cost_date, "
            f"{result_price_columns}"
            "CAST(ROUND(margin.retail_price_kzt_vat_excluded, 2) "
            "AS decimal(38, 2)) AS retail_price_kzt_excl_vat, "
            "CAST(ROUND(margin.unit_cost_kzt, 2) "
            "AS decimal(38, 2)) AS cost_kzt_per_unit, "
            "CAST(ROUND(margin.gross_margin_kzt, 2) "
            "AS decimal(38, 2)) AS gross_profit_kzt_per_unit, "
            "CAST(ROUND(margin.gross_margin_percent, 2) "
            "AS decimal(38, 2)) AS gross_margin_percent "
            "FROM margin "
            "INNER JOIN product_scope AS dim "
            "ON margin.[product_id] = dim.[product_id]"
            f" ORDER BY {order_by}"
        )
        self._emit_sql_ready(sql, on_sql_ready)
        rows = run_sql_query(db._engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(columns, rows),
            explanation_text=(
                "GM рассчитана по каждому коду Спрута"
                + (
                    " только для товаров с положительным текущим остатком"
                    if intent.filters.in_stock_only
                    else " без фильтра по наличию"
                )
                + ". Использованы последняя действующая розничная цена в KZT, "
                + (
                    f"скидка {intent.discount_percent:g}%, "
                    if intent.discount_percent is not None
                    else ""
                )
                + "цена без НДС 16% и текущая средняя себестоимость cost_sum / qnt_sum."
            ),
        )

    def _gross_margin_as_of_filter(self, intent: QueryIntent) -> str:
        as_of_date = intent.filters.date_eq or intent.filters.date_to
        if as_of_date:
            safe_date = as_of_date.replace("'", "''")
            return f"CONVERT(datetime2, '{safe_date.replace('-', '')}', 112)"
        return "GETDATE()"

    def _build_product_scope_cte(
        self,
        intent: QueryIntent,
        *,
        include_identifier_filters: bool = False,
        required_columns: tuple[str, ...] = (),
    ) -> str:
        columns = self._product_scope_columns(intent, required_columns)
        selected_columns = ", ".join(f"dim.[{column_name}]" for column_name in columns)
        where_clause = self._build_product_scope_where_clause(
            intent,
            include_identifier_filters=include_identifier_filters,
        )
        return (
            f"product_scope AS (SELECT {selected_columns} "
            "FROM [DWH].[LLM].[dimension_product] AS dim"
            f"{where_clause})"
        )

    def _product_scope_columns(
        self,
        intent: QueryIntent,
        required_columns: tuple[str, ...] = (),
    ) -> list[str]:
        columns = ["product_id", *required_columns]
        if self._is_sales_detail_select(intent):
            columns.extend(SALES_PRODUCT_COLUMNS)
        columns.extend(intent.filters.dimension_filters)
        columns.extend(intent.requested_columns)
        columns.extend(intent.group_by_columns or [])
        if intent.group_by:
            columns.append(intent.group_by)
        if intent.sort_column:
            columns.append(intent.sort_column)
        columns.extend(intent.filters.dimension_prefix_filters)
        return self._dedupe(
            [
                column_name
                for column_name in columns
                if column_name in PREFERRED_COLUMNS["product_dimension"]
            ]
        )

    def _build_product_scope_where_clause(
        self,
        intent: QueryIntent,
        *,
        include_identifier_filters: bool = False,
    ) -> str:
        filters: list[str] = []
        if include_identifier_filters:
            identifier_values = intent.filters.identifier_values
            if not identifier_values and intent.filters.identifier_value:
                identifier_values = [intent.filters.identifier_value]
            if len(identifier_values) == 1:
                filters.append(
                    "dim.[product_id] = "
                    f"'{identifier_values[0].replace(chr(39), chr(39) * 2)}'"
                )
            elif identifier_values:
                values = ", ".join(
                    "'" + value.replace("'", "''") + "'" for value in identifier_values
                )
                filters.append(f"dim.[product_id] IN ({values})")

        for column_name, value in intent.filters.dimension_filters.items():
            if column_name not in PREFERRED_COLUMNS["product_dimension"]:
                continue
            filters.append(
                self._build_value_filter(f"dim.[{column_name}]", value)
            )
        for column_name, value in intent.filters.dimension_prefix_filters.items():
            if column_name not in PREFERRED_COLUMNS["product_dimension"]:
                continue
            filters.append(
                self._build_prefix_filter(f"dim.[{column_name}]", value)
            )

        return " WHERE " + " AND ".join(filters) if filters else ""

    def _uses_product_scope(self, intent: QueryIntent) -> bool:
        dimension_filter_columns = (
            intent.filters.dimension_filters
            | intent.filters.dimension_prefix_filters
        )
        return intent.domain in PRODUCT_FACT_DOMAINS and any(
            column_name in PREFERRED_COLUMNS["product_dimension"]
            for column_name in dimension_filter_columns
        )

    def _answer_select(
        self,
        db,
        intent: QueryIntent,
        on_sql_ready: SqlReadyCallback | None = None,
    ) -> str:
        columns = self._resolve_select_columns(intent)
        is_sales_detail = self._is_sales_detail_select(intent)
        if is_sales_detail:
            columns = self._sales_detail_columns()
        if intent.latest_per_identifier:
            return self._answer_latest_per_identifier(db, intent, columns, on_sql_ready)

        where_clause = self._build_where_clause(intent)
        order_clause = self._build_order_clause(intent, columns)
        top_clause = f"TOP {intent.limit} " if intent.limit is not None else ""
        distinct_clause = "DISTINCT " if intent.distinct else ""
        from_clause = self._build_from_clause(intent)
        cte_prefix = (
            f"WITH {self._build_product_scope_cte(intent)} "
            if self._uses_product_scope(intent)
            else ""
        )
        select_expressions = [
            self._column_expr(intent, column_name) for column_name in columns
        ]
        if is_sales_detail:
            select_expressions.extend(
                f"SUM({self._column_expr(intent, column_name)}) OVER () "
                f"AS [__total_{column_name}]"
                for column_name in SALES_TOTAL_COLUMNS
            )
        sql = (
            cte_prefix
            + f"SELECT {distinct_clause}{top_clause}"
            + ", ".join(select_expressions)
            + f" FROM {from_clause}"
            + where_clause
            + order_clause
        )
        self._emit_sql_ready(sql, on_sql_ready)
        rows = run_sql_query(db._engine, sql)
        result_text = (
            self._format_sales_detail_rows(columns, rows)
            if is_sales_detail
            else format_rows(columns, rows)
        )
        row_limit_text = "все строки" if intent.limit is None else f"до {intent.limit} строк"
        value_kind = "уникальные значения" if intent.distinct else "строки"
        return format_sql_response(
            sql=sql,
            result_text=result_text,
            explanation_text=(
                f"Показаны {value_kind} ({row_limit_text}) из таблицы {intent.qualified_table_name}"
                + (" с применёнными фильтрами." if where_clause else ".")
            ),
        )

    def _is_sales_detail_select(self, intent: QueryIntent) -> bool:
        return (
            intent.operation == "select"
            and intent.domain == "sales"
            and not intent.distinct
        )

    def _sales_detail_columns(self) -> list[str]:
        columns = list(PREFERRED_COLUMNS["sales"])
        product_id_index = columns.index("product_id") + 1
        columns[product_id_index:product_id_index] = SALES_PRODUCT_COLUMNS
        return columns

    def _format_sales_detail_rows(
        self,
        columns: list[str],
        rows: list[tuple],
    ) -> str:
        if not rows:
            return format_rows(columns, rows)

        detail_width = len(columns)
        detail_rows = [tuple(row[:detail_width]) for row in rows]
        total_values = rows[0][detail_width:]
        total_row: list[object] = [""] * detail_width
        total_row[columns.index("product_id")] = "ИТОГО"
        for column_name, total_value in zip(SALES_TOTAL_COLUMNS, total_values):
            total_row[columns.index(column_name)] = total_value
        detail_rows.append(tuple(total_row))
        return format_rows(columns, detail_rows)

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
        product_scope_prefix = (
            f"WITH {self._build_product_scope_cte(intent)}, "
            if self._uses_product_scope(intent)
            else "WITH "
        )
        sql = (
            product_scope_prefix
            + "latest_price AS ("
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
        cte_prefix = (
            f"WITH {self._build_product_scope_cte(intent)} "
            if self._uses_product_scope(intent)
            else ""
        )
        group_by_columns = intent.group_by_columns or (
            [intent.group_by] if intent.group_by else []
        )
        if not group_by_columns:
            default_group_by = self._default_stock_balance_group_by(intent)
            group_by_columns = [default_group_by] if default_group_by else []
        top_clause = f"TOP {intent.limit} " if intent.limit is not None and group_by_columns else ""

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

        if group_by_columns:
            group_by_exprs = [
                self._column_expr(intent, column_name)
                for column_name in group_by_columns
            ]
            group_by_sql = ", ".join(group_by_exprs)
            if aggregate_function == "count":
                select_columns = [*group_by_columns, "row_count"]
                sql = (
                    cte_prefix
                    + f"SELECT {top_clause}{group_by_sql}, COUNT(*) AS row_count "
                    f"FROM {from_clause}"
                    f"{where_clause} GROUP BY {group_by_sql}"
                )
            else:
                select_columns = [*group_by_columns, aggregate_alias]
                sql = (
                    cte_prefix
                    + f"SELECT {top_clause}{group_by_sql}, {self._aggregate_sql(intent, aggregate_function, metric_column)} AS {aggregate_alias} "
                    f"FROM {from_clause}"
                    f"{where_clause} GROUP BY {group_by_sql}"
                )
            primary_group_by = group_by_columns[0]
            if primary_group_by in {"price_date", "sale_date", "date", "purchase_date"}:
                sql += f" ORDER BY {group_by_sql} DESC"
            elif primary_group_by in {"ware_id", "product_id"}:
                if aggregate_function == "count":
                    sql += f" ORDER BY row_count DESC, {group_by_sql}"
                else:
                    sql += f" ORDER BY {aggregate_alias} DESC, {group_by_sql}"
            else:
                sql += f" ORDER BY {group_by_sql}"
            self._emit_sql_ready(sql, on_sql_ready)
            rows = run_sql_query(db._engine, sql)
            metric_label = "количеству строк" if aggregate_function == "count" else f"полю [{metric_column or '*'}]"
            return format_sql_response(
                sql=sql,
                result_text=format_rows(select_columns, rows),
                explanation_text=f"Показана агрегированная статистика по {metric_label} в разрезе {', '.join(f'[{column}]' for column in group_by_columns)}.",
            )

        aggregate_sql = self._aggregate_sql(intent, aggregate_function, metric_column)
        sql = (
            cte_prefix
            + f"SELECT {aggregate_sql} AS {aggregate_alias} "
            f"FROM {from_clause}{where_clause}"
        )
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
        cte_prefix = (
            f"WITH {self._build_product_scope_cte(intent)} "
            if self._uses_product_scope(intent)
            else ""
        )
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
                cte_prefix
                + f"SELECT {group_prefix}"
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
                cte_prefix
                + f"SELECT {group_prefix}SUM({self._column_expr(intent, 'quantity')}) AS stock_quantity_start "
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
                cte_prefix
                + f"SELECT {group_prefix}SUM({self._column_expr(intent, 'quantity')}) AS stock_quantity_end "
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
            columns = list(intent.requested_columns)
        else:
            columns = list(
                PREFERRED_COLUMNS.get(intent.domain, PREFERRED_COLUMNS["retail_price"])
            )
        columns.extend(self._active_filter_columns(intent))
        return self._dedupe(columns)

    def _active_filter_columns(self, intent: QueryIntent) -> list[str]:
        columns: list[str] = []
        filters = intent.filters

        if (
            filters.identifier_column
            and (filters.identifier_value or filters.identifier_values)
        ):
            columns.append(filters.identifier_column)
        if filters.date_column and (
            filters.date_eq or filters.date_from or filters.date_to
        ):
            columns.append(filters.date_column)
        if (
            filters.threshold_column
            and filters.threshold_operator
            and filters.threshold_value
        ):
            columns.append(filters.threshold_column)

        columns.extend(filters.equality_filters)
        columns.extend(filters.dimension_filters)
        columns.extend(filters.dimension_prefix_filters)
        columns.extend(filters.division_filters)
        return columns

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

        if not self._uses_product_scope(intent):
            for column_name, value in intent.filters.dimension_filters.items():
                filters.append(
                    self._build_value_filter(
                        self._column_expr(intent, column_name),
                        value,
                    )
                )
            for column_name, value in intent.filters.dimension_prefix_filters.items():
                filters.append(
                    self._build_prefix_filter(
                        self._column_expr(intent, column_name),
                        value,
                    )
                )

        for column_name, value in intent.filters.division_filters.items():
            safe_value = value.replace("'", "''")
            filters.append(f"{self._column_expr(intent, column_name)} = '{safe_value}'")

        if intent.filters.in_stock_only:
            product_id = self._availability_product_expr(intent)
            filters.append(
                "EXISTS (SELECT 1 FROM [DWH].[LLM].[stock] AS stock_availability "
                f"WHERE stock_availability.[product_id] = {product_id} "
                "GROUP BY stock_availability.[product_id] "
                "HAVING SUM(stock_availability.[quantity]) > 0)"
            )

        if not filters:
            return ""
        return " WHERE " + " AND ".join(filters)

    def _build_value_filter(
        self,
        column_expression: str,
        value: str | list[str],
    ) -> str:
        values = value if isinstance(value, list) else [value]
        safe_values = [
            "'" + item.replace("'", "''") + "'"
            for item in values
        ]
        if len(safe_values) == 1:
            return f"{column_expression} = {safe_values[0]}"
        return f"{column_expression} IN ({', '.join(safe_values)})"

    def _build_prefix_filter(
        self,
        column_expression: str,
        value: str,
    ) -> str:
        safe_value = (
            value.replace("'", "''")
            .replace("[", "[[]")
            .replace("%", "[%]")
            .replace("_", "[_]")
        )
        return f"{column_expression} LIKE '{safe_value}%'"

    def _availability_product_expr(self, intent: QueryIntent) -> str:
        if intent.domain == "retail_price":
            return self._column_expr(intent, "ware_id")
        return self._column_expr(intent, "product_id")

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
        if not uses_product_dimension and not uses_division_dimension and not intent.filters.in_stock_only:
            return intent.qualified_table_name
        from_clause = f"{intent.qualified_table_name} AS fact"
        if uses_product_dimension:
            fact_identifier = "ware_id" if intent.domain == "retail_price" else "product_id"
            dimension_source = (
                "product_scope"
                if self._uses_product_scope(intent)
                else "[DWH].[LLM].[dimension_product]"
            )
            from_clause += (
                f" INNER JOIN {dimension_source} AS dim "
                f"ON fact.[{fact_identifier}] = dim.[product_id]"
            )
        if uses_division_dimension:
            from_clause += (
                " INNER JOIN [DWH].[LLM].[division] AS div "
                "ON fact.[division_id] = div.[id]"
            )
        return from_clause

    def _uses_dimension_join(self, intent: QueryIntent) -> bool:
        return intent.domain in PRODUCT_FACT_DOMAINS and bool(
            self._is_sales_detail_select(intent)
            or intent.filters.dimension_filters
            or intent.filters.dimension_prefix_filters
            or any(
                column_name in PREFERRED_COLUMNS["product_dimension"]
                and column_name != "product_id"
                for column_name in intent.requested_columns
            )
            or (
                any(
                    column_name in PREFERRED_COLUMNS["product_dimension"]
                    and column_name != "product_id"
                    for column_name in (intent.group_by_columns or [intent.group_by])
                )
            )
        )

    def _uses_division_join(self, intent: QueryIntent) -> bool:
        return intent.domain == "sales" and bool(
            intent.filters.division_filters
            or any(
                column_name in {"division", "city"}
                for column_name in intent.requested_columns
            )
            or any(
                column_name in {"division", "city"}
                for column_name in (intent.group_by_columns or [intent.group_by])
            )
        )

    def _column_expr(self, intent: QueryIntent, column_name: str | None) -> str:
        if column_name is None:
            return ""
        if (
            self._uses_dimension_join(intent)
            or self._uses_division_join(intent)
            or intent.filters.in_stock_only
        ):
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
