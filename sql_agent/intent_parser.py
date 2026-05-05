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
)


RETAIL_PRICE_COLUMNS = [
    "price_date",
    "ware_id",
    "full_retail_price_kzt",
    "full_retail_price_eur",
    "full_retail_price_usd",
]

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
    "quantity": ("quantity", "qty", "количество", "шт", "штук"),
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
    "product_id": ("по товару", "по товарам", "товара", "товаров", "по product_id", "by product"),
    "channel": ("по каналу", "by channel", "канал"),
    "payment_method": ("по способу оплаты", "by payment method"),
    "customer_id": ("по клиенту", "by customer"),
}


class IntentParser:
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

        if is_schema_question(question):
            if table_name is None and not permissive:
                return QueryIntent(operation="unknown")
            return QueryIntent(
                operation="schema",
                domain=domain,
                schema_name=schema_name or "BI",
                table_name=table_name or ("sales_table" if domain == "sales" else "actual_retail_price"),
            )

        aggregate_function = self._extract_aggregate_function(lowered)
        metric_column = self._extract_metric_column(question, domain)
        group_by = self._extract_group_by(lowered, domain)

        if aggregate_function and (metric_column or aggregate_function == "count"):
            return QueryIntent(
                operation="aggregate",
                domain=domain,
                schema_name=schema_name or "BI",
                table_name=table_name or ("sales_table" if domain == "sales" else "actual_retail_price"),
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
                schema_name=schema_name or "BI",
                table_name=table_name or ("sales_table" if domain == "sales" else "actual_retail_price"),
                requested_columns=requested_columns,
                metric_column=metric_column,
                limit=limit,
                sort_column=sort_column,
                sort_direction=sort_direction,
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
        schema_snapshot = memory.schema_snapshot[:1400] if memory.schema_snapshot else "BI.actual_retail_price, BI.sales_table"
        return (
            "You are an intent parser for a Microsoft SQL Server analytics assistant.\n"
            "Return JSON only. Infer intent, not SQL.\n"
            "Supported domains: retail_price, sales.\n"
            "Supported operations: select, aggregate, schema, unknown.\n"
            "Retail price table: BI.actual_retail_price with date column price_date and product column ware_id.\n"
            "Sales table: BI.sales_table with date column sale_date and product column product_id.\n"
            "If the user asks for all rows or says no limit, return null for limit.\n"
            "Schema snapshot:\n"
            f"{schema_snapshot}\n\n"
            "JSON shape:\n"
            '{"operation":"aggregate","domain":"sales","schema_name":"BI","table_name":"sales_table","requested_columns":[],"metric_column":"amount_usd","aggregate_function":"sum","group_by":"sale_date","limit":10,"sort_column":"sale_date","sort_direction":"desc","filters":{"date_column":"sale_date","date_eq":"2026-02-01","date_from":null,"date_to":null,"identifier_column":"product_id","identifier_value":null,"threshold_column":null,"threshold_operator":null,"threshold_value":null}}\n\n'
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

        return QueryIntent(
            operation=operation,
            domain=domain,
            schema_name=str(payload.get("schema_name") or "BI"),
            table_name=str(payload.get("table_name") or ("sales_table" if domain == "sales" else "actual_retail_price")),
            requested_columns=[str(item) for item in requested_columns],
            metric_column=payload.get("metric_column"),
            aggregate_function=payload.get("aggregate_function"),
            group_by=payload.get("group_by"),
            limit=limit,
            sort_column=payload.get("sort_column"),
            sort_direction=str(payload.get("sort_direction") or "desc").lower(),
            filters=filters,
        )

    def _detect_domain(self, question: str) -> str:
        lowered = question.lower()
        sales_markers = (
            "sales",
            "sale",
            "продаж",
            "выручк",
            "оборот",
            "quantity",
            "amount",
            "document_number",
            "payment",
            "customer",
            "channel",
            "product_id",
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
            "BI.actual_retail_price",
            "actual_retail_price",
            "BI.sales_table",
            "sales_table",
        ]
        table_name = extract_table_name(question, known_tables)
        if table_name == "BI.actual_retail_price":
            return ("BI", "actual_retail_price")
        if table_name == "actual_retail_price":
            return ("BI", "actual_retail_price")
        if table_name == "BI.sales_table":
            return ("BI", "sales_table")
        if table_name == "sales_table":
            return ("BI", "sales_table")

        return ("BI", "sales_table") if domain == "sales" else ("BI", "actual_retail_price")

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

        identifier_value = self._extract_identifier_value(question, domain)
        if identifier_value:
            filters.identifier_value = identifier_value

        threshold = parse_numeric_threshold(question)
        if threshold:
            operator, value = threshold
            filters.threshold_column = self._extract_metric_column(question, domain)
            filters.threshold_operator = operator
            filters.threshold_value = value

        return filters

    def _extract_identifier_value(self, question: str, domain: str) -> str | None:
        if domain == "retail_price":
            return parse_ware_id_filter(question)

        patterns = (
            r"product_id\s*[=:]?\s*([A-Za-z0-9_\-]+)",
            r"товар\s+([A-Za-z0-9_\-]+)",
            r"product\s+([A-Za-z0-9_\-]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, question, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _extract_metric_column(self, question: str, domain: str) -> str | None:
        lowered = question.lower()
        if domain == "retail_price":
            for alias, column_name in CURRENCY_ALIAS_MAP.items():
                if alias in lowered:
                    return column_name
            for marker in ("full_retail_price_kzt", "full_retail_price_eur", "full_retail_price_usd"):
                if marker in lowered:
                    return marker
            return None

        if any(marker in lowered for marker in ("продаж", "выручк", "оборот", "sales", "amount")):
            for alias, price_column in CURRENCY_ALIAS_MAP.items():
                if alias in lowered:
                    if price_column.endswith("_usd"):
                        return "amount_usd"
                    if price_column.endswith("_eur"):
                        return "amount_eur"
                    return "amount"
        for column_name, aliases in SALES_METRIC_ALIASES.items():
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
        if "по ware_id" in lowered or "по товара" in lowered or "по товар" in lowered:
            return "ware_id"
        return None

    def _extract_requested_columns(self, question: str, domain: str) -> list[str]:
        lowered = question.lower()
        columns: list[str] = []
        if domain == "sales":
            if any(marker in lowered for marker in ("дата", "sale_date")):
                columns.append("sale_date")
            if any(marker in lowered for marker in ("document", "документ", "чек")):
                columns.append("document_number")
            if any(marker in lowered for marker in ("product_id", "товар", "product")):
                columns.append("product_id")
            if any(marker in lowered for marker in ("customer", "клиент")):
                columns.extend(["customer_id", "customer_name"])
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
        elif "price_date" in lowered or "дата" in lowered:
            columns.append("price_date")
        if "ware_id" in lowered or "товар" in lowered:
            columns.append("ware_id")

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

    def _extract_sort(self, lowered: str, metric_column: str | None, domain: str) -> tuple[str | None, str]:
        date_column = "sale_date" if domain == "sales" else "price_date"
        if "топ" in lowered or "top" in lowered:
            return metric_column or date_column, "desc"
        if "latest" in lowered or "last" in lowered or "последн" in lowered:
            return date_column, "desc"
        if "first" in lowered or "первые" in lowered:
            return date_column, "asc"
        return date_column, "desc"

    def _wants_all_rows(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in (
                "все",
                "all",
                "без лимита",
                "без ограничений",
                "лимит не используй",
            )
        )

    def _dedupe(self, columns: list[str]) -> list[str]:
        deduped: list[str] = []
        for column in columns:
            if column not in deduped:
                deduped.append(column)
        return deduped
