from __future__ import annotations

import json
import re

from openai import APIError

from sql_agent.config import CURRENCY_ALIAS_MAP, DEFAULT_PREVIEW_ROWS
from sql_agent.intents import QueryFilters, QueryIntent
from sql_agent.langchain_factory import build_llm
from sql_agent.memory import SqlAgentMemory
from sql_agent.query_utils import (
    extract_table_name,
    find_table_reference,
    is_aggregate_question,
    is_price_question,
    is_schema_question,
    parse_date_filters,
    parse_numeric_threshold,
    parse_requested_limit,
    parse_ware_id_filter,
    parse_ware_id_filters,
)


RETAIL_PRICE_COLUMNS = [
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

RETAIL_PRICE_DATABASE = "DWH"
RETAIL_PRICE_SCHEMA = "LLM"
RETAIL_PRICE_TABLE = "price"

SALES_COLUMNS = [
    "sale_date",
    "document_number",
    "product_id",
    "division_id",
    "quantity",
    "amount",
    "amount_usd",
    "amount_eur",
]

COST_COLUMNS = [
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
]

COST_PRODUCT_HISTORY_COLUMNS = [
    "date",
    "product_id",
    "op_type",
    "quantity",
    "cost",
    "cost_per_unit",
    "qnt_sum",
    "cost_sum",
]

COST_DATABASE = "DWH"
COST_SCHEMA = "LLM"
COST_TABLE = "cost"

STOCK_COLUMNS = [
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
]

STOCK_DATABASE = "DWH"
STOCK_SCHEMA = "LLM"
STOCK_TABLE = "stock"

PURCHASE_COLUMNS = [
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
]

PURCHASE_DATABASE = "DWH"
PURCHASE_SCHEMA = "LLM"
PURCHASE_TABLE = "v_Purchases"

PRODUCT_DIMENSION_COLUMNS = [
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
]

PRODUCT_DIMENSION_DATABASE = "DWH"
PRODUCT_DIMENSION_SCHEMA = "LLM"
PRODUCT_DIMENSION_TABLE = "dimension_product"

DIVISION_COLUMNS = ["id", "division", "city"]
DIVISION_DATABASE = "DWH"
DIVISION_SCHEMA = "LLM"
DIVISION_TABLE = "division"
DIVISION_ATTRIBUTE_ALIASES = {
    "division": (
        "division",
        "подразделение",
        "подразделению",
        "магазин",
        "бутик",
        "точка продаж",
    ),
    "city": ("city", "город"),
}

PRODUCT_DIMENSION_ATTRIBUTE_ALIASES = {
    "product_id": ("product_id", "product id", "sprut", "код спрута"),
    "article": ("article", "артикул"),
    "style": ("style",),
    "fabric": ("fabric",),
    "color_code": ("color_code",),
    "name": ("name", "наименование"),
    "breadcrumbs": ("breadcrumbs",),
    "bu": (
        "bu",
        "business unit",
        "бизнес юнит",
        "бизнес-юнит",
        "направление бизнеса",
        "направление",
        "направления",
    ),
    "category": ("category", "категория"),
    "group": ("group", "группа"),
    "subgroup": ("subgroup", "подгруппа"),
    "product": ("product", "продукт"),
    "department": ("department", "департамент"),
    "subdepartment": ("subdepartment", "субдепартамент"),
    "department_vs": ("department_vs",),
    "subdepartment_vs": ("subdepartment_vs",),
    "brand": ("brand", "бренд", "марка"),
    "season_year": ("season_year",),
    "season_short": ("season_short", "сезон кратко"),
    "season": ("season", "сезон"),
    "gender": ("gender", "пол"),
    "sizechart_type": ("sizechart_type",),
    "sizechart": ("sizechart",),
    "common_size": ("common_size", "размер"),
    "italian_size": ("italian_size",),
    "color_eng": ("color_eng",),
    "color_rus": ("color_rus", "цвет"),
    "country": ("country", "страна"),
    "buyer": ("buyer", "байер"),
    "buyer_assistant": ("buyer_assistant", "ассистент байера"),
    "composition": ("composition", "состав"),
    "fur": ("fur", "мех"),
    "heel": ("heel", "каблук"),
    "brand_category": ("brand_category",),
    "individual_number": ("individual_number",),
    "consigment": ("consigment", "консигнация"),
    "carryover": ("carryover", "кэрриовер"),
    "stock_year": ("stock_year",),
    "world_retail_price": ("world_retail_price", "мировая цена"),
    "collection_jw": ("collection_jw", "collection", "коллекция", "коллекции", "коллекцию"),
    # Store/division wording (for example, "бутик Saks Fifth Avenue") belongs
    # to DWH.LLM.division. Keep only the explicit column name here so a sales
    # request does not get a duplicate dimension_product.store_jw filter.
    "store_jw": ("store_jw",),
    "volume": ("volume", "объем"),
    "tone": ("tone", "тон"),
    "line": ("line", "линия"),
    "department_en": ("department_en",),
    "url": ("url", "ссылка"),
    "image_url": ("image_url", "картинка", "изображение"),
    "barcode": ("barcode", "штрихкод", "bar code"),
    "buyer_assistant_vs": ("buyer_assistant_vs",),
    "buyer_vs": ("buyer_vs",),
    "full_composition": ("full_composition", "полный состав"),
    "size_type": ("size_type",),
    "AML": ("aml",),
}

PRODUCT_DIMENSION_BU_VALUE_ALIASES = {
    "J&W": (
        r"\bювелир[а-яё-]*\b",
        r"\bювелирно-часов[а-яё-]*\b",
        r"\bj\s*&\s*w\b",
        r"\bjw\b",
    ),
}

STOCK_METRIC_ALIASES = {
    "quantity": (
        "quantity",
        "количеств",
        "остаток",
        "остатк",
        "шт",
        "qty",
        "stock",
        "balance",
    ),
}

COST_METRIC_ALIASES = {
    "quantity": ("quantity", "количество в операции"),
    "cost": ("cost", "сумма операции", "себестоимость операции"),
    "cost_per_unit": ("cost_per_unit", "себестоимость единицы", "себестоимость за единицу"),
    "qnt_sum": ("qnt_sum", "остаток товара", "остаток в штуках"),
    "cost_sum": ("cost_sum", "себестоимость остатка", "стоимость остатка"),
    "zeroed": ("zeroed", "обнулено", "обнуление", "нулевая себестоимость"),
}

PURCHASE_METRIC_ALIASES = {
    "quantity": ("quantity", "количеств"),
    "amount_kzt": ("amount_kzt", "kzt", "тенге", "закупочная стоимость", "стоимость закуп"),
    "amount_usd": ("amount_usd", "usd", "доллар"),
    "amount_eur": ("amount_eur", "eur", "евро"),
    "amount_chf": ("amount_chf", "chf", "франк"),
    "NDS_kzt": ("nds_kzt", "ндс kzt", "ндс тенге"),
    "NDS_usd": ("nds_usd", "ндс usd"),
    "NDS_eur": ("nds_eur", "ндс eur"),
    "NDS_chf": ("nds_chf", "ндс chf"),
}

SALES_METRIC_ALIASES = {
    "quantity": (
        "quantity",
        "qty",
        "количество",
        "шт",
        "штук",
        "продано",
        "проданный",
        "проданная",
        "продавался",
        "продавалась",
    ),
    "amount": ("amount", "sales amount", "выручка", "сумма продаж", "продажи", "оборот"),
    "amount_usd": ("amount_usd", "sales in usd", "выручка в usd", "продажи в usd", "сумма в usd"),
    "amount_eur": ("amount_eur", "sales in eur", "выручка в eur", "продажи в eur", "сумма в eur"),
    "price": ("price", "цена продажи", "sale price"),
    "price_usd": ("price_usd", "price in usd", "цена в usd"),
    "price_eur": ("price_eur", "price in eur", "цена в eur"),
    "discount": ("discount", "скидка", "discount amount"),
    "cash": ("cash", "наличные", "cash payment"),
    "card": ("card", "карта", "card payment"),
    "loan": ("loan", "кредит", "loan payment"),
    "bonus": ("bonus", "бонус", "bonus payment"),
}

SALES_GROUP_BY_ALIASES = {
    "sale_date": ("по дате", "по датам", "by date", "daily"),
    "product_id": (
        "по товару",
        "по товарам",
        "by product",
    ),
    "channel": ("по каналу", "by channel", "канал"),
    "payment_method": ("по способу оплаты", "by payment method"),
    "customer_id": ("по клиенту", "by customer"),
}


class IntentParser:
    def get_clarification(self, question: str) -> str | None:
        lowered = question.lower()
        if self._detect_domain(question) != "sales":
            return None
        if self._extract_group_by(lowered, "sales") != "product_id":
            return None
        if not self._wants_single_best(lowered):
            return None
        if self._is_quantity_metric_request(lowered) or self._is_amount_metric_request(lowered):
            return None
        return (
            "Уточните, пожалуйста: лучший товар считать по количеству проданного товара "
            "или по сумме продаж?"
        )

    def parse(self, question: str, memory: SqlAgentMemory, engine=None) -> QueryIntent:
        intent = self._parse_rules(question, engine)
        if intent.operation != "unknown":
            return intent

        llm_intent = self._parse_with_llm(question, memory)
        if llm_intent is not None:
            return llm_intent

        fallback_intent = self._parse_rules(question, engine, permissive=True)
        if fallback_intent.operation != "unknown":
            return fallback_intent

        return QueryIntent(operation="unknown")

    def _parse_rules(self, question: str, engine=None, permissive: bool = False) -> QueryIntent:
        lowered = question.lower()
        if self._wants_gross_margin(lowered):
            return self._parse_gross_margin(question)

        domain = self._detect_domain(question)
        schema_name, table_name = self._resolve_table(question, engine, domain)
        date_column = self._date_column(domain)
        identifier_column = self._identifier_column(domain)
        filters = self._build_filters(question, domain, date_column, identifier_column)
        limit = parse_requested_limit(question)
        if self._wants_all_data(lowered):
            limit = None
        elif (
            domain == "product_cost"
            and filters.identifier_value
            and self._wants_product_cost_history(lowered)
            and not self._has_explicit_limit(lowered)
        ):
            limit = None

        if is_schema_question(question) and not self._looks_like_row_request(
            lowered,
            filters,
            limit,
        ):
            if table_name is None and not permissive:
                return QueryIntent(operation="unknown")
            return QueryIntent(
                operation="schema",
                domain=domain,
                database_name=self._default_database_name(domain, table_name),
                schema_name=schema_name or "LLM",
                table_name=table_name or self._table_name(domain),
            )

        aggregate_function = self._extract_aggregate_function(lowered)
        metric_column = self._extract_metric_column(question, domain)
        distinct = self._wants_distinct_values(lowered)
        group_by = self._extract_group_by(lowered, domain)
        group_by_columns = self._extract_group_by_columns(lowered, domain, group_by)
        if distinct:
            group_by = None
            group_by_columns = []
        if group_by and limit is None:
            limit = DEFAULT_PREVIEW_ROWS
        for group_by_column in group_by_columns:
            if group_by_column in PRODUCT_DIMENSION_ATTRIBUTE_ALIASES:
                filters.dimension_filters.pop(group_by_column, None)
                filters.dimension_prefix_filters.pop(group_by_column, None)
            if group_by_column in DIVISION_ATTRIBUTE_ALIASES:
                filters.division_filters.pop(group_by_column, None)
        if (
            domain == "sales"
            and filters.identifier_value
            and group_by == "product_id"
            and (
                self._looks_like_sales_row_request(lowered)
                or not any(marker in lowered for marker in ("по товарам", "by product"))
            )
        ):
            group_by = None
        if (
            domain == "sales"
            and self._looks_like_sales_row_request(lowered)
            and filters.threshold_column
            and aggregate_function == "sum"
        ):
            aggregate_function = None
        if group_by and limit == DEFAULT_PREVIEW_ROWS and self._wants_single_best(lowered):
            limit = 1
        if domain == "sales" and group_by and not aggregate_function and self._wants_single_best(lowered):
            if self._is_quantity_metric_request(lowered):
                aggregate_function = "sum"
                metric_column = "quantity"
            elif self._is_amount_metric_request(lowered):
                aggregate_function = "sum"
                metric_column = metric_column or "amount"
        if domain == "sales" and group_by and not aggregate_function and self._wants_sales_ranking(lowered):
            aggregate_function = "sum"
            metric_column = "quantity" if self._is_quantity_metric_request(lowered) else "amount"
        if domain == "sales" and group_by and not aggregate_function:
            aggregate_function = "sum"
            metric_column = metric_column or "amount"
        if domain == "sales" and group_by == "product_id" and self._wants_all_sold_products(lowered):
            aggregate_function = "sum"
            metric_column = "quantity"
            limit = None
            if not filters.threshold_column:
                filters.threshold_column = "quantity"
                filters.threshold_operator = ">"
                filters.threshold_value = "0"
        if (
            domain == "sales"
            and aggregate_function == "count"
            and self._is_quantity_metric_request(lowered)
        ):
            aggregate_function = "sum"
            metric_column = "quantity"
        if domain == "stock" and self._wants_stock_balance(lowered):
            return QueryIntent(
                operation="stock_balance",
                domain=domain,
                database_name=self._default_database_name(domain, table_name),
                schema_name=schema_name or "LLM",
                table_name=table_name or self._table_name(domain),
                metric_column="quantity",
                aggregate_function="sum",
                group_by=group_by,
                group_by_columns=group_by_columns,
                balance_mode=self._extract_stock_balance_mode(lowered),
                limit=limit,
                filters=filters,
                sort_column=group_by,
                sort_direction="desc",
            )

        if (
            domain == "product_cost"
            and aggregate_function == "sum"
            and metric_column in {"qnt_sum", "cost_sum"}
        ):
            aggregate_function = None

        if aggregate_function and (metric_column or aggregate_function == "count"):
            return QueryIntent(
                operation="aggregate",
                domain=domain,
                database_name=self._default_database_name(domain, table_name),
                schema_name=schema_name or "LLM",
                table_name=table_name or self._table_name(domain),
                metric_column=metric_column,
                aggregate_function=aggregate_function,
                group_by=group_by,
                group_by_columns=group_by_columns,
                limit=limit,
                filters=filters,
                sort_column=group_by,
                sort_direction="desc",
            )

        if table_name is not None or domain in {"sales", "retail_price", "product_cost", "stock", "purchases", "product_dimension", "division_dimension"} or filters.date_eq or filters.date_from:
            requested_columns = self._extract_requested_columns(
                question,
                domain,
                include_context_columns=not distinct,
            )
            if (
                not distinct
                and domain in {"product_cost", "stock"}
                and not (
                    domain == "product_cost"
                    and self._wants_product_cost_history(lowered)
                )
            ):
                requested_columns = list(self._domain_columns(domain))
            if not requested_columns:
                requested_columns = list(self._domain_columns(domain))
            if distinct:
                if (
                    len(requested_columns) > 1
                    and "bu" in filters.dimension_filters
                    and self._extract_known_bu_value(question)
                ):
                    requested_columns = [
                        column_name
                        for column_name in requested_columns
                        if column_name != "bu"
                    ]
                for column_name in requested_columns:
                    filters.equality_filters.pop(column_name, None)
                    filters.dimension_prefix_filters.pop(column_name, None)
                    dimension_value = filters.dimension_filters.get(column_name)
                    dimension_values = (
                        dimension_value
                        if isinstance(dimension_value, list)
                        else [dimension_value]
                        if dimension_value
                        else []
                    )
                    if not (
                        dimension_values
                        and all(value.isascii() for value in dimension_values)
                        and not re.match(
                            r"^(?:and|by|from|in|of|where|order|sort)\b",
                            dimension_values[0],
                            flags=re.IGNORECASE,
                        )
                    ):
                        filters.dimension_filters.pop(column_name, None)
                    filters.division_filters.pop(column_name, None)
            keep_unlimited_cost_history = (
                domain == "product_cost"
                and filters.identifier_value
                and self._wants_product_cost_history(lowered)
            )
            if limit is None and not (
                self._wants_all_rows(lowered) or keep_unlimited_cost_history
            ):
                limit = DEFAULT_PREVIEW_ROWS
            sort_column, sort_direction = self._extract_sort(lowered, metric_column, domain)
            if distinct and requested_columns:
                sort_column = requested_columns[0]
                sort_direction = "asc"
            return QueryIntent(
                operation="select",
                domain=domain,
                database_name=self._default_database_name(domain, table_name),
                schema_name=schema_name or "LLM",
                table_name=table_name or self._table_name(domain),
                requested_columns=requested_columns,
                metric_column=metric_column,
                limit=limit,
                sort_column=sort_column,
                sort_direction=sort_direction,
                distinct=distinct,
                latest_per_identifier=(
                    domain == "retail_price"
                    and bool(
                        filters.identifier_values
                        or filters.dimension_filters
                        or filters.dimension_prefix_filters
                    )
                    and (self._wants_latest_price(lowered) or bool(filters.date_eq))
                ),
                filters=filters,
            )

        return QueryIntent(operation="unknown")

    def _parse_gross_margin(self, question: str) -> QueryIntent:
        lowered = question.lower()
        filters = self._build_filters(
            question,
            "retail_price",
            "price_date",
            "ware_id",
        )
        limit = parse_requested_limit(question) or DEFAULT_PREVIEW_ROWS
        group_by = self._extract_gross_margin_scope(lowered)
        return QueryIntent(
            operation="gross_margin",
            domain="retail_price",
            database_name=RETAIL_PRICE_DATABASE,
            schema_name=RETAIL_PRICE_SCHEMA,
            table_name=RETAIL_PRICE_TABLE,
            group_by=group_by,
            discount_percent=self._extract_discount_percent(question),
            limit=min(limit, DEFAULT_PREVIEW_ROWS),
            filters=filters,
        )

    def _parse_with_llm(self, question: str, memory: SqlAgentMemory) -> QueryIntent | None:
        prompt = self._build_intent_prompt(question, memory)
        try:
            response = build_llm().invoke(prompt)
        except APIError:
            return None

        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = "".join(str(item) for item in content)
        if not isinstance(content, str):
            return None

        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            return None

        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return self._intent_from_payload(payload)

    def _build_intent_prompt(self, question: str, memory: SqlAgentMemory) -> str:
        schema_snapshot = memory.schema_snapshot[:1400] if memory.schema_snapshot else "DWH.LLM.price, LLM.sales, DWH.LLM.cost"
        return (
            "You are an intent parser for a Microsoft SQL Server analytics assistant.\n"
            "Return JSON only. Infer intent, not SQL.\n"
            "Supported domains: retail_price, sales, product_cost, stock, purchases, product_dimension, division_dimension.\n"
            "Supported operations: select, aggregate, stock_balance, gross_margin, schema, unknown.\n"
            "Retail price table: DWH.LLM.price with date column price_date and product/warehouse column ware_id.\n"
            "Sales table: LLM.sales with date column sale_date and integer product column product_id. Do not use customer_name; it is not present.\n"
            "Product cost table: DWH.LLM.cost with date column date, product column product_id, KZT operation metrics cost and cost_per_unit, and running balances qnt_sum and cost_sum. Never sum running balances.\n"
            "Stock table: DWH.LLM.stock with date column date, product_id, warehouse_id, recorder/document fields, and signed quantity movements. Use it for stock balances, warehouse movements, Перемещение товаров, document_id in 1C, and explicit stock table requests. Stock at period start is SUM(quantity) before the start date; stock at period end is SUM(quantity) through the end date.\n"
            "Purchases table: DWH.LLM.v_Purchases with date column purchase_date, product_id, recorder_number, division_id, quantity, amount_kzt/usd/eur/chf and NDS_kzt/usd/eur/chf. Use it for purchase cost, purchasing value, procurement, supplier returns, import declarations, additional purchase expenses, and purchase receipts.\n"
            "Product dimension table: DWH.LLM.dimension_product with product_id as the product dictionary key used in other product tables. Use it for product attributes such as article, brand, category, bu, season, gender, size, color, barcode, buyer, url, and image_url. It has no date column.\n"
            "Division dimension table: DWH.LLM.division with id, division, and city. For sales, join LLM.sales.division_id to DWH.LLM.division.id and use division/city for filters or grouping.\n"
            "If the user asks for all rows or says no limit, return null for limit.\n"
            "Schema snapshot:\n"
            f"{schema_snapshot}\n\n"
            "JSON shape:\n"
            '{"operation":"aggregate","domain":"sales","schema_name":"LLM","table_name":"sales","requested_columns":[],"metric_column":"amount_usd","aggregate_function":"sum","group_by":"sale_date","limit":10,"sort_column":"sale_date","sort_direction":"desc","filters":{"date_column":"sale_date","date_eq":"2026-02-01","date_from":null,"date_to":null,"identifier_column":"product_id","identifier_value":null,"threshold_column":null,"threshold_operator":null,"threshold_value":null}}\n\n'
            "User request:\n"
            f"{question}"
        )

    def _intent_from_payload(self, payload: dict) -> QueryIntent | None:
        operation = str(payload.get("operation", "unknown")).lower()
        if operation not in {"select", "aggregate", "stock_balance", "gross_margin", "schema", "unknown"}:
            return None

        filters_payload = payload.get("filters") or {}
        filters = QueryFilters(
            date_column=filters_payload.get("date_column"),
            date_eq=filters_payload.get("date_eq"),
            date_from=filters_payload.get("date_from"),
            date_to=filters_payload.get("date_to"),
            identifier_column=filters_payload.get("identifier_column"),
            identifier_value=filters_payload.get("identifier_value"),
            identifier_values=filters_payload.get("identifier_values") or [],
            threshold_column=filters_payload.get("threshold_column"),
            threshold_operator=filters_payload.get("threshold_operator"),
            threshold_value=str(filters_payload.get("threshold_value")) if filters_payload.get("threshold_value") is not None else None,
            equality_filters=filters_payload.get("equality_filters") or {},
            dimension_filters=filters_payload.get("dimension_filters") or {},
            dimension_prefix_filters=filters_payload.get("dimension_prefix_filters") or {},
            division_filters=filters_payload.get("division_filters") or {},
            in_stock_only=bool(filters_payload.get("in_stock_only") or False),
        )

        limit = payload.get("limit")
        if limit is not None:
            try:
                limit = max(1, min(int(limit), 1000))
            except (TypeError, ValueError):
                limit = DEFAULT_PREVIEW_ROWS

        requested_columns = payload.get("requested_columns") or []
        if not isinstance(requested_columns, list):
            requested_columns = []

        domain = str(payload.get("domain") or "retail_price")
        if domain not in {"retail_price", "sales", "product_cost", "stock", "purchases", "product_dimension", "division_dimension"}:
            domain = "retail_price"
        if (
            domain == "sales"
            and filters.identifier_column == "product_id"
            and filters.identifier_value
            and not str(filters.identifier_value).isdigit()
        ):
            filters.identifier_value = None
            filters.identifier_values = []

        return QueryIntent(
            operation=operation,
            domain=domain,
            database_name=str(payload.get("database_name") or self._database_name(domain)) if self._database_name(domain) else payload.get("database_name"),
            schema_name=str(payload.get("schema_name") or "LLM"),
            table_name=str(payload.get("table_name") or self._table_name(domain)),
            requested_columns=[str(item) for item in requested_columns],
            metric_column=payload.get("metric_column"),
            aggregate_function=payload.get("aggregate_function"),
            group_by=payload.get("group_by"),
            group_by_columns=[
                str(item)
                for item in (payload.get("group_by_columns") or [])
            ],
            balance_mode=payload.get("balance_mode"),
            limit=limit,
            sort_column=payload.get("sort_column"),
            sort_direction=str(payload.get("sort_direction") or "desc").lower(),
            latest_per_identifier=bool(payload.get("latest_per_identifier") or False),
            filters=filters,
        )

    def _detect_domain(self, question: str) -> str:
        lowered = self._without_availability_phrases(question).lower()
        explicit_division_markers = (
            "dwh.llm.division",
            "[dwh].[llm].[division]",
            "llm.division",
            "таблица division",
            "справочник подразделений",
            "справочник магазинов",
        )
        if any(marker in lowered for marker in explicit_division_markers):
            return "division_dimension"
        cost_markers = (
            "dwh.llm.cost",
            "[dwh].[llm].[cost]",
            "себестоим",
            "себес",
            "себестом",
            "cost_per_unit",
            "cost_sum",
            "qnt_sum",
            "zeroed",
            "product cost",
            "cost price",
        )
        if any(marker in lowered for marker in cost_markers):
            return "product_cost"
        purchase_markers = (
            "dwh.llm.v_purchases",
            "[dwh].[llm].[v_purchases]",
            "llm.v_purchases",
            "v_purchases",
            "закуп",
            "закупоч",
            "поставщик",
            "гтд",
            "импорт",
            "доп. расход",
            "доп расход",
            "поступление товаров и услуг",
            "purchase",
            "purchases",
            "procurement",
            "supplier return",
            "amount_kzt",
            "nds_kzt",
            "division_id",
            "recorder_number",
        )
        if any(marker in lowered for marker in purchase_markers):
            return "purchases"
        stock_markers = (
            "dwh.llm.stock",
            "[dwh].[llm].[stock]",
            "llm.stock",
            "остатк",
            "остаток",
            "перемещен",
            "склад",
            "склада",
            "складам",
            "warehouse",
            "stock",
            "document_id",
            "recorder_guid",
            "recorder_type",
            "movement_index",
            "ввод_остатков",
            "оприходование",
            "списание",
            "поступление",
        )
        if any(marker in lowered for marker in stock_markers):
            return "stock"
        explicit_product_dimension_markers = (
            "dwh.llm.dimension_product",
            "[dwh].[llm].[dimension_product]",
            "llm.dimension_product",
            "dimension_product",
            "DWH.LLM.division",
            "LLM.division",
            "division",
            "product dimension",
            "product dictionary",
            "product attributes",
            "product master",
            "справочник товаров",
            "справочник товара",
            "карточка товара",
            "атрибуты товара",
            "номенклатура",
        )
        product_dimension_markers = explicit_product_dimension_markers + (
            "артикул",
            "бренд товара",
            "штрихкод",
            "barcode",
            "image_url",
            "breadcrumbs",
            "season_short",
        )
        if any(marker in lowered for marker in explicit_product_dimension_markers):
            return "product_dimension"
        sales_markers = (
            "sales",
            "sale",
            "продаж",
            "продав",
            "продан",
            "выручк",
            "оборот",
            "quantity",
            "amount",
            "document_number",
            "payment",
            "customer",
            "channel",
            "оплат",
            "налич",
            "карт",
            "кредит",
            "бонус",
        )
        if any(marker in lowered for marker in sales_markers):
            return "sales"
        if is_price_question(question):
            return "retail_price"
        reference_request_markers = (
            "опиши",
            "описание",
            "данные о",
            "название",
            "справочные данные",
        )
        value_table_markers = (
            "цен",
            "продаж",
            "продан",
            "продавал",
            "выруч",
            "оборот",
            "себестоим",
            "закуп",
            "покуп",
            "остат",
            "движен",
            "перемещен",
            "склад",
        )
        if (
            any(marker in lowered for marker in reference_request_markers)
            and not any(marker in lowered for marker in value_table_markers)
        ):
            return "product_dimension"
        if any(marker in lowered for marker in product_dimension_markers):
            return "product_dimension"
        if any(marker in lowered for marker in ("магазин", "бутик", "точка продаж", "подразделен", "city")):
            return "division_dimension"
        # Product master data is the safe default when the question does not
        # explicitly name a value-table operation (sales, price, stock, etc.).
        return "product_dimension"

    def _resolve_table(self, question: str, engine, domain: str) -> tuple[str | None, str | None]:
        if engine is not None:
            table_ref = find_table_reference(engine, question)
            if table_ref is not None:
                return table_ref

        known_tables = [
            "DWH.LLM.price",
            "LLM.price",
            "price",
            "LLM.sales",
            "sales",
            "BI.sales_table",
            "sales_table",
            "DWH.LLM.cost",
            "LLM.cost",
            "cost",
            "DWH.LLM.stock",
            "LLM.stock",
            "stock",
            "DWH.LLM.v_Purchases",
            "LLM.v_Purchases",
            "v_Purchases",
            "v_purchases",
            "purchases",
            "DWH.LLM.dimension_product",
            "LLM.dimension_product",
            "dimension_product",
        ]
        table_name = extract_table_name(question, known_tables)
        if table_name in {
            "DWH.LLM.price",
            "LLM.price",
            "price",
        }:
            return (RETAIL_PRICE_SCHEMA, RETAIL_PRICE_TABLE)
        if table_name in {"LLM.sales", "sales", "BI.sales_table", "sales_table"}:
            return ("LLM", "sales")
        if table_name in {"DWH.LLM.cost", "LLM.cost", "cost"}:
            return (COST_SCHEMA, COST_TABLE)
        if table_name in {"DWH.LLM.stock", "LLM.stock", "stock"}:
            return (STOCK_SCHEMA, STOCK_TABLE)
        if table_name in {"DWH.LLM.v_Purchases", "LLM.v_Purchases", "v_Purchases", "v_purchases", "purchases"}:
            return (PURCHASE_SCHEMA, PURCHASE_TABLE)
        if table_name in {"DWH.LLM.dimension_product", "LLM.dimension_product", "dimension_product"}:
            return (PRODUCT_DIMENSION_SCHEMA, PRODUCT_DIMENSION_TABLE)
        if table_name in {"DWH.LLM.division", "LLM.division", "division"}:
            return (DIVISION_SCHEMA, DIVISION_TABLE)

        if domain == "sales":
            return ("LLM", "sales")
        if domain == "product_cost":
            return (COST_SCHEMA, COST_TABLE)
        if domain == "stock":
            return (STOCK_SCHEMA, STOCK_TABLE)
        if domain == "purchases":
            return (PURCHASE_SCHEMA, PURCHASE_TABLE)
        if domain == "product_dimension":
            return (PRODUCT_DIMENSION_SCHEMA, PRODUCT_DIMENSION_TABLE)
        if domain == "division_dimension":
            return (DIVISION_SCHEMA, DIVISION_TABLE)
        return (RETAIL_PRICE_SCHEMA, RETAIL_PRICE_TABLE)

    def _default_database_name(self, domain: str, table_name: str | None) -> str | None:
        if domain == "retail_price" and (table_name is None or table_name == RETAIL_PRICE_TABLE):
            return RETAIL_PRICE_DATABASE
        if domain == "product_cost" and (table_name is None or table_name == COST_TABLE):
            return COST_DATABASE
        if domain == "stock" and (table_name is None or table_name == STOCK_TABLE):
            return STOCK_DATABASE
        if domain == "purchases" and (table_name is None or table_name == PURCHASE_TABLE):
            return PURCHASE_DATABASE
        if domain == "product_dimension" and (table_name is None or table_name == PRODUCT_DIMENSION_TABLE):
            return PRODUCT_DIMENSION_DATABASE
        if domain == "division_dimension" and (table_name is None or table_name == DIVISION_TABLE):
            return DIVISION_DATABASE
        return None

    def _build_filters(
        self,
        question: str,
        domain: str,
        date_column: str,
        identifier_column: str,
    ) -> QueryFilters:
        filters = QueryFilters(date_column=date_column, identifier_column=identifier_column)
        filters.in_stock_only = self._wants_in_stock_only(question)
        filter_question = self._without_availability_phrases(question)
        for key, value in parse_date_filters(question):
            if key == "eq":
                filters.date_eq = value
            elif key == "between":
                filters.date_from = value
            elif key == "between_end":
                filters.date_to = value

        identifier_values = self._extract_identifier_values(filter_question, domain)
        if identifier_values:
            filters.identifier_values = identifier_values
            filters.identifier_value = identifier_values[0]

        threshold = parse_numeric_threshold(question)
        if threshold:
            operator, value = threshold
            filters.threshold_column = self._extract_metric_column(question, domain)
            filters.threshold_operator = operator
            filters.threshold_value = value

        if domain == "stock":
            lowered = question.lower()
            if "перемещен" in lowered:
                filters.equality_filters["recorder_type"] = "Перемещение товаров"

        filters.dimension_filters = self._extract_dimension_filters(filter_question, domain)
        filters.dimension_prefix_filters = self._extract_dimension_prefix_filters(
            filter_question,
            domain,
        )
        for column_name in filters.dimension_prefix_filters:
            filters.dimension_filters.pop(column_name, None)
        filters.division_filters = self._extract_division_filters(question, domain)
        return filters

    def _wants_in_stock_only(self, question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:только\s+)?(?:в\s+наличии|на\s+остатках)\b",
                question,
                flags=re.IGNORECASE,
            )
        )

    def _without_availability_phrases(self, question: str) -> str:
        return re.sub(
            r"\b(?:только\s+)?(?:в\s+наличии|на\s+остатках)\b",
            " ",
            question,
            flags=re.IGNORECASE,
        )

    def _extract_division_filters(self, question: str, domain: str) -> dict[str, str]:
        if domain not in {"sales", "division_dimension"}:
            return {}
        filters: dict[str, str] = {}
        for column_name, aliases in DIVISION_ATTRIBUTE_ALIASES.items():
            value = self._extract_dimension_filter_value(question, aliases)
            if value:
                filters[column_name] = value
        return filters

    def _extract_dimension_filters(
        self,
        question: str,
        domain: str,
    ) -> dict[str, str | list[str]]:
        if domain not in {
            "sales",
            "retail_price",
            "product_cost",
            "stock",
            "purchases",
            "product_dimension",
        }:
            return {}

        filters: dict[str, str | list[str]] = {}
        bu_value = self._extract_known_bu_value(question)
        if bu_value:
            filters["bu"] = bu_value

        for column_name, aliases in PRODUCT_DIMENSION_ATTRIBUTE_ALIASES.items():
            if column_name in {"product_id", "bu"} and column_name in filters:
                continue
            if column_name == "product_id":
                continue
            if column_name == "product" and re.search(
                r"\bproduct\s+\d+\b", question, flags=re.IGNORECASE
            ):
                continue
            values = self._extract_dimension_filter_values(question, aliases)
            if values:
                filters[column_name] = values[0] if len(values) == 1 else values
        return filters

    def _extract_dimension_prefix_filters(
        self,
        question: str,
        domain: str,
    ) -> dict[str, str]:
        if domain not in {
            "sales",
            "retail_price",
            "product_cost",
            "stock",
            "purchases",
            "product_dimension",
        }:
            return {}

        filters: dict[str, str] = {}
        for column_name, aliases in PRODUCT_DIMENSION_ATTRIBUTE_ALIASES.items():
            for alias in sorted(aliases, key=len, reverse=True):
                pattern = (
                    re.escape(alias)
                    + r"(?:ом|ем|у|а|е|ом)?\s+"
                    r"(?:начина(?:ется|ющийся|ющаяся|ющееся|ющиеся)\s+(?:с|на)|"
                    r"starts?\s+with)\s+"
                    r"(?:\"([^\"]+)\"|'([^']+)'|«([^»]+)»|"
                    r"([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9_./&\-]*))"
                )
                match = re.search(pattern, question, flags=re.IGNORECASE)
                if not match:
                    continue
                value = next(group for group in match.groups() if group is not None)
                filters[column_name] = value.strip(" .,:;")
                break
        return filters

    def _extract_known_bu_value(self, question: str) -> str | None:
        for value, patterns in PRODUCT_DIMENSION_BU_VALUE_ALIASES.items():
            if any(re.search(pattern, question, flags=re.IGNORECASE) for pattern in patterns):
                return value
        return None

    def _extract_dimension_filter_value(
        self,
        question: str,
        aliases: tuple[str, ...],
    ) -> str | None:
        values = self._extract_dimension_filter_values(question, aliases)
        return values[0] if values else None

    def _extract_dimension_filter_values(
        self,
        question: str,
        aliases: tuple[str, ...],
    ) -> list[str]:
        for alias in sorted(aliases, key=len, reverse=True):
            pattern = (
                r"(?:с\s+|по\s+|для\s+|у\s+)?"
                + re.escape(alias)
                + r"(?:ом|ем|у|а|е|ом)?\s*(?:=|:|№|#)?\s*"
                r"(?:"
                r'"([^"]+)"'
                r"|'([^']+)'"
                r"|«([^»]+)»"
                r"|([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9_./&,\- ]*)"
                r")"
            )
            match = re.search(pattern, question, flags=re.IGNORECASE)
            if not match:
                continue
            matched_group_index, value = next(
                (index, group)
                for index, group in enumerate(match.groups())
                if group is not None
            )
            value = value.strip(" .,:;")
            if re.match(
                r"^(?:и|and|за|на|с|по|где|where|order|sort|разбивка)\b",
                value,
                flags=re.IGNORECASE,
            ):
                continue
            value = re.split(
                r"\s+(?:и|and|за|на|с|по|при|где|where|order|sort|разбивка)\s+",
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" .,:;")
            if value:
                if matched_group_index < 3:
                    return [value]
                return [
                    item.strip(" .,:;")
                    for item in value.split(",")
                    if item.strip(" .,:;")
                ]
        return []

    def _extract_identifier_value(self, question: str, domain: str) -> str | None:
        values = self._extract_identifier_values(question, domain)
        return values[0] if values else None

    def _extract_identifier_values(self, question: str, domain: str) -> list[str]:
        if domain == "retail_price":
            return parse_ware_id_filters(question)

        identifier_values = self._extract_product_identifier_values(question, domain)
        if identifier_values:
            return identifier_values

        if domain == "purchases":
            patterns = (
                r"product_id\s*[=:]?\s*(\d+)",
                r"(?:товар[а-яё]*|для\s+товара|у\s+товара)\s+(\d+)",
                r"product\s+(\d+)",
            )
            for pattern in patterns:
                match = re.search(pattern, question, flags=re.IGNORECASE)
                if match:
                    return [match.group(1)]
            return []

        if domain == "stock":
            patterns = (
                r"product_id\s*[=:]?\s*(\d+)",
                r"(?:код(?:ом)?\s+спрута|спрут(?:а|у)?|sprut(?:\s+code)?)\s*[#:№=\-]?\s*(\d+)",
                r"(?:товар[а-я]*|для\s+товара|у\s+товара)\s+(\d+)",
                r"product\s+(\d+)",
            )
            for pattern in patterns:
                match = re.search(pattern, question, flags=re.IGNORECASE)
                if match:
                    return [match.group(1)]
            return []

        patterns = (
            r"product_id\s*[=:]?\s*(\d+)",
            r"(?:товар[ауюом]?|для\s+товара|у\s+товара)\s+(\d+)",
            r"product\s+(\d+)",
        )
        for pattern in patterns:
            match = re.search(pattern, question, flags=re.IGNORECASE)
            if match:
                return [match.group(1)]
        return []

    def _extract_product_identifier_values(self, question: str, domain: str) -> list[str]:
        patterns = [
            r"product_id\s*(?:=|:|in)?\s*\(?\s*([0-9][0-9,\s;]*)",
            r"(?:товар[а-яё]*|для\s+товара|у\s+товара)\s+([0-9][0-9,\s;]*)",
            r"(?:код(?:ом)?\s+спрута|спрут(?:а|у)?|sprut(?:\s+code)?)\s*[#:№=\-]?\s*([0-9][0-9,\s;]*)",
            r"(?:товар[а-яё]*|для\s+товара|у\s+товара)\s+([0-9][0-9,\s;]*)",
            r"product\s+([0-9][0-9,\s;]*)",
        ]
        if domain == "product_cost":
            patterns.insert(
                0,
                r"(?:себес[а-яё]*|себестоим[а-яё]*|себестом[а-яё]*)\s+(\d{5,})\b",
            )

        for pattern in patterns:
            match = re.search(pattern, question, flags=re.IGNORECASE)
            if match:
                return self._parse_identifier_list(match.group(1))
        return []

    def _parse_identifier_list(self, value: str) -> list[str]:
        identifiers: list[str] = []
        for identifier in re.findall(r"\d+", value):
            if identifier not in identifiers:
                identifiers.append(identifier)
        return identifiers

    def _extract_metric_column(self, question: str, domain: str) -> str | None:
        lowered = question.lower()
        if domain == "product_dimension":
            matches: list[tuple[int, str]] = []
            for column_name, aliases in PRODUCT_DIMENSION_ATTRIBUTE_ALIASES.items():
                positions = [
                    lowered.find(candidate)
                    for candidate in (column_name, *aliases)
                    if candidate in lowered
                ]
                if positions:
                    matches.append((min(positions), column_name))
            return min(matches)[1] if matches else None
        if domain == "product_cost":
            has_cost_marker = "себестоим" in lowered or "себестом" in lowered
            if has_cost_marker and "остат" in lowered:
                return "cost_sum"
            if has_cost_marker and "единиц" in lowered:
                return "cost_per_unit"
            for column_name, aliases in COST_METRIC_ALIASES.items():
                if any(alias in lowered for alias in aliases):
                    return column_name
            if has_cost_marker:
                return "cost"
            return None
        if domain == "stock":
            for column_name, aliases in STOCK_METRIC_ALIASES.items():
                if any(alias in lowered for alias in aliases):
                    return column_name
            if "amount" in lowered:
                return "amount"
            return "quantity"
        if domain == "purchases":
            if "ндс" in lowered:
                if "usd" in lowered:
                    return "NDS_usd"
                if "eur" in lowered:
                    return "NDS_eur"
                if "chf" in lowered:
                    return "NDS_chf"
                return "NDS_kzt"
            if "usd" in lowered or "доллар" in lowered:
                return "amount_usd"
            if "eur" in lowered or "евро" in lowered:
                return "amount_eur"
            if "chf" in lowered or "франк" in lowered:
                return "amount_chf"
            if "kzt" in lowered or "тенге" in lowered:
                return "amount_kzt"
            for column_name, aliases in PURCHASE_METRIC_ALIASES.items():
                if any(alias in lowered for alias in aliases):
                    return column_name
            if "за единиц" in lowered or "per unit" in lowered:
                if "usd" in lowered:
                    return "amount_usd"
                if "eur" in lowered:
                    return "amount_eur"
                if "chf" in lowered:
                    return "amount_chf"
            return "amount_kzt"
        if domain == "retail_price":
            for alias, column_name in CURRENCY_ALIAS_MAP.items():
                if alias in lowered:
                    return column_name
            for marker in (
                "full_retail_price_kzt",
                "full_retail_price_eur",
                "full_retail_price_usd",
                "full_price_level_kzt",
                "full_price_level_usd",
                "full_price_level_eur",
                "_rank",
                "brand",
            ):
                if marker in lowered:
                    return "_RANK" if marker == "_rank" else marker
            return None

        payment_metric = self._extract_payment_metric(lowered)
        if payment_metric:
            return payment_metric

        if self._is_amount_metric_request(lowered):
            for alias, price_column in CURRENCY_ALIAS_MAP.items():
                if alias in lowered:
                    if price_column.endswith("_usd"):
                        return "amount_usd"
                    if price_column.endswith("_eur"):
                        return "amount_eur"
                    return "amount"
            return "amount"

        if self._is_quantity_metric_request(lowered) or any(marker in lowered for marker in ("продав", "продан")):
            return "quantity"

        if any(marker in lowered for marker in ("продаж", "sales", "amount")):
            return "amount"
        for column_name, aliases in SALES_METRIC_ALIASES.items():
            if any(alias in lowered for alias in aliases):
                return column_name
        return None

    def _extract_payment_metric(self, lowered: str) -> str | None:
        payment_aliases = {
            "cash": ("cash", "налич", "наличн"),
            "card": ("card", "карт"),
            "loan": ("loan", "кредит"),
            "bonus": ("bonus", "бонус"),
        }
        for column_name, aliases in payment_aliases.items():
            if any(alias in lowered for alias in aliases):
                return column_name
        return None

    def _extract_aggregate_function(self, lowered: str) -> str | None:
        if any(marker in lowered for marker in ("максим", "max", "highest")):
            return "max"
        if any(marker in lowered for marker in ("миним", "min", "lowest")):
            return "min"
        if any(marker in lowered for marker in ("средн", "avg", "average")):
            return "avg"
        if any(marker in lowered for marker in ("сумм", "sum", "итого")):
            return "sum"
        if any(marker in lowered for marker in ("сколько", "count", "количество")):
            return "count"
        return None

    def _extract_group_by(self, lowered: str, domain: str) -> str | None:
        if domain in {"sales", "division_dimension"}:
            division_group_by = self._extract_division_group_by(lowered)
            if division_group_by:
                return division_group_by
        if domain == "product_dimension":
            for group_by, aliases in PRODUCT_DIMENSION_ATTRIBUTE_ALIASES.items():
                markers = tuple(
                    marker
                    for alias in aliases
                    for marker in (f"by {alias}", f"по {alias}")
                ) + (f"by {group_by}", f"по {group_by}")
                if any(marker in lowered for marker in markers):
                    return group_by
                if any(
                    re.search(
                        rf"\bпо\s+{re.escape(alias[:-1])}[а-яё]*\b",
                        lowered,
                    )
                    for alias in aliases
                    if len(alias) >= 5
                    and re.fullmatch(r"[а-яё -]+", alias)
                ):
                    return group_by
            return None
        if domain == "stock":
            aliases = {
                "date": ("по дате", "по датам", "by date"),
                "product_id": (
                    "по товару",
                    "по товарам",
                    "по коду спрута",
                    "по кодам спрута",
                    "by product",
                    "by sprut code",
                ),
                "warehouse_id": ("по складу", "по складам", "by warehouse"),
                "recorder_type": ("по операци", "по типу", "by operation"),
                "document_id": ("по документ", "by document"),
                "source_database": ("по базе", "по источнику", "by source"),
            }
            for group_by, markers in aliases.items():
                if any(marker in lowered for marker in markers):
                    return group_by
            return None
        if domain == "product_cost":
            aliases = {
                "date": ("по дате", "по датам", "by date"),
                "product_id": ("по товару", "по товарам", "by product"),
                "op_type": ("по типу операции", "by operation type"),
                "db": ("по базе", "по источнику", "by source"),
            }
            for group_by, markers in aliases.items():
                if any(marker in lowered for marker in markers):
                    return group_by
            return None
        if domain == "purchases":
            aliases = {
                "purchase_date": ("по дате", "по датам", "by date"),
                "product_id": ("по товару", "по товарам", "by product"),
                "recorder_type": ("по операц", "по типу", "by operation"),
                "recorder_number": ("по документ", "by document"),
                "division_id": ("по подраздел", "by division"),
                "source_database": ("по базе", "по источнику", "by source"),
            }
            for group_by, markers in aliases.items():
                if any(marker in lowered for marker in markers):
                    return group_by
            return None
        if domain == "sales":
            dimension_group_by = self._extract_dimension_group_by(lowered)
            if dimension_group_by:
                return dimension_group_by
            for group_by, aliases in SALES_GROUP_BY_ALIASES.items():
                if any(alias in lowered for alias in aliases):
                    return group_by
            return None

        if domain in {"retail_price", "product_cost", "stock", "purchases"}:
            dimension_group_by = self._extract_dimension_group_by(lowered)
            if dimension_group_by:
                return dimension_group_by

        if "по дате" in lowered or "по датам" in lowered:
            return "price_date"
        if (
            "по ware_id" in lowered
            or "по складу" in lowered
            or "по складам" in lowered
            or "склад" in lowered
        ):
            return "ware_id"
        return None

    def _extract_group_by_columns(
        self,
        lowered: str,
        domain: str,
        primary_group_by: str | None,
    ) -> list[str]:
        if not primary_group_by:
            return []

        columns = [primary_group_by]
        if domain not in {
            "sales",
            "retail_price",
            "product_cost",
            "stock",
            "purchases",
            "product_dimension",
        }:
            return columns

        grouping_markers = (
            "группировка по ",
            "группировкой по ",
            "сгруппировать по ",
            "в разрезе ",
            "group by ",
            "grouped by ",
            "breakdown by ",
        )
        marker_positions = [
            lowered.find(marker) + len(marker)
            for marker in grouping_markers
            if marker in lowered
        ]
        if not marker_positions:
            return columns

        grouping_text = lowered[min(marker_positions):]
        matches: list[tuple[int, str]] = []
        for column_name, aliases in PRODUCT_DIMENSION_ATTRIBUTE_ALIASES.items():
            candidates = {
                candidate
                for alias in (*aliases, column_name)
                for candidate in (
                    alias,
                    alias[:-1] if len(alias) >= 6 and any("а" <= char <= "я" for char in alias) else "",
                )
                if candidate
            }
            positions = [
                grouping_text.find(candidate)
                for candidate in candidates
                if candidate in grouping_text
            ]
            if positions:
                matches.append((min(positions), column_name))

        for _, column_name in sorted(matches):
            if column_name not in columns:
                columns.append(column_name)
        return columns

    def _extract_dimension_group_by(self, lowered: str) -> str | None:
        grouping_markers = (
            "группировка по ",
            "группировкой по ",
            "сгруппировать по ",
            "в разрезе ",
            "group by ",
            "grouped by ",
            "breakdown by ",
        )
        for column_name, aliases in PRODUCT_DIMENSION_ATTRIBUTE_ALIASES.items():
            for alias in (*aliases, column_name):
                if any(f"{marker}{alias}" in lowered for marker in grouping_markers):
                    return column_name
        return None

    def _extract_division_group_by(self, lowered: str) -> str | None:
        explicit_grouping_markers = (
            "в разрезе ",
            "группировка по ",
            "group by ",
            "grouped by ",
            "breakdown by ",
        )
        plural_aliases = {
            "division": ("магазинам", "бутикам", "точкам продаж", "подразделениям"),
            "city": ("городам",),
        }
        for column_name, aliases in DIVISION_ATTRIBUTE_ALIASES.items():
            for alias in (*aliases, *plural_aliases[column_name], column_name):
                if any(f"{marker}{alias}" in lowered for marker in explicit_grouping_markers):
                    return column_name
            if any(f"по {alias}" in lowered for alias in plural_aliases[column_name]):
                return column_name
        return None

    def _wants_single_best(self, lowered: str) -> bool:
        if re.search(r"\b(?:top|топ|limit)\s+\d+\b", lowered, flags=re.IGNORECASE):
            return False
        return any(
            marker in lowered
            for marker in (
                "лучше всего",
                "лучший",
                "лучшая",
                "лучшее",
                "самый продаваемый",
                "самая продаваемая",
                "больше всего",
                "highest",
                "best",
            )
        )

    def _wants_sales_ranking(self, lowered: str) -> bool:
        has_top_limit = bool(
            re.search(r"\b(?:top|limit)\s+\d+\b", lowered, flags=re.IGNORECASE)
            or re.search(r"(?:^|\s)топ\s+\d+\b", lowered, flags=re.IGNORECASE)
        )
        if not has_top_limit:
            return False
        return any(
            marker in lowered
            for marker in (
                "sales",
                "amount",
                "продаж",
                "выручк",
                "оборот",
            )
        )

    def _wants_all_sold_products(self, lowered: str) -> bool:
        wants_all_products = any(
            marker in lowered
            for marker in (
                "все товары",
                "все товар",
                "all products",
                "all product",
            )
        )
        has_sold_marker = any(
            marker in lowered
            for marker in (
                "продан",
                "продав",
                "sold",
            )
        )
        return wants_all_products and has_sold_marker

    def _is_quantity_metric_request(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in (
                "по количеству",
                "количеству",
                "количество",
                "quantity",
                "qty",
                "штук",
                "шт",
            )
        )

    def _is_amount_metric_request(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in (
                "по сумме",
                "сумме продаж",
                "сумма продаж",
                "сумм",
                "выручк",
                "оборот",
                "amount",
                "usd",
                "eur",
                "kzt",
                "тенге",
            )
        )

    def _extract_requested_columns(
        self,
        question: str,
        domain: str,
        *,
        include_context_columns: bool = True,
    ) -> list[str]:
        lowered = question.lower()
        if not include_context_columns:
            lowered = re.sub(
                r"\b(?:dimension_product|v_purchases|sales|stock|cost|price|division)\b",
                " ",
                lowered,
            )
        columns: list[str] = []
        if domain == "division_dimension":
            if self._wants_all_columns(lowered):
                return list(DIVISION_COLUMNS)
            for column_name, aliases in DIVISION_ATTRIBUTE_ALIASES.items():
                if any(alias in lowered for alias in aliases):
                    columns.append(column_name)
            return self._dedupe(columns or list(DIVISION_COLUMNS))
        if domain == "product_dimension":
            if self._wants_all_columns(lowered):
                return list(PRODUCT_DIMENSION_COLUMNS)
            if "название" in lowered:
                columns.append("name")
            for column_name, aliases in PRODUCT_DIMENSION_ATTRIBUTE_ALIASES.items():
                if any(
                    self._mentions_column_alias(
                        lowered,
                        alias,
                        exact_ascii=not include_context_columns,
                    )
                    for alias in aliases
                ):
                    columns.append(column_name)
            if not columns or (
                include_context_columns and self._looks_like_sales_row_request(lowered)
            ):
                return list(PRODUCT_DIMENSION_COLUMNS)
            if include_context_columns and "product_id" not in columns:
                columns.insert(0, "product_id")
            return self._dedupe(columns)
        if domain == "stock":
            if self._wants_all_columns(lowered):
                return list(STOCK_COLUMNS)
            column_aliases = {
                "source_database": ("source_database", "источник", "база 1с"),
                "date": ("date", "дата"),
                "recorder_type": ("recorder_type", "операц", "перемещен"),
                "recorder_type_guid": ("recorder_type_guid",),
                "recorder_guid": ("recorder_guid", "идентификатор документ"),
                "warehouse_id": ("warehouse_id", "склад"),
                "product_id": ("product_id", "товар", "product"),
                "quantity": ("quantity", "количеств", "остатк"),
                "amount": ("amount",),
                "document_id": ("document_id", "номер документ", "документ", "1с"),
                "movement_index": ("movement_index", "хронолог", "номер операц"),
            }
            for column_name, aliases in column_aliases.items():
                if any(alias in lowered for alias in aliases):
                    columns.append(column_name)
            if not columns or (
                include_context_columns and self._looks_like_sales_row_request(lowered)
            ):
                return list(STOCK_COLUMNS)
            if include_context_columns:
                for required_column in ("date", "product_id"):
                    if required_column not in columns:
                        columns.insert(0, required_column)
            return self._dedupe(columns)
        if domain == "product_cost":
            if self._wants_all_columns(lowered):
                return list(COST_COLUMNS)
            if self._wants_product_cost_history(lowered):
                return list(COST_PRODUCT_HISTORY_COLUMNS)
            column_aliases = {
                "db": (" db", "источник", "база 1с"),
                "date": ("date", "дата"),
                "op_type": ("op_type", "тип операции"),
                "doc_num": ("doc_num", "документ"),
                "product_id": ("product_id", "товар", "product"),
                "quantity": ("quantity", "количество"),
                "cost": (" cost", "себестоимость операции", "сумма операции"),
                "cost_per_unit": ("cost_per_unit", "за единицу", "единицы"),
                "qnt_sum": ("qnt_sum", "остаток товара", "остаток в штуках"),
                "cost_sum": ("cost_sum", "себестоимость остатка", "стоимость остатка"),
                "zeroed": ("zeroed", "обнул"),
            }
            for column_name, aliases in column_aliases.items():
                if any(alias in f" {lowered}" for alias in aliases):
                    columns.append(column_name)
            metric_column = self._extract_metric_column(question, domain)
            if metric_column:
                columns.append(metric_column)
            if not columns or (
                include_context_columns and self._looks_like_sales_row_request(lowered)
            ):
                return list(COST_COLUMNS)
            if include_context_columns:
                for required_column in ("date", "product_id"):
                    if required_column not in columns:
                        columns.insert(0, required_column)
            return self._dedupe(columns)
        if domain == "purchases":
            if self._wants_all_columns(lowered):
                return list(PURCHASE_COLUMNS)
            column_aliases = {
                "source_database": ("source_database", "источник", "база 1с"),
                "purchase_date": ("purchase_date", "дата"),
                "recorder_type": ("recorder_type", "операц"),
                "recorder_number": ("recorder_number", "номер документ", "документ", "1с"),
                "product_id": ("product_id", "товар", "product"),
                "quantity": ("quantity", "количеств"),
                "division_id": ("division_id", "подраздел"),
                "amount_kzt": ("amount_kzt", "kzt", "тенге"),
                "NDS_kzt": ("nds_kzt", "ндс"),
                "amount_usd": ("amount_usd", "usd"),
                "NDS_usd": ("nds_usd",),
                "amount_eur": ("amount_eur", "eur"),
                "NDS_eur": ("nds_eur",),
                "amount_chf": ("amount_chf", "chf"),
                "NDS_chf": ("nds_chf",),
            }
            for column_name, aliases in column_aliases.items():
                if any(alias in lowered for alias in aliases):
                    columns.append(column_name)
            metric_column = self._extract_metric_column(question, domain)
            if metric_column:
                columns.append(metric_column)
            if not columns or (
                include_context_columns and self._looks_like_sales_row_request(lowered)
            ):
                return list(PURCHASE_COLUMNS)
            if include_context_columns:
                for required_column in ("purchase_date", "product_id"):
                    if required_column not in columns:
                        columns.insert(0, required_column)
            return self._dedupe(columns)
        if domain == "sales":
            if self._wants_all_columns(lowered):
                return list(SALES_COLUMNS)
            if include_context_columns and self._looks_like_sales_row_request(lowered):
                return list(SALES_COLUMNS)
            if any(marker in lowered for marker in ("дата", "sale_date")):
                columns.append("sale_date")
            if any(marker in lowered for marker in ("document", "документ", "чек")):
                columns.append("document_number")
            if any(marker in lowered for marker in ("product_id", "товар", "product")):
                columns.append("product_id")
            if any(marker in lowered for marker in ("customer", "клиент")):
                columns.append("customer_id")
            if any(marker in lowered for marker in ("payment", "оплат")):
                columns.extend(["payment_type", "payment_method"])
            if not include_context_columns:
                for column_name, aliases in PRODUCT_DIMENSION_ATTRIBUTE_ALIASES.items():
                    if column_name != "product_id" and any(
                        self._mentions_column_alias(lowered, alias, exact_ascii=True)
                        for alias in aliases
                    ):
                        columns.append(column_name)
                for column_name, aliases in DIVISION_ATTRIBUTE_ALIASES.items():
                    if any(alias in lowered for alias in aliases):
                        columns.append(column_name)

            metric_column = self._extract_metric_column(question, domain)
            # A bare mention of sales identifies the domain, not an explicit
            # request for the amount column. Return detailed sales rows unless
            # the user asks for a metric such as revenue, total, or currency.
            if metric_column == "amount" and not self._is_amount_metric_request(lowered):
                return self._dedupe(columns) if columns else list(SALES_COLUMNS)
            if metric_column:
                columns.append(metric_column)
            else:
                columns.extend(SALES_COLUMNS)
            return self._dedupe(columns)

        if self._wants_all_columns(lowered):
            return list(RETAIL_PRICE_COLUMNS)
        if is_price_question(question):
            columns.extend(["price_date", "ware_id"])
        elif "price_date" in lowered or "дата" in lowered:
            columns.append("price_date")
        if "ware_id" in lowered or "товар" in lowered:
            columns.append("ware_id")
        if "brand" in lowered or "бренд" in lowered:
            columns.append("brand")
        if "_rank" in lowered or "rank" in lowered:
            columns.append("_RANK")
        if "price_level" in lowered or "диапазон" in lowered:
            columns.extend(["full_price_level_kzt", "full_price_level_usd", "full_price_level_eur"])

        metric_column = self._extract_metric_column(question, domain)
        if metric_column:
            columns.append(metric_column)
        elif is_price_question(question):
            columns.extend(
                [
                    "full_retail_price_kzt",
                    "full_retail_price_eur",
                    "full_retail_price_usd",
                ]
            )
        return self._dedupe(columns)

    def _looks_like_sales_row_request(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in (
                "покажи",
                "выведи",
                "последн",
                "строк",
                "запис",
                "show",
                "rows",
                "latest",
            )
        )

    def _extract_sort(self, lowered: str, metric_column: str | None, domain: str) -> tuple[str | None, str]:
        date_column = self._date_column(domain)
        if domain == "product_dimension":
            if "top" in lowered or "С‚РѕРї" in lowered:
                return metric_column or "product_id", "desc"
            return "product_id", "asc"
        if domain in {"retail_price", "product_cost", "stock", "purchases"} and any(
            marker in lowered
            for marker in ("истори", "динамик", "history", "dynamics")
        ):
            return date_column, "asc"
        if "топ" in lowered or "top" in lowered:
            return metric_column or date_column, "desc"
        if self._wants_latest_price(lowered):
            return date_column, "desc"
        if "first" in lowered or "первые" in lowered:
            return date_column, "asc"
        return date_column, "desc"

    def _date_column(self, domain: str) -> str | None:
        return {"sales": "sale_date", "product_cost": "date", "stock": "date", "purchases": "purchase_date", "product_dimension": None, "division_dimension": None}.get(domain, "price_date")

    def _identifier_column(self, domain: str) -> str:
        if domain == "division_dimension":
            return "id"
        return "product_id" if domain in {"sales", "product_cost", "stock", "purchases", "product_dimension"} else "ware_id"

    def _table_name(self, domain: str) -> str:
        return {"sales": "sales", "product_cost": COST_TABLE, "stock": STOCK_TABLE, "purchases": PURCHASE_TABLE, "product_dimension": PRODUCT_DIMENSION_TABLE, "division_dimension": DIVISION_TABLE}.get(domain, RETAIL_PRICE_TABLE)

    def _database_name(self, domain: str) -> str | None:
        if domain in {"product_cost", "stock", "purchases", "product_dimension", "division_dimension"}:
            return "DWH"
        return RETAIL_PRICE_DATABASE if domain == "retail_price" else None

    def _domain_columns(self, domain: str) -> list[str]:
        return {"sales": SALES_COLUMNS, "product_cost": COST_COLUMNS, "stock": STOCK_COLUMNS, "purchases": PURCHASE_COLUMNS, "product_dimension": PRODUCT_DIMENSION_COLUMNS, "division_dimension": DIVISION_COLUMNS}.get(domain, RETAIL_PRICE_COLUMNS)

    def _wants_stock_balance(self, lowered: str) -> bool:
        return "остат" in lowered or "balance" in lowered

    def _extract_stock_balance_mode(self, lowered: str) -> str:
        wants_start = any(marker in lowered for marker in ("на начал", "start", "beginning"))
        wants_end = any(marker in lowered for marker in ("на кон", "конец", "end"))
        if wants_start and wants_end:
            return "period"
        if wants_start:
            return "start"
        return "end"

    def _wants_all_rows(self, lowered: str) -> bool:
        if self._wants_all_columns(lowered):
            return self._wants_all_data(lowered)
        return any(
            marker in lowered
            for marker in (
                "все строки",
                "все записи",
                "все данные",
                "все продажи",
                "все",
                "всё",
                "all",
                "без лимита",
                "без ограничений",
                "за весь период",
                "лимит не используй",
            )
        )

    def _wants_latest_price(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in (
                "latest",
                "last",
                "последн",
                "действующ",
                "актуальн",
            )
        )

    def _wants_gross_margin(self, lowered: str) -> bool:
        return bool(
            re.search(
                r"(?:\bgm\b|\bгм\b|gross\s+margin|маржинальност|марж[аиуеой])",
                lowered,
                flags=re.IGNORECASE,
            )
        )

    def _extract_discount_percent(self, question: str) -> float | None:
        match = re.search(
            r"\b(?:при\s+)?(?:скидк[аеуи]|discount(?:\s+of)?)\s*"
            r"(?:в\s*)?(\d+(?:[.,]\d+)?)\s*%?",
            question,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        discount_percent = float(match.group(1).replace(",", "."))
        if 0 <= discount_percent <= 100:
            return discount_percent
        return None

    def _extract_gross_margin_scope(self, lowered: str) -> str:
        if any(marker in lowered for marker in ("артикул", "article")):
            return "article"
        if any(marker in lowered for marker in ("бренд", "brand")):
            return "brand"
        return "product_id"

    def _wants_all_columns(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in (
                "все данные",
                "все колонки",
                "все столбцы",
                "все поля",
                "all columns",
                "all fields",
                "select *",
            )
        )

    def _wants_all_data(self, lowered: str) -> bool:
        return "все данные" in lowered

    def _wants_distinct_values(self, lowered: str) -> bool:
        return bool(re.search(r"\bуникальн\w*\b", lowered)) or bool(
            re.search(r"\bdistinct\b", lowered)
        )

    def _mentions_column_alias(
        self,
        lowered: str,
        alias: str,
        *,
        exact_ascii: bool,
    ) -> bool:
        if exact_ascii and alias.isascii():
            return bool(
                re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])",
                    lowered,
                )
            )
        return alias in lowered

    def _wants_product_cost_history(self, lowered: str) -> bool:
        has_cost_marker = any(
            marker in lowered for marker in ("себестоим", "себестом", "себес")
        )
        has_product_marker = any(
            marker in lowered for marker in ("товар", "product")
        )
        has_shorthand_product_id = bool(
            re.search(r"\bсебес[а-яё]*\s+\d{5,}\b", lowered)
        )
        return has_cost_marker and (has_product_marker or has_shorthand_product_id)

    def _has_explicit_limit(self, lowered: str) -> bool:
        return bool(
            re.search(
                r"\b(?:top|топ|limit|покажи|выведи|первые|последние)\s+\d+\b",
                lowered,
                flags=re.IGNORECASE,
            )
        )

    def _looks_like_row_request(
        self,
        lowered: str,
        filters: QueryFilters,
        limit: int | None,
    ) -> bool:
        if limit != DEFAULT_PREVIEW_ROWS:
            return True
        if filters.date_eq or filters.date_from or filters.date_to:
            return True
        return any(
            marker in lowered
            for marker in (
                "топ",
                "top",
                "limit",
                "строк",
                "запис",
                "продаж",
                "продажи",
                "sales",
                "отобрази",
            )
        )

    def _dedupe(self, columns: list[str]) -> list[str]:
        deduped: list[str] = []
        for column in columns:
            if column not in deduped:
                deduped.append(column)
        return deduped
