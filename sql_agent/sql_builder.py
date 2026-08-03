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
        "quantity",
        "full_price",
        "price",
        "amount",
        "loan",
        "cash",
        "card",
        "certificate",
        "bonus",
        "discount",
        "channel",
        "payment_method",
        "partner_id",
        "customer_status",
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
    "full_price",
    "amount",
    "loan",
    "cash",
    "card",
    "certificate",
    "bonus",
    "discount",
]

PURCHASE_UNIT_COST_AMOUNT_COLUMNS = {
    "unit_cost_kzt": "amount_kzt",
    "unit_cost_usd": "amount_usd",
    "unit_cost_eur": "amount_eur",
    "unit_cost_chf": "amount_chf",
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
        margin_threshold_clause = ""
        if (
            intent.filters.threshold_column == "gross_margin_percent"
            and intent.filters.threshold_operator in {"=", ">", "<", ">=", "<="}
            and intent.filters.threshold_value
        ):
            margin_threshold_clause = (
                " WHERE margin.gross_margin_percent "
                f"{intent.filters.threshold_operator} "
                f"{intent.filters.threshold_value}"
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
        if intent.sort_column == "gross_margin_percent":
            direction = "ASC" if intent.sort_direction.lower() == "asc" else "DESC"
            order_by = f"margin.gross_margin_percent {direction}, margin.[product_id]"
        else:
            order_by = order_columns.get(intent.group_by or "product_id", "margin.[product_id]")
        columns = [
            "остаток",
            "product_id",
            "article",
            "brand",
            "name",
            "price_date",
            "cost_date",
            "retail_price_kzt_incl_vat",
            "retail_price_kzt_excl_vat",
            "cost_kzt_per_unit",
            "gross_profit_kzt_per_unit",
            "gross_margin_percent",
        ]
        if intent.discount_percent is not None:
            margin_base_price_columns = (
                f"{base_price_expression} AS retail_price_kzt_before_discount, "
                f"CAST({intent.discount_percent:.6f} AS decimal(38, 6)) "
                "AS discount_percent, "
                f"{price_expression} AS retail_price_kzt_after_discount, "
                f"{price_expression} AS retail_price_kzt_vat_included, "
            )
            discount_result_columns = (
                "CAST(ROUND(margin.retail_price_kzt_before_discount, 2) "
                "AS decimal(38, 2)) AS retail_price_kzt_before_discount, "
                "CAST(ROUND(margin.discount_percent, 2) "
                "AS decimal(38, 2)) AS discount_percent, "
                "CAST(ROUND(margin.retail_price_kzt_after_discount, 2) "
                "AS decimal(38, 2)) AS retail_price_kzt_after_discount, "
            )
            columns.extend(
                [
                    "retail_price_kzt_before_discount",
                    "discount_percent",
                    "retail_price_kzt_after_discount",
                ]
            )
        else:
            margin_base_price_columns = (
                f"{price_expression} AS retail_price_kzt_vat_included, "
            )
            discount_result_columns = ""
        result_price_columns = (
            "CAST(ROUND(margin.retail_price_kzt_vat_included, 2) "
            "AS decimal(38, 2)) AS retail_price_kzt_incl_vat, "
        )
        sql = (
            f"WITH {product_scope_cte}, stock_balance AS ("
            "SELECT stock_fact.[product_id], "
            "SUM(stock_fact.[quantity]) AS stock_quantity "
            "FROM [DWH].[LLM].[stock] AS stock_fact "
            "INNER JOIN product_scope AS scope "
            "ON stock_fact.[product_id] = scope.[product_id] "
            f"WHERE stock_fact.[date] < {as_of_filter} "
            f"GROUP BY stock_fact.[product_id]{stock_having_clause}"
            "), ranked_price AS ("
            "SELECT price_fact.[ware_id] AS product_id, price_fact.[price_date], "
            "price_fact.[full_retail_price_kzt], "
            "ROW_NUMBER() OVER (PARTITION BY price_fact.[ware_id] "
            "ORDER BY price_fact.[price_date] DESC) AS rn "
            "FROM [DWH].[LLM].[price] AS price_fact "
            "INNER JOIN product_scope AS scope "
            "ON price_fact.[ware_id] = scope.[product_id] "
            f"WHERE price_fact.[price_date] < {as_of_filter}"
            "), ranked_cost AS ("
            "SELECT cost_fact.[product_id], cost_fact.[date] AS cost_date, "
            "cost_fact.[qnt_sum], cost_fact.[cost_sum], "
            "ROW_NUMBER() OVER (PARTITION BY cost_fact.[product_id] "
            "ORDER BY cost_fact.[date] DESC) AS rn "
            "FROM [DWH].[LLM].[cost] AS cost_fact "
            "INNER JOIN product_scope AS scope "
            "ON cost_fact.[product_id] = scope.[product_id] "
            f"WHERE cost_fact.[date] < {as_of_filter}"
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
            "AS decimal(38, 2)) AS gross_margin_percent"
            + (f", {discount_result_columns[:-2]}" if discount_result_columns else "")
            + " "
            "FROM margin "
            "INNER JOIN product_scope AS dim "
            "ON margin.[product_id] = dim.[product_id]"
            f"{margin_threshold_clause}"
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
            return (
                "DATEADD(day, 1, "
                f"CONVERT(datetime2, '{safe_date.replace('-', '')}', 112))"
            )
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
        if intent.metric_column:
            columns.append(intent.metric_column)
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
        sales_detail_total_columns = list(SALES_TOTAL_COLUMNS)
        if is_sales_detail:
            columns = self._sales_detail_columns(intent)
            if intent.metric_column in {"amount_usd", "amount_eur"}:
                sales_detail_total_columns.append(intent.metric_column)
        if intent.latest_per_identifier:
            if intent.domain == "product_cost":
                return self._answer_latest_cost_balance(
                    db,
                    intent,
                    columns,
                    on_sql_ready,
                )
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
            self._select_column_expr(intent, column_name) for column_name in columns
        ]
        if is_sales_detail:
            select_expressions.extend(
                f"SUM({self._column_expr(intent, column_name)}) OVER () "
                f"AS [__total_{column_name}]"
                for column_name in sales_detail_total_columns
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
            self._format_sales_detail_rows(
                columns,
                rows,
                sales_detail_total_columns,
            )
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

    def _sales_detail_columns(self, intent: QueryIntent) -> list[str]:
        columns = list(PREFERRED_COLUMNS["sales"])
        if intent.metric_column in {"amount_usd", "amount_eur"}:
            amount_index = columns.index("amount") + 1
            columns.insert(amount_index, intent.metric_column)
        product_id_index = columns.index("product_id") + 1
        columns[product_id_index:product_id_index] = SALES_PRODUCT_COLUMNS
        return columns

    def _format_sales_detail_rows(
        self,
        columns: list[str],
        rows: list[tuple],
        total_columns: list[str],
    ) -> str:
        if not rows:
            return format_rows(columns, rows)

        detail_width = len(columns)
        detail_rows = [tuple(row[:detail_width]) for row in rows]
        total_values = rows[0][detail_width:]
        total_row: list[object] = [""] * detail_width
        total_row[columns.index("product_id")] = "ИТОГО"
        for column_name, total_value in zip(total_columns, total_values):
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
        top_clause = f"TOP {intent.limit} " if intent.limit is not None else ""
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
            f"SELECT {top_clause}{select_columns} FROM latest_price "
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

    def _answer_latest_cost_balance(
        self,
        db,
        intent: QueryIntent,
        columns: list[str],
        on_sql_ready: SqlReadyCallback | None = None,
    ) -> str:
        for required_column in ("date", "product_id", "qnt_sum", "cost_sum"):
            if required_column not in columns:
                columns.append(required_column)
        where_clause = self._build_where_clause(intent, include_date=False)
        cutoff_date = intent.filters.date_eq or intent.filters.date_to
        if cutoff_date:
            cutoff_filter = (
                f"{self._column_expr(intent, 'date')} < DATEADD(day, 1, "
                f"{self._sql_datetime_literal(cutoff_date)})"
            )
            where_clause = self._append_date_filter(where_clause, cutoff_filter)
        cte_prefix = (
            f"WITH {self._build_product_scope_cte(intent)}, "
            if self._uses_product_scope(intent)
            else "WITH "
        )
        cte_columns = ", ".join(
            f"{self._column_expr(intent, column_name)} AS [{column_name}]"
            for column_name in columns
        )
        product_id = self._column_expr(intent, "product_id")
        cost_date = self._column_expr(intent, "date")
        top_clause = f"TOP {intent.limit} " if intent.limit is not None else ""
        output_columns = list(columns)
        select_expressions = [f"[{column_name}]" for column_name in columns]
        if intent.current_cost_per_unit:
            output_columns.append("current_cost_per_unit")
            select_expressions.append(
                "CAST([cost_sum] AS decimal(38, 6)) / "
                "NULLIF(CAST([qnt_sum] AS decimal(38, 6)), 0) "
                "AS [current_cost_per_unit]"
            )
        select_columns = ", ".join(select_expressions)
        sql = (
            cte_prefix
            + "ranked_cost AS ("
            f"SELECT {cte_columns}, ROW_NUMBER() OVER (PARTITION BY {product_id} "
            f"ORDER BY {cost_date} DESC) AS rn "
            f"FROM {self._build_from_clause(intent)}{where_clause}"
            ") "
            f"SELECT {top_clause}{select_columns} FROM ranked_cost "
            "WHERE rn = 1 ORDER BY [date] DESC, [product_id]"
        )
        self._emit_sql_ready(sql, on_sql_ready)
        rows = run_sql_query(db._engine, sql)
        return format_sql_response(
            sql=sql,
            result_text=format_rows(output_columns, rows),
            explanation_text=(
                "Показана последняя строка баланса себестоимости для каждого "
                "[product_id]; qnt_sum и cost_sum не суммируются."
                + (
                    " Текущая средняя себестоимость единицы рассчитана как "
                    "cost_sum / NULLIF(qnt_sum, 0)."
                    if intent.current_cost_per_unit
                    else ""
                )
            ),
        )

    def _build_latest_price_where_clause(self, intent: QueryIntent) -> str:
        where_clause = self._build_where_clause(intent, include_date=False)
        cutoff_date = intent.filters.date_eq or intent.filters.date_to
        if cutoff_date:
            date_filter = (
                "[price_date] < DATEADD(day, 1, "
                f"{self._sql_datetime_literal(cutoff_date)})"
            )
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
            aggregate_sql = self._aggregate_sql(
                intent,
                aggregate_function,
                metric_column,
            )
            aggregate_alias = (
                "document_count"
                if intent.distinct and metric_column == "document_number"
                else "distinct_count"
                if intent.distinct and metric_column
                else "row_count"
            )
        elif aggregate_function == "max":
            aggregate_sql = f"MAX([{metric_column}])"
            aggregate_alias = "max_value"
        elif aggregate_function == "min":
            aggregate_sql = f"MIN([{metric_column}])"
            aggregate_alias = "min_value"
        elif aggregate_function == "sum":
            aggregate_sql = f"SUM([{metric_column}])"
            aggregate_alias = (
                f"total_{metric_column}"
                if intent.domain == "sales" and metric_column in SALES_TOTAL_COLUMNS
                else "sum_value"
            )
        else:
            aggregate_sql = f"AVG(CAST([{metric_column}] AS FLOAT))"
            aggregate_alias = "avg_value"

        sales_total_expressions = self._sales_total_expressions(
            intent,
            aggregate_function,
            metric_column,
        )
        sales_total_sql = "".join(
            f", {expression} AS [{alias}]"
            for expression, alias in sales_total_expressions
        )
        sales_total_columns = [alias for _, alias in sales_total_expressions]
        sales_grand_total_sql = self._sales_grand_total_sql(
            intent,
            aggregate_function,
            metric_column,
        )

        if group_by_columns:
            group_by_exprs = [
                self._column_expr(intent, column_name)
                for column_name in group_by_columns
            ]
            group_by_sql = ", ".join(group_by_exprs)
            having_clause = self._build_aggregate_having_clause(
                intent,
                aggregate_function,
                metric_column,
            )
            if aggregate_function == "count":
                select_columns = [
                    *group_by_columns,
                    aggregate_alias,
                    *sales_total_columns,
                ]
                sql = (
                    cte_prefix
                    + f"SELECT {top_clause}{group_by_sql}, {aggregate_sql} AS {aggregate_alias}"
                    f"{sales_total_sql}{sales_grand_total_sql} "
                    f"FROM {from_clause}"
                    f"{where_clause} GROUP BY {group_by_sql}{having_clause}"
                )
            else:
                select_columns = [
                    *group_by_columns,
                    aggregate_alias,
                    *sales_total_columns,
                ]
                sql = (
                    cte_prefix
                    + f"SELECT {top_clause}{group_by_sql}, {self._aggregate_sql(intent, aggregate_function, metric_column)} AS {aggregate_alias}"
                    f"{sales_total_sql}{sales_grand_total_sql} "
                    f"FROM {from_clause}"
                    f"{where_clause} GROUP BY {group_by_sql}{having_clause}"
                )
            primary_group_by = group_by_columns[0]
            if primary_group_by in {"price_date", "sale_date", "date", "purchase_date"}:
                sql += f" ORDER BY {group_by_sql} DESC"
            elif primary_group_by in {"ware_id", "product_id"}:
                if aggregate_function == "count":
                    sql += f" ORDER BY {aggregate_alias} DESC, {group_by_sql}"
                else:
                    sql += f" ORDER BY {aggregate_alias} DESC, {group_by_sql}"
            elif intent.sort_column == metric_column:
                direction = "ASC" if intent.sort_direction.lower() == "asc" else "DESC"
                sql += f" ORDER BY {aggregate_alias} {direction}, {group_by_sql}"
            else:
                sql += f" ORDER BY {group_by_sql}"
            self._emit_sql_ready(sql, on_sql_ready)
            rows = run_sql_query(db._engine, sql)
            metric_label = "количеству строк" if aggregate_function == "count" else f"полю [{metric_column or '*'}]"
            return format_sql_response(
                sql=sql,
                result_text=(
                    self._format_sales_grouped_aggregate_rows(
                        select_columns,
                        rows,
                        group_by_columns,
                        aggregate_function,
                        metric_column,
                        aggregate_alias,
                    )
                    if intent.domain == "sales"
                    else format_rows(select_columns, rows)
                ),
                explanation_text=f"Показана агрегированная статистика по {metric_label} в разрезе {', '.join(f'[{column}]' for column in group_by_columns)}.",
            )

        aggregate_sql = self._aggregate_sql(intent, aggregate_function, metric_column)
        having_clause = self._build_aggregate_having_clause(
            intent,
            aggregate_function,
            metric_column,
        )
        sql = (
            cte_prefix
            + f"SELECT {aggregate_sql} AS {aggregate_alias}"
            f"{sales_total_sql} "
            f"FROM {from_clause}{where_clause}{having_clause}"
        )
        self._emit_sql_ready(sql, on_sql_ready)
        rows = run_sql_query(db._engine, sql)
        metric_label = "количеству строк" if aggregate_function == "count" else f"полю [{metric_column or '*'}]"
        return format_sql_response(
            sql=sql,
            result_text=format_rows([aggregate_alias, *sales_total_columns], rows),
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
        top_clause = (
            f"TOP {intent.limit} "
            if intent.limit is not None and group_by_expr
            else ""
        )
        group_clause = f" GROUP BY {group_by_expr}" if group_by_expr else ""
        mode = intent.balance_mode or "end"
        if group_by_expr and intent.sort_column == "quantity":
            balance_alias = (
                "stock_quantity_start" if mode == "start" else "stock_quantity_end"
            )
            order_clause = f" ORDER BY {balance_alias} DESC, {group_by_expr}"
        else:
            order_clause = f" ORDER BY {group_by_expr}" if group_by_expr else ""

        start_date, end_date = self._stock_balance_dates(intent)
        if mode == "period":
            start_filter = self._stock_start_date_filter(intent, start_date)
            end_filter = self._stock_end_date_filter(intent, end_date)
            select_columns = ([group_by_column] if group_by_column else []) + [
                "stock_quantity_start",
                "stock_quantity_end",
            ]
            sql = (
                cte_prefix
                + f"SELECT {top_clause}{group_prefix}"
                f"SUM(CASE WHEN {start_filter} THEN {self._column_expr(intent, 'quantity')} ELSE 0 END) AS stock_quantity_start, "
                f"SUM(CASE WHEN {end_filter} THEN {self._column_expr(intent, 'quantity')} ELSE 0 END) AS stock_quantity_end "
                f"FROM {from_clause}"
                + where_clause
                + group_clause
                + self._build_stock_balance_having_clause(intent, end_filter)
                + order_clause
            )
        elif mode == "start":
            select_columns = ([group_by_column] if group_by_column else []) + ["stock_quantity_start"]
            sql = (
                cte_prefix
                + f"SELECT {top_clause}{group_prefix}SUM({self._column_expr(intent, 'quantity')}) AS stock_quantity_start "
                f"FROM {from_clause}"
                + self._append_date_filter(where_clause, self._stock_start_date_filter(intent, start_date))
                + group_clause
                + self._build_stock_balance_having_clause(
                    intent,
                    self._stock_start_date_filter(intent, start_date),
                )
                + order_clause
            )
        else:
            select_columns = ([group_by_column] if group_by_column else []) + ["stock_quantity_end"]
            if self._has_stock_balance_date_filter(intent):
                where_clause = self._append_date_filter(where_clause, self._stock_end_date_filter(intent, end_date))
            sql = (
                cte_prefix
                + f"SELECT {top_clause}{group_prefix}SUM({self._column_expr(intent, 'quantity')}) AS stock_quantity_end "
                f"FROM {from_clause}"
                + where_clause
                + group_clause
                + self._build_stock_balance_having_clause(
                    intent,
                    self._stock_end_date_filter(intent, end_date)
                    if self._has_stock_balance_date_filter(intent)
                    else None,
                )
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
        return (
            f"{self._column_expr(intent, 'date')} < "
            f"DATEADD(day, 1, {self._sql_datetime_literal(date_value)})"
        )

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
            date_expr = self._column_expr(intent, intent.filters.date_column)
            datetime_domain = intent.domain in {"product_cost", "stock"}
            if intent.filters.date_eq and datetime_domain:
                filters.append(
                    f"{date_expr} >= {self._sql_datetime_literal(intent.filters.date_eq)} "
                    f"AND {date_expr} < DATEADD(day, 1, "
                    f"{self._sql_datetime_literal(intent.filters.date_eq)})"
                )
            elif intent.filters.date_eq:
                filters.append(f"{date_expr} = '{intent.filters.date_eq}'")
            elif intent.filters.date_from and intent.filters.date_to and datetime_domain:
                filters.append(
                    f"{date_expr} >= {self._sql_datetime_literal(intent.filters.date_from)} "
                    f"AND {date_expr} < DATEADD(day, 1, "
                    f"{self._sql_datetime_literal(intent.filters.date_to)})"
                )
            elif intent.filters.date_from and intent.filters.date_to:
                filters.append(
                    f"{date_expr} BETWEEN '{intent.filters.date_from}' AND '{intent.filters.date_to}'"
                )
            else:
                if intent.filters.date_from:
                    filters.append(f"{date_expr} >= '{intent.filters.date_from}'")
                if intent.filters.date_to:
                    if datetime_domain:
                        filters.append(
                            f"{date_expr} < DATEADD(day, 1, "
                            f"{self._sql_datetime_literal(intent.filters.date_to)})"
                        )
                    else:
                        filters.append(f"{date_expr} <= '{intent.filters.date_to}'")

        if (
            intent.filters.threshold_column
            and intent.filters.threshold_operator
            and intent.filters.threshold_value
            and intent.operation not in {"aggregate", "stock_balance"}
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
            or (
                intent.metric_column in PREFERRED_COLUMNS["product_dimension"]
                and intent.metric_column != "product_id"
                and intent.metric_column not in PREFERRED_COLUMNS.get(intent.domain, ())
            )
            or (
                intent.sort_column in PREFERRED_COLUMNS["product_dimension"]
                and intent.sort_column != "product_id"
                and intent.sort_column not in PREFERRED_COLUMNS.get(intent.domain, ())
            )
            or any(
                column_name in PREFERRED_COLUMNS["product_dimension"]
                and column_name != "product_id"
                and column_name not in PREFERRED_COLUMNS.get(intent.domain, ())
                for column_name in intent.requested_columns
            )
            or (
                any(
                    column_name in PREFERRED_COLUMNS["product_dimension"]
                    and column_name != "product_id"
                    and column_name not in PREFERRED_COLUMNS.get(intent.domain, ())
                    for column_name in (intent.group_by_columns or [intent.group_by])
                )
            )
        )

    def _uses_division_join(self, intent: QueryIntent) -> bool:
        return intent.domain == "sales" and bool(
            intent.filters.division_filters
            or intent.metric_column in {"division", "city"}
            or intent.sort_column in {"division", "city"}
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
            intent.domain == "purchases"
            and column_name in PURCHASE_UNIT_COST_AMOUNT_COLUMNS
        ):
            return self._purchase_unit_cost_expr(intent, column_name)
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

    def _select_column_expr(self, intent: QueryIntent, column_name: str) -> str:
        expression = self._column_expr(intent, column_name)
        if (
            intent.domain == "purchases"
            and column_name in PURCHASE_UNIT_COST_AMOUNT_COLUMNS
        ):
            return f"{expression} AS [{column_name}]"
        return expression

    def _purchase_unit_cost_expr(
        self,
        intent: QueryIntent,
        column_name: str,
    ) -> str:
        amount_column = PURCHASE_UNIT_COST_AMOUNT_COLUMNS[column_name]
        uses_alias = bool(
            self._uses_dimension_join(intent)
            or self._uses_division_join(intent)
            or intent.filters.in_stock_only
        )
        amount_expr = (
            self._fact_column_expr(amount_column)
            if uses_alias
            else f"[{amount_column}]"
        )
        quantity_expr = (
            self._fact_column_expr("quantity")
            if uses_alias
            else "[quantity]"
        )
        return (
            f"CAST({amount_expr} AS decimal(38, 6)) / "
            f"NULLIF(CAST({quantity_expr} AS decimal(38, 6)), 0)"
        )

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
        if (
            intent.domain == "product_cost"
            and intent.weighted_cost_per_unit
            and metric_column == "cost_per_unit"
        ):
            cost_expr = self._column_expr(intent, "cost")
            quantity_expr = self._column_expr(intent, "quantity")
            return (
                f"CAST(SUM({cost_expr}) AS decimal(38, 6)) / "
                f"NULLIF(CAST(SUM({quantity_expr}) AS decimal(38, 6)), 0)"
            )
        if (
            intent.domain == "purchases"
            and metric_column in PURCHASE_UNIT_COST_AMOUNT_COLUMNS
        ):
            unit_cost_expr = self._column_expr(intent, metric_column)
            if aggregate_function == "max":
                return f"MAX({unit_cost_expr})"
            if aggregate_function == "min":
                return f"MIN({unit_cost_expr})"
            if aggregate_function == "count":
                return "COUNT(*)"
            amount_column = PURCHASE_UNIT_COST_AMOUNT_COLUMNS[metric_column]
            amount_expr = self._column_expr(intent, amount_column)
            quantity_expr = self._column_expr(intent, "quantity")
            return (
                f"CAST(SUM({amount_expr}) AS decimal(38, 6)) / "
                f"NULLIF(CAST(SUM({quantity_expr}) AS decimal(38, 6)), 0)"
            )
        metric_expr = self._column_expr(intent, metric_column) if metric_column else "*"
        if aggregate_function == "max":
            return f"MAX({metric_expr})"
        if aggregate_function == "min":
            return f"MIN({metric_expr})"
        if aggregate_function == "sum":
            return f"SUM({metric_expr})"
        if aggregate_function == "count":
            if intent.distinct and metric_column:
                return f"COUNT(DISTINCT {metric_expr})"
            return "COUNT(*)"
        return f"AVG(CAST({metric_expr} AS FLOAT))"

    def _build_aggregate_having_clause(
        self,
        intent: QueryIntent,
        aggregate_function: str | None,
        metric_column: str | None,
    ) -> str:
        filters = intent.filters
        if not (
            filters.threshold_column
            and filters.threshold_operator
            and filters.threshold_value
        ):
            return ""
        threshold_metric = filters.threshold_column or metric_column
        expression = self._aggregate_sql(
            intent,
            aggregate_function,
            threshold_metric,
        )
        return (
            f" HAVING {expression} {filters.threshold_operator} "
            f"{filters.threshold_value}"
        )

    def _build_stock_balance_having_clause(
        self,
        intent: QueryIntent,
        date_filter: str | None,
    ) -> str:
        filters = intent.filters
        if not (
            filters.threshold_column == "quantity"
            and filters.threshold_operator
            and filters.threshold_value
        ):
            return ""
        quantity_expr = self._column_expr(intent, "quantity")
        if date_filter:
            balance_expression = (
                f"SUM(CASE WHEN {date_filter} THEN {quantity_expr} ELSE 0 END)"
            )
        else:
            balance_expression = f"SUM({quantity_expr})"
        return (
            f" HAVING {balance_expression} {filters.threshold_operator} "
            f"{filters.threshold_value}"
        )

    def _sales_total_expressions(
        self,
        intent: QueryIntent,
        aggregate_function: str | None,
        metric_column: str | None,
    ) -> list[tuple[str, str]]:
        if intent.domain != "sales":
            return []

        expressions: list[tuple[str, str]] = []
        for column_name in SALES_TOTAL_COLUMNS:
            if aggregate_function == "sum" and metric_column == column_name:
                continue
            expressions.append(
                (
                    f"SUM({self._column_expr(intent, column_name)})",
                    f"total_{column_name}",
                )
            )
        return expressions

    def _sales_grand_total_sql(
        self,
        intent: QueryIntent,
        aggregate_function: str | None,
        metric_column: str | None,
    ) -> str:
        if intent.domain != "sales":
            return ""
        sql = "".join(
            ", SUM(SUM("
            f"{self._column_expr(intent, column_name)}"
            ")) OVER () AS "
            f"[__grand_total_{column_name}]"
            for column_name in SALES_TOTAL_COLUMNS
        )
        if aggregate_function == "count":
            if intent.distinct and metric_column:
                sql += (
                    ", (SELECT COUNT(DISTINCT "
                    f"{self._column_expr(intent, metric_column)}) FROM "
                    f"{self._build_from_clause(intent)}"
                    f"{self._build_where_clause(intent)}) "
                    "AS [__grand_total_distinct_count]"
                )
            else:
                sql += ", SUM(COUNT(*)) OVER () AS [__grand_total_row_count]"
        elif aggregate_function == "sum" and metric_column not in SALES_TOTAL_COLUMNS:
            sql += (
                ", SUM(SUM("
                f"{self._column_expr(intent, metric_column)}"
                ")) OVER () AS [__grand_total_primary]"
            )
        return sql

    def _format_sales_grouped_aggregate_rows(
        self,
        columns: list[str],
        rows: list[tuple],
        group_by_columns: list[str],
        aggregate_function: str | None,
        metric_column: str | None,
        aggregate_alias: str,
    ) -> str:
        if not rows:
            return format_rows(columns, rows)

        visible_width = len(columns)
        visible_rows = [tuple(row[:visible_width]) for row in rows]
        total_row: list[object] = [""] * visible_width
        total_row[columns.index(group_by_columns[0])] = "ИТОГО"
        hidden_totals = rows[0][
            visible_width : visible_width + len(SALES_TOTAL_COLUMNS)
        ]
        full_totals = (
            dict(zip(SALES_TOTAL_COLUMNS, hidden_totals))
            if len(hidden_totals) == len(SALES_TOTAL_COLUMNS)
            else {}
        )
        primary_total_index = visible_width + len(SALES_TOTAL_COLUMNS)
        primary_total = (
            rows[0][primary_total_index]
            if (
                aggregate_function == "count"
                or (
                    aggregate_function == "sum"
                    and metric_column not in SALES_TOTAL_COLUMNS
                )
            )
            and len(rows[0]) > primary_total_index
            else None
        )

        for column_name in SALES_TOTAL_COLUMNS:
            output_column = (
                aggregate_alias
                if aggregate_function == "sum" and metric_column == column_name
                else f"total_{column_name}"
            )
            output_index = columns.index(output_column)
            if column_name in full_totals:
                total_row[output_index] = full_totals[column_name]
            else:
                values = [
                    row[output_index]
                    for row in visible_rows
                    if row[output_index] is not None
                ]
                total_row[output_index] = sum(values) if values else None

        if primary_total is not None and aggregate_alias in columns:
            total_row[columns.index(aggregate_alias)] = primary_total

        visible_rows.append(tuple(total_row))
        return format_rows(columns, visible_rows)
