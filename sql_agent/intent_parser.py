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
    "quantity",
    "amount",
    "amount_usd",
    "amount_eur",
]

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
        "товар",
        "товара",
        "товару",
        "товаров",
        "product",
        "product_id",
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
        domain = self._detect_domain(question)
        schema_name, table_name = self._resolve_table(question, engine, domain)
        date_column = "sale_date" if domain == "sales" else "price_date"
        identifier_column = "product_id" if domain == "sales" else "ware_id"
        filters = self._build_filters(question, domain, date_column, identifier_column)
        limit = parse_requested_limit(question)

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
                table_name=table_name or ("sales" if domain == "sales" else RETAIL_PRICE_TABLE),
            )

        aggregate_function = self._extract_aggregate_function(lowered)
        metric_column = self._extract_metric_column(question, domain)
        group_by = self._extract_group_by(lowered, domain)
        if (
            domain == "sales"
            and filters.identifier_value
            and group_by == "product_id"
            and (
                self._looks_like_sales_row_request(lowered)
                or not any(marker in lowered for marker in ("\u043f\u043e \u0442\u043e\u0432\u0430\u0440\u0430\u043c", "by product"))
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

        if aggregate_function and (metric_column or aggregate_function == "count"):
            return QueryIntent(
                operation="aggregate",
                domain=domain,
                database_name=self._default_database_name(domain, table_name),
                schema_name=schema_name or "LLM",
                table_name=table_name or ("sales" if domain == "sales" else RETAIL_PRICE_TABLE),
                metric_column=metric_column,
                aggregate_function=aggregate_function,
                group_by=group_by,
                limit=limit,
                filters=filters,
                sort_column=group_by,
                sort_direction="desc",
            )

        if table_name is not None or domain in {"sales", "retail_price"} or filters.date_eq or filters.date_from:
            requested_columns = self._extract_requested_columns(question, domain)
            if not requested_columns:
                requested_columns = list(SALES_COLUMNS if domain == "sales" else RETAIL_PRICE_COLUMNS)
            if limit is None and not self._wants_all_rows(lowered):
                limit = DEFAULT_PREVIEW_ROWS
            sort_column, sort_direction = self._extract_sort(lowered, metric_column, domain)
            return QueryIntent(
                operation="select",
                domain=domain,
                database_name=self._default_database_name(domain, table_name),
                schema_name=schema_name or "LLM",
                table_name=table_name or ("sales" if domain == "sales" else RETAIL_PRICE_TABLE),
                requested_columns=requested_columns,
                metric_column=metric_column,
                limit=limit,
                sort_column=sort_column,
                sort_direction=sort_direction,
                latest_per_identifier=(
                    domain == "retail_price"
                    and bool(filters.identifier_values)
                    and self._wants_latest_price(lowered)
                ),
                filters=filters,
            )

        return QueryIntent(operation="unknown")

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
        schema_snapshot = memory.schema_snapshot[:1400] if memory.schema_snapshot else "DWH.LLM.price, LLM.sales"
        return (
            "You are an intent parser for a Microsoft SQL Server analytics assistant.\n"
            "Return JSON only. Infer intent, not SQL.\n"
            "Supported domains: retail_price, sales.\n"
            "Supported operations: select, aggregate, schema, unknown.\n"
            "Retail price table: DWH.LLM.price with date column price_date and product/warehouse column ware_id.\n"
            "Sales table: LLM.sales with date column sale_date and integer product column product_id. Do not use customer_name; it is not present.\n"
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
        if operation not in {"select", "aggregate", "schema", "unknown"}:
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
        if domain not in {"retail_price", "sales"}:
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
            database_name=str(payload.get("database_name") or RETAIL_PRICE_DATABASE) if domain == "retail_price" else payload.get("database_name"),
            schema_name=str(payload.get("schema_name") or "LLM"),
            table_name=str(payload.get("table_name") or ("sales" if domain == "sales" else RETAIL_PRICE_TABLE)),
            requested_columns=[str(item) for item in requested_columns],
            metric_column=payload.get("metric_column"),
            aggregate_function=payload.get("aggregate_function"),
            group_by=payload.get("group_by"),
            limit=limit,
            sort_column=payload.get("sort_column"),
            sort_direction=str(payload.get("sort_direction") or "desc").lower(),
            latest_per_identifier=bool(payload.get("latest_per_identifier") or False),
            filters=filters,
        )

    def _detect_domain(self, question: str) -> str:
        lowered = question.lower()
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
            "product_id",
            "\u043e\u043f\u043b\u0430\u0442",
            "\u043d\u0430\u043b\u0438\u0447",
            "\u043a\u0430\u0440\u0442",
            "\u043a\u0440\u0435\u0434\u0438\u0442",
            "\u0431\u043e\u043d\u0443\u0441",
        )
        if any(marker in lowered for marker in sales_markers):
            return "sales"
        if is_price_question(question):
            return "retail_price"
        return "retail_price"

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

        return ("LLM", "sales") if domain == "sales" else (RETAIL_PRICE_SCHEMA, RETAIL_PRICE_TABLE)

    def _default_database_name(self, domain: str, table_name: str | None) -> str | None:
        if domain == "retail_price" and (table_name is None or table_name == RETAIL_PRICE_TABLE):
            return RETAIL_PRICE_DATABASE
        return None

    def _build_filters(
        self,
        question: str,
        domain: str,
        date_column: str,
        identifier_column: str,
    ) -> QueryFilters:
        filters = QueryFilters(date_column=date_column, identifier_column=identifier_column)
        for key, value in parse_date_filters(question):
            if key == "eq":
                filters.date_eq = value
            elif key == "between":
                filters.date_from = value
            elif key == "between_end":
                filters.date_to = value

        identifier_values = self._extract_identifier_values(question, domain)
        if identifier_values:
            filters.identifier_values = identifier_values
            filters.identifier_value = identifier_values[0]

        threshold = parse_numeric_threshold(question)
        if threshold:
            operator, value = threshold
            filters.threshold_column = self._extract_metric_column(question, domain)
            filters.threshold_operator = operator
            filters.threshold_value = value

        return filters

    def _extract_identifier_value(self, question: str, domain: str) -> str | None:
        values = self._extract_identifier_values(question, domain)
        return values[0] if values else None

    def _extract_identifier_values(self, question: str, domain: str) -> list[str]:
        if domain == "retail_price":
            return parse_ware_id_filters(question)

        patterns = (
            r"product_id\s*[=:]?\s*(\d+)",
            r"(?:\u0442\u043e\u0432\u0430\u0440[ауюом]?|\u0434\u043b\u044f\s+\u0442\u043e\u0432\u0430\u0440\u0430|\u0443\s+\u0442\u043e\u0432\u0430\u0440\u0430)\s+(\d+)",
            r"product\s+(\d+)",
        )
        for pattern in patterns:
            match = re.search(pattern, question, flags=re.IGNORECASE)
            if match:
                return [match.group(1)]
        return []

    def _extract_metric_column(self, question: str, domain: str) -> str | None:
        lowered = question.lower()
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
            "cash": ("cash", "\u043d\u0430\u043b\u0438\u0447", "\u043d\u0430\u043b\u0438\u0447\u043d"),
            "card": ("card", "\u043a\u0430\u0440\u0442"),
            "loan": ("loan", "\u043a\u0440\u0435\u0434\u0438\u0442"),
            "bonus": ("bonus", "\u0431\u043e\u043d\u0443\u0441"),
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
        if domain == "sales":
            for group_by, aliases in SALES_GROUP_BY_ALIASES.items():
                if any(alias in lowered for alias in aliases):
                    return group_by
            return None

        if "по дате" in lowered or "по датам" in lowered:
            return "price_date"
        if (
            "по ware_id" in lowered
            or "\u043f\u043e \u0441\u043a\u043b\u0430\u0434\u0443" in lowered
            or "\u043f\u043e \u0441\u043a\u043b\u0430\u0434\u0430\u043c" in lowered
            or "\u0441\u043a\u043b\u0430\u0434" in lowered
        ):
            return "ware_id"
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
            or re.search(r"(?:^|\s)\u0442\u043e\u043f\s+\d+\b", lowered, flags=re.IGNORECASE)
        )
        if not has_top_limit:
            return False
        return any(
            marker in lowered
            for marker in (
                "sales",
                "amount",
                "\u043f\u0440\u043e\u0434\u0430\u0436",
                "\u0432\u044b\u0440\u0443\u0447\u043a",
                "\u043e\u0431\u043e\u0440\u043e\u0442",
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

    def _extract_requested_columns(self, question: str, domain: str) -> list[str]:
        lowered = question.lower()
        columns: list[str] = []
        if domain == "sales":
            if self._wants_all_columns(lowered):
                return list(SALES_COLUMNS)
            if self._looks_like_sales_row_request(lowered):
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

            metric_column = self._extract_metric_column(question, domain)
            if metric_column:
                columns.append(metric_column)
            else:
                columns.extend(SALES_COLUMNS)
            return self._dedupe(columns)

        if is_price_question(question):
            columns.extend(["price_date", "ware_id"])
        elif self._wants_all_columns(lowered):
            return list(RETAIL_PRICE_COLUMNS)
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
                "\u043f\u043e\u043a\u0430\u0436\u0438",
                "\u0432\u044b\u0432\u0435\u0434\u0438",
                "\u043f\u043e\u0441\u043b\u0435\u0434\u043d",
                "\u0441\u0442\u0440\u043e\u043a",
                "\u0437\u0430\u043f\u0438\u0441",
                "show",
                "rows",
                "latest",
            )
        )

    def _extract_sort(self, lowered: str, metric_column: str | None, domain: str) -> tuple[str | None, str]:
        date_column = "sale_date" if domain == "sales" else "price_date"
        if domain == "retail_price" and any(
            marker in lowered
            for marker in ("\u0438\u0441\u0442\u043e\u0440\u0438", "\u0434\u0438\u043d\u0430\u043c\u0438\u043a")
        ):
            return date_column, "asc"
        if "топ" in lowered or "top" in lowered:
            return metric_column or date_column, "desc"
        if self._wants_latest_price(lowered):
            return date_column, "desc"
        if "first" in lowered or "первые" in lowered:
            return date_column, "asc"
        return date_column, "desc"

    def _wants_all_rows(self, lowered: str) -> bool:
        if self._wants_all_columns(lowered):
            return False
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

    def _wants_all_columns(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in (
                "все колонки",
                "все столбцы",
                "все поля",
                "all columns",
                "all fields",
                "select *",
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
