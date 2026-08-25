from __future__ import annotations

import json
import re
from datetime import date

from openai import APIError

from sql_agent.config import CURRENCY_ALIAS_MAP, DEFAULT_PREVIEW_ROWS
from sql_agent.division_aliases import (
    canonicalize_division_name,
    find_contextual_division_name,
)
from sql_agent.intents import QueryFilters, QueryIntent
from sql_agent.langchain_factory import build_llm
from sql_agent.memory import SqlAgentMemory
from sql_agent.query_utils import (
    RUSSIAN_MONTHS,
    extract_table_name,
    find_table_reference,
    has_invalid_explicit_date,
    has_reversed_explicit_date_range,
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

PURCHASE_UNIT_COST_COLUMNS = {
    "KZT": "unit_cost_kzt",
    "USD": "unit_cost_usd",
    "EUR": "unit_cost_eur",
    "CHF": "unit_cost_chf",
}

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
        "подразделения",
        "подразделению",
        "магазин",
        "магазины",
        "бутик",
        "бутики",
        "точка продаж",
    ),
    "city": ("city", "город", "города"),
}

PRODUCT_DIMENSION_ATTRIBUTE_ALIASES = {
    "product_id": ("product_id", "product id", "sprut", "код спрута"),
    "article": ("article", "артикул", "артикукл"),
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
        "направления бизнеса",
        "направление",
        "направления",
    ),
    "category": ("category", "категория", "категории", "категорий", "категорию"),
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
    "season": ("season", "сезон", "сезона"),
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
    "full_price": ("full_price", "full price", "полная цена"),
    "amount_usd": ("amount_usd", "sales in usd", "выручка в usd", "продажи в usd", "сумма в usd"),
    "amount_eur": ("amount_eur", "sales in eur", "выручка в eur", "продажи в eur", "сумма в eur"),
    "price": ("price", "цена продажи", "sale price"),
    "discount": ("discount", "скидка", "discount amount"),
    "cash": ("cash", "наличные", "cash payment"),
    "card": ("card", "карта", "card payment"),
    "loan": ("loan", "кредит", "loan payment"),
    "certificate": ("certificate", "сертификат"),
    "bonus": ("bonus", "бонус", "bonus payment"),
}

SALES_GROUP_BY_ALIASES = {
    "sale_date": (
        "по дате",
        "по датам",
        "by date",
        "by sale_date",
        "group by sale_date",
        "daily",
    ),
    "product_id": (
        "по товару",
        "по товарам",
        "по product_id",
        "by product",
        "by product_id",
        "group by product_id",
    ),
    "document_number": ("по документам", "by documents", "by document_number"),
    "channel": ("по каналу", "по каналам", "by channel", "by channels"),
    "payment_method": (
        "по способу оплаты",
        "по способам оплаты",
        "by payment method",
        "by payment methods",
    ),
    "partner_id": ("по partner_id", "по партнёрам", "by partner_id", "by partners"),
    "customer_status": (
        "по customer_status",
        "по статусам клиентов",
        "by customer_status",
    ),
    "customer_id": ("по клиенту", "by customer"),
}

UNBOUNDED_WEB_OUTPUT_MESSAGE = (
    "Безлимитный вывод строк в веб-чате отключён: большой результат может "
    "перегрузить браузер. Укажите конечный лимит либо используйте "
    "пагинацию/экспорт."
)


class IntentParser:
    def get_clarification(self, question: str) -> str | None:
        lowered = question.lower()
        if has_invalid_explicit_date(question):
            return (
                "Указана некорректная календарная дата. "
                "Исправьте её в формате YYYY-MM-DD или DD.MM.YYYY."
            )
        if has_reversed_explicit_date_range(question):
            return (
                "Начальная дата периода позже конечной. "
                "Укажите диапазон в хронологическом порядке."
            )
        if re.match(
            r"^\s*(?:insert|update|delete|drop|alter|create|truncate|merge|exec|execute)\b",
            lowered,
        ):
            return "Разрешены только read-only SELECT-запросы."
        numeric_range_pattern = r"-?\d+(?:[.,]\d+)?(?![-.\d])"
        if re.search(
            rf"(?:\bот\b\s*{numeric_range_pattern}\s*(?:%|[A-Za-zА-Яа-яЁё]*)?\s*"
            rf"\bдо\b\s*{numeric_range_pattern}|\bмежду\b\s*{numeric_range_pattern}\s*"
            rf"\bи\b\s*{numeric_range_pattern})",
            question,
            flags=re.IGNORECASE,
        ):
            return (
                "Числовой диапазон с двумя границами пока нельзя применить без "
                "риска потерять одну из границ. Укажите одно пороговое условие."
            )
        if re.search(
            r"\b(?:кроме|без|исключая|не)\s+(?:товар\w*\s+)?"
            r"(?:бренд\w*|артикул\w*|категори\w*|сезон\w*|размер\w*|"
            r"цвет\w*|коллекци\w*|bu\b|buyer\b|байер\w*)",
            lowered,
        ):
            return (
                "Исключающие dimension-фильтры пока не поддерживаются безопасно. "
                "Переформулируйте запрос с положительным фильтром."
            )
        if (
            self._wants_explicit_unbounded_rows(lowered)
            and not is_aggregate_question(question)
        ):
            return UNBOUNDED_WEB_OUTPUT_MESSAGE
        domain = self._detect_domain(question)
        unsupported_currency = self._unsupported_currency(lowered, domain)
        if unsupported_currency:
            return (
                f"В домене {domain} валюта {unsupported_currency} не документирована. "
                "Укажите поддерживаемую валюту или правило пересчёта."
            )
        discount_match = re.search(
            r"(?:скидк\w*|discount(?:\s+of)?)\s*(?:в\s*)?"
            r"(-?\d+(?:[.,]\d+)?)\s*%?",
            question,
            flags=re.IGNORECASE,
        )
        if self._wants_gross_margin(lowered) and discount_match:
            discount_value = float(discount_match.group(1).replace(",", "."))
            if not 0 <= discount_value <= 100:
                return "Скидка для GM должна быть в диапазоне от 0% до 100%."
        mentioned_fact_domains = self._mentioned_fact_domains(lowered)
        explicit_table_domain = self._explicit_table_domain(lowered)
        if explicit_table_domain:
            conflicting_domains = set(mentioned_fact_domains)
            conflicting_domains.discard(explicit_table_domain)
            if conflicting_domains:
                return (
                    "Явно указанная таблица не соответствует остальному смыслу "
                    f"запроса ({explicit_table_domain} против "
                    f"{', '.join(sorted(conflicting_domains))}). Уточните нужный домен."
                )
        if not self._wants_gross_margin(lowered) and len(mentioned_fact_domains) > 1:
            return (
                "Запрос одновременно затрагивает несколько fact-таблиц "
                f"({', '.join(sorted(mentioned_fact_domains))}). Их grain и ключи "
                "соединения не подтверждены документацией; разделите запрос или "
                "уточните документированное правило связи."
            )
        if re.search(r"\bуникальн\w*\s+покупател\w*\b", lowered):
            return (
                "Уточните смысл «покупатель»: buyer/байер из dimension_product "
                "или клиент продажи. В [LLM].[sales] нет customer_name; доступны "
                "partner_id и customer_status."
            )
        if (
            domain == "sales"
            and any(marker in lowered for marker in ("цена продажи", "sale price"))
            and any(marker in lowered for marker in ("usd", "eur", "доллар", "евро"))
        ):
            return (
                "В [LLM].[sales] нет price_usd/price_eur. "
                "Уточните: использовать price без валютного пересчёта или "
                "сумму продаж amount_usd/amount_eur."
            )
        if domain == "product_cost" and re.search(
            r"(?:общ(?:ая|ую|ей)\s+себестоим|total\s+(?:product\s+)?cost)",
            lowered,
            flags=re.IGNORECASE,
        ) and not any(
            marker in lowered
            for marker in ("sum(cost)", "сумма себестоимости операций", "текущ", "cost_sum")
        ):
            return (
                "Уточните смысл «общая себестоимость»: SUM(cost) по операциям "
                "или текущий баланс cost_sum."
            )
        if (
            domain == "product_cost"
            and "средн" in lowered
            and any(marker in lowered for marker in ("себестоим", "себестом", "себес"))
            and not self._wants_current_cost_balance(lowered)
            and not any(
                marker in lowered
                for marker in ("единиц", "cost_per_unit", "взвеш")
            )
        ):
            return (
                "Уточните среднюю себестоимость: AVG(cost_per_unit) по операциям "
                "или взвешенную SUM(cost) / NULLIF(SUM(quantity), 0)."
            )
        if (
            domain == "product_cost"
            and self._extract_dimension_group_by(lowered)
            and self._extract_aggregate_function(lowered) is None
        ):
            return (
                "Для себестоимости в разрезе атрибута укажите метрику: "
                "SUM(cost) операций, AVG(cost_per_unit) или текущий баланс."
            )
        if (
            domain == "stock"
            and self._wants_stock_balance(lowered)
            and self._extract_stock_balance_mode(lowered) == "start"
            and not parse_date_filters(question)
        ):
            return "Для остатка на начало периода укажите дату или период расчёта."
        if (
            domain == "retail_price"
            and self._wants_in_stock_only(question)
            and not self._wants_gross_margin(lowered)
        ):
            return (
                "Фильтр цены по текущему остатку пока не выполняется: прямой "
                "price↔stock join документирован только для расчёта GM."
            )
        if domain in {"sales", "product_cost", "purchases"} and self._wants_in_stock_only(
            question
        ):
            return (
                "Связь stock с sales/cost/purchases для фильтра «в наличии» "
                "не подтверждена документацией. Уточните подтверждённый способ связи."
            )
        if any(marker in lowered for marker in ("клиент", "customer_name")):
            return (
                "В [LLM].[sales] нет customer_name. Уточните доступный идентификатор: "
                "partner_id либо customer_status."
            )
        if domain != "sales":
            return None
        wants_product_ranking = (
            self._extract_group_by(lowered, "sales") == "product_id"
            or (
                self._wants_single_best(lowered)
                and any(marker in lowered for marker in ("товар", "product"))
            )
        )
        if not wants_product_ranking:
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
        if self._wants_preview_sample(lowered) and not self._has_explicit_limit(lowered):
            limit = 10

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
        metric_question = self._without_availability_phrases(question)
        for filter_value in filters.equality_filters.values():
            metric_question = re.sub(
                rf"(?<![A-Za-zА-Яа-яЁё0-9_]){re.escape(filter_value)}"
                r"(?![A-Za-zА-Яа-яЁё0-9_])",
                " ",
                metric_question,
                count=1,
                flags=re.IGNORECASE,
            )
        metric_column = self._extract_metric_column(metric_question, domain)
        wants_distinct_values = self._wants_distinct_values(lowered)
        distinct = wants_distinct_values
        distinct_count_column = self._extract_distinct_count_column(lowered, domain)
        if aggregate_function == "count" and distinct_count_column:
            metric_column = distinct_count_column
            distinct = True
            filters.equality_filters.pop(distinct_count_column, None)
            filters.dimension_filters.pop(distinct_count_column, None)
            filters.dimension_prefix_filters.pop(distinct_count_column, None)
            filters.dimension_contains_filters.pop(distinct_count_column, None)
            filters.dimension_suffix_filters.pop(distinct_count_column, None)
            filters.division_filters.pop(distinct_count_column, None)
            filters.division_prefix_filters.pop(distinct_count_column, None)
            filters.division_contains_filters.pop(distinct_count_column, None)
            filters.division_suffix_filters.pop(distinct_count_column, None)
        if (
            domain == "sales"
            and aggregate_function == "count"
            and self._is_document_count_request(lowered)
        ):
            metric_column = "document_number"
            distinct = True
        elif (
            domain == "sales"
            and aggregate_function == "count"
            and self._is_document_or_row_count_request(lowered)
        ):
            metric_column = None
        group_by = self._extract_group_by(lowered, domain)
        if (
            domain == "stock"
            and group_by is None
            and re.fullmatch(r"\s*остат(?:ок|ки)\s+\d+\s*[?.!]?\s*", lowered)
        ):
            group_by = "warehouse_id"
        if group_by is None and filters.threshold_column:
            group_by = self._infer_threshold_group_by(lowered, domain)
        if group_by and group_by in filters.equality_filters:
            group_by = None
        group_by_columns = self._extract_group_by_columns(lowered, domain, group_by)
        if (
            domain == "product_dimension"
            and group_by in filters.dimension_filters
            and not self._has_explicit_grouping_marker(lowered)
        ):
            group_by = None
            group_by_columns = []
        if wants_distinct_values and aggregate_function != "count":
            group_by = None
            group_by_columns = []
        if group_by and limit is None:
            limit = DEFAULT_PREVIEW_ROWS
        for group_by_column in group_by_columns:
            filters.equality_filters.pop(group_by_column, None)
            if group_by_column in PRODUCT_DIMENSION_ATTRIBUTE_ALIASES:
                filters.dimension_filters.pop(group_by_column, None)
                filters.dimension_prefix_filters.pop(group_by_column, None)
                filters.dimension_contains_filters.pop(group_by_column, None)
                filters.dimension_suffix_filters.pop(group_by_column, None)
            if group_by_column in DIVISION_ATTRIBUTE_ALIASES:
                filters.division_filters.pop(group_by_column, None)
                filters.division_prefix_filters.pop(group_by_column, None)
                filters.division_contains_filters.pop(group_by_column, None)
                filters.division_suffix_filters.pop(group_by_column, None)
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
            metric_column = metric_column or (
                "quantity" if self._is_quantity_metric_request(lowered) else "amount"
            )
        if domain == "sales" and group_by and not aggregate_function:
            aggregate_function = "sum"
            metric_column = metric_column or "amount"
        if domain == "sales" and group_by == "product_id" and self._wants_all_sold_products(lowered):
            aggregate_function = "sum"
            metric_column = "quantity"
            limit = DEFAULT_PREVIEW_ROWS
            if not filters.threshold_column:
                filters.threshold_column = "quantity"
                filters.threshold_operator = ">"
                filters.threshold_value = "0"
        if (
            domain == "sales"
            and aggregate_function == "count"
            and not distinct
            and self._is_quantity_metric_request(lowered)
            and not self._is_document_or_row_count_request(lowered)
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
                sort_column=(
                    "quantity" if self._has_top_limit(lowered) else group_by
                ),
                sort_direction="desc",
            )

        if (
            domain == "product_cost"
            and aggregate_function == "sum"
            and metric_column in {"qnt_sum", "cost_sum"}
        ):
            aggregate_function = None

        if (
            domain == "product_cost"
            and aggregate_function == "avg"
            and self._wants_current_cost_balance(lowered)
        ):
            return QueryIntent(
                operation="select",
                domain=domain,
                database_name=self._default_database_name(domain, table_name),
                schema_name=schema_name or "LLM",
                table_name=table_name or self._table_name(domain),
                requested_columns=["date", "product_id", "qnt_sum", "cost_sum"],
                metric_column="cost_per_unit",
                limit=limit or DEFAULT_PREVIEW_ROWS,
                sort_column="date",
                sort_direction="desc",
                latest_per_identifier=True,
                current_cost_per_unit=True,
                filters=filters,
            )

        if (
            domain == "product_cost"
            and aggregate_function == "avg"
            and "взвеш" in lowered
        ):
            metric_column = "cost_per_unit"

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
                distinct=distinct,
                weighted_cost_per_unit=(
                    domain == "product_cost"
                    and aggregate_function == "avg"
                    and "взвеш" in lowered
                ),
                sort_column=(
                    metric_column
                    if self._has_top_limit(lowered)
                    or self._wants_explicit_metric_sort(lowered)
                    or (
                        domain == "sales"
                        and self._wants_single_best(lowered)
                    )
                    else group_by
                ),
                sort_direction=(
                    "asc"
                    if re.search(
                        r"по\s+возрастан|от\s+(?:меньш|низк)|ascending|\basc\b",
                        lowered,
                    )
                    else "desc"
                ),
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
                    filters.division_prefix_filters.pop(column_name, None)
                    filters.division_contains_filters.pop(column_name, None)
                    filters.division_suffix_filters.pop(column_name, None)
            if limit is None:
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
                    (
                        domain == "retail_price"
                        and bool(
                            filters.identifier_values
                            or filters.dimension_filters
                            or filters.dimension_prefix_filters
                            or filters.dimension_contains_filters
                            or filters.dimension_suffix_filters
                        )
                        and (self._wants_latest_price(lowered) or bool(filters.date_eq))
                        and not (
                            limit > 1 and self._has_explicit_limit(lowered)
                        )
                    )
                    or (
                        domain == "product_cost"
                        and self._wants_current_cost_balance(lowered)
                        and not (
                            limit > 1 and self._has_explicit_limit(lowered)
                        )
                        and not any(
                            marker in lowered
                            for marker in (
                                "операци",
                                "operation",
                                "истори",
                                "history",
                            )
                        )
                    )
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
        product_id_match = re.search(
            r"\bproduct_id\b\s*(?:=|:|№|#|-)?\s*((?:\d+[\s,;]*)+)",
            question,
            flags=re.IGNORECASE,
        )
        if product_id_match:
            product_ids = re.findall(r"\d+", product_id_match.group(1))
            filters.identifier_values = product_ids
            filters.identifier_value = product_ids[0]
        margin_threshold = parse_numeric_threshold(question)
        if margin_threshold:
            filters.threshold_column = "gross_margin_percent"
            filters.threshold_operator = margin_threshold[0]
            filters.threshold_value = margin_threshold[1]
        limit = parse_requested_limit(question) or DEFAULT_PREVIEW_ROWS
        lowest_ranking = bool(
            re.search(r"минимальн\w*|наименьш\w*|сам\w*\s+низк\w*", lowered)
        )
        highest_ranking = bool(
            re.search(
                r"(?:\bтоп\b|\btop\b|сам\w*\s+маржинальн\w*|"
                r"сам\w*\s+высок\w*|максимальн\w*)",
                lowered,
            )
        )
        if (
            parse_requested_limit(question) == DEFAULT_PREVIEW_ROWS
            and re.search(
                r"сам\w*\s+(?:маржинальн\w*|высок\w*|низк\w*)|"
                r"(?:максимальн\w*|минимальн\w*)\s+марж\w*",
                lowered,
            )
        ):
            limit = 1
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
            sort_column=(
                "gross_margin_percent"
                if highest_ranking or lowest_ranking
                else None
            ),
            sort_direction="asc" if lowest_ranking else "desc",
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

        supported_domains = {
            "retail_price",
            "sales",
            "product_cost",
            "stock",
            "purchases",
            "product_dimension",
            "division_dimension",
        }
        domain = str(payload.get("domain") or "retail_price")
        if domain not in supported_domains:
            return None
        if operation == "stock_balance":
            domain = "stock"
        elif operation == "gross_margin":
            domain = "retail_price"

        domain_columns = set(self._domain_columns(domain))
        allowed_columns = set(domain_columns)
        if domain in {
            "sales",
            "retail_price",
            "product_cost",
            "stock",
            "purchases",
        }:
            allowed_columns.update(PRODUCT_DIMENSION_COLUMNS)
        if domain == "sales":
            allowed_columns.update(DIVISION_COLUMNS)
            allowed_columns.update({"amount_usd", "amount_eur"})
        if domain == "purchases":
            allowed_columns.update(PURCHASE_UNIT_COST_COLUMNS.values())

        filters_payload = payload.get("filters") or {}
        if not isinstance(filters_payload, dict):
            return None
        identifier_values = filters_payload.get("identifier_values") or []
        if not isinstance(identifier_values, list):
            identifier_values = []
        identifier_values = [
            str(value)
            for value in identifier_values[:100]
            if self._is_safe_payload_value(value)
        ]
        identifier_value = filters_payload.get("identifier_value")
        if not self._is_safe_payload_value(identifier_value):
            identifier_value = None
        elif identifier_value is not None:
            identifier_value = str(identifier_value)
        threshold_operator = str(filters_payload.get("threshold_operator") or "")
        if threshold_operator not in {"=", ">", "<", ">=", "<="}:
            threshold_operator = None
        threshold_value = filters_payload.get("threshold_value")
        threshold_value = str(threshold_value) if threshold_value is not None else None
        if threshold_value and not re.fullmatch(r"-?\d+(?:\.\d+)?", threshold_value):
            threshold_value = None
            threshold_operator = None
        threshold_column = filters_payload.get("threshold_column")
        if threshold_column not in domain_columns:
            threshold_column = None

        filters = QueryFilters(
            date_column=self._date_column(domain),
            date_eq=self._safe_payload_date(filters_payload.get("date_eq")),
            date_from=self._safe_payload_date(filters_payload.get("date_from")),
            date_to=self._safe_payload_date(filters_payload.get("date_to")),
            identifier_column=self._identifier_column(domain),
            identifier_value=identifier_value,
            identifier_values=identifier_values,
            threshold_column=threshold_column,
            threshold_operator=threshold_operator,
            threshold_value=threshold_value,
            equality_filters=self._safe_payload_filter_map(
                filters_payload.get("equality_filters"),
                domain_columns,
            ),
            dimension_filters=(
                self._safe_payload_filter_map(
                    filters_payload.get("dimension_filters"),
                    set(PRODUCT_DIMENSION_COLUMNS),
                    allow_lists=True,
                )
                if domain
                in {
                    "sales",
                    "retail_price",
                    "product_cost",
                    "stock",
                    "purchases",
                    "product_dimension",
                }
                else {}
            ),
            dimension_prefix_filters=(
                self._safe_payload_filter_map(
                    filters_payload.get("dimension_prefix_filters"),
                    set(PRODUCT_DIMENSION_COLUMNS),
                )
                if domain
                in {
                    "sales",
                    "retail_price",
                    "product_cost",
                    "stock",
                    "purchases",
                    "product_dimension",
                }
                else {}
            ),
            dimension_contains_filters=(
                self._safe_payload_filter_map(
                    filters_payload.get("dimension_contains_filters"),
                    set(PRODUCT_DIMENSION_COLUMNS),
                )
                if domain
                in {
                    "sales",
                    "retail_price",
                    "product_cost",
                    "stock",
                    "purchases",
                    "product_dimension",
                }
                else {}
            ),
            dimension_suffix_filters=(
                self._safe_payload_filter_map(
                    filters_payload.get("dimension_suffix_filters"),
                    set(PRODUCT_DIMENSION_COLUMNS),
                )
                if domain
                in {
                    "sales",
                    "retail_price",
                    "product_cost",
                    "stock",
                    "purchases",
                    "product_dimension",
                }
                else {}
            ),
            division_filters=(
                self._safe_payload_filter_map(
                    filters_payload.get("division_filters"),
                    set(DIVISION_COLUMNS),
                )
                if domain in {"sales", "division_dimension"}
                else {}
            ),
            division_prefix_filters=(
                self._safe_payload_filter_map(
                    filters_payload.get("division_prefix_filters"),
                    set(DIVISION_COLUMNS),
                )
                if domain in {"sales", "division_dimension"}
                else {}
            ),
            division_contains_filters=(
                self._safe_payload_filter_map(
                    filters_payload.get("division_contains_filters"),
                    set(DIVISION_COLUMNS),
                )
                if domain in {"sales", "division_dimension"}
                else {}
            ),
            division_suffix_filters=(
                self._safe_payload_filter_map(
                    filters_payload.get("division_suffix_filters"),
                    set(DIVISION_COLUMNS),
                )
                if domain in {"sales", "division_dimension"}
                else {}
            ),
            in_stock_only=self._safe_payload_bool(
                filters_payload.get("in_stock_only")
            ),
        )

        limit = payload.get("limit")
        if limit is not None:
            try:
                limit = max(1, min(int(limit), DEFAULT_PREVIEW_ROWS))
            except (TypeError, ValueError):
                limit = DEFAULT_PREVIEW_ROWS

        requested_columns = payload.get("requested_columns") or []
        if not isinstance(requested_columns, list):
            requested_columns = []
        requested_columns = [
            str(item) for item in requested_columns if str(item) in allowed_columns
        ]

        metric_column = payload.get("metric_column")
        if metric_column not in allowed_columns:
            metric_column = None
        aggregate_function = payload.get("aggregate_function")
        if aggregate_function is not None:
            aggregate_function = str(aggregate_function).lower()
        if aggregate_function not in {None, "sum", "count", "max", "min", "avg"}:
            return None
        if operation == "aggregate":
            if aggregate_function is None:
                return None
            if aggregate_function != "count" and not metric_column:
                return None
            if (
                aggregate_function != "count"
                and not self._is_allowed_payload_aggregate_metric(
                    domain,
                    aggregate_function,
                    metric_column,
                )
            ):
                return None
        if filters.threshold_column and filters.threshold_operator and filters.threshold_value:
            if operation == "aggregate" and (
                filters.threshold_column != metric_column
                or not self._is_allowed_payload_aggregate_metric(
                    domain,
                    aggregate_function,
                    filters.threshold_column,
                )
            ):
                return None
            if operation == "stock_balance" and filters.threshold_column != "quantity":
                return None

        group_by = payload.get("group_by")
        if group_by not in allowed_columns:
            group_by = None
        group_by_columns_payload = payload.get("group_by_columns") or []
        if not isinstance(group_by_columns_payload, list):
            group_by_columns_payload = []
        group_by_columns = [
            str(item)
            for item in group_by_columns_payload
            if str(item) in allowed_columns
        ]
        sort_column = payload.get("sort_column")
        if sort_column not in allowed_columns:
            sort_column = None
        sort_direction = str(payload.get("sort_direction") or "desc").lower()
        if sort_direction not in {"asc", "desc"}:
            sort_direction = "desc"
        balance_mode = payload.get("balance_mode")
        if balance_mode not in {None, "start", "end", "period"}:
            balance_mode = None
        if limit is None and (
            operation in {"select", "stock_balance", "gross_margin"}
            or group_by
            or group_by_columns
        ):
            limit = DEFAULT_PREVIEW_ROWS
        discount_percent = payload.get("discount_percent")
        try:
            discount_percent = (
                float(discount_percent) if discount_percent is not None else None
            )
        except (TypeError, ValueError):
            discount_percent = None
        if discount_percent is not None and not 0 <= discount_percent <= 100:
            discount_percent = None
        if (
            domain == "sales"
            and filters.identifier_value
            and not str(filters.identifier_value).isdigit()
        ):
            filters.identifier_value = None
            filters.identifier_values = []

        return QueryIntent(
            operation=operation,
            domain=domain,
            database_name=self._database_name(domain),
            schema_name="LLM",
            table_name=self._table_name(domain),
            requested_columns=requested_columns,
            metric_column=metric_column,
            aggregate_function=aggregate_function,
            group_by=group_by,
            group_by_columns=group_by_columns,
            balance_mode=balance_mode,
            discount_percent=discount_percent,
            limit=limit,
            sort_column=sort_column,
            sort_direction=sort_direction,
            latest_per_identifier=(
                domain == "retail_price"
                and self._safe_payload_bool(payload.get("latest_per_identifier"))
            ),
            distinct=self._safe_payload_bool(payload.get("distinct")),
            filters=filters,
        )

    def _safe_payload_date(self, value) -> str | None:
        if not isinstance(value, str):
            return None
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            return None

    def _is_safe_payload_value(self, value) -> bool:
        if value is None:
            return True
        return isinstance(value, (str, int, float)) and len(str(value)) <= 200

    def _safe_payload_bool(self, value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def _safe_payload_filter_map(
        self,
        value,
        allowed_columns: set[str],
        *,
        allow_lists: bool = False,
    ) -> dict:
        if not isinstance(value, dict):
            return {}
        result = {}
        for column_name, filter_value in value.items():
            if column_name not in allowed_columns:
                continue
            if allow_lists and isinstance(filter_value, list):
                safe_values = [
                    str(item)
                    for item in filter_value[:100]
                    if self._is_safe_payload_value(item)
                ]
                if safe_values:
                    result[column_name] = safe_values
            elif self._is_safe_payload_value(filter_value) and filter_value is not None:
                result[column_name] = str(filter_value)
        return result

    def _is_allowed_payload_aggregate_metric(
        self,
        domain: str,
        aggregate_function: str | None,
        metric_column: str | None,
    ) -> bool:
        if not metric_column or aggregate_function not in {"sum", "avg", "min", "max"}:
            return False
        additive_metrics = {
            "sales": {
                "quantity",
                "full_price",
                "amount",
                "amount_usd",
                "amount_eur",
                "loan",
                "cash",
                "card",
                "certificate",
                "bonus",
                "discount",
            },
            "product_cost": {"quantity", "cost"},
            "stock": {"quantity"},
            "purchases": {
                "quantity",
                "amount_kzt",
                "NDS_kzt",
                "amount_usd",
                "NDS_usd",
                "amount_eur",
                "NDS_eur",
                "amount_chf",
                "NDS_chf",
            },
        }
        numeric_metrics = {
            "retail_price": {
                "full_retail_price_kzt",
                "full_retail_price_eur",
                "full_retail_price_usd",
            },
            "sales": additive_metrics["sales"] | {"price"},
            "product_cost": {"quantity", "cost", "cost_per_unit"},
            "stock": {"quantity"},
            "purchases": additive_metrics["purchases"]
            | set(PURCHASE_UNIT_COST_COLUMNS.values()),
        }
        if aggregate_function == "sum":
            return metric_column in additive_metrics.get(domain, set())
        return metric_column in numeric_metrics.get(domain, set())

    def _detect_domain(self, question: str) -> str:
        lowered = self._without_availability_phrases(question).lower()
        explicit_table_domain = self._explicit_table_domain(lowered)
        if explicit_table_domain:
            return explicit_table_domain
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
        if re.search(r"\bdivision\b", lowered) and not any(
            marker in lowered for marker in ("sales", "sale", "продаж")
        ):
            return "division_dimension"
        explicit_stock_markers = (
            "dwh.llm.stock",
            "[dwh].[llm].[stock]",
            "llm.stock",
            "таблица stock",
        )
        if any(marker in lowered for marker in explicit_stock_markers) or re.search(
            r"(?:движени[еяй]*\s+(?:по\s+)?склад|stock\s+movements?)",
            lowered,
            flags=re.IGNORECASE,
        ):
            return "stock"
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
            "дополнительн",
            "поступление товаров и услуг",
            "purchase",
            "purchases",
            "procurement",
            "supplier return",
            "amount_kzt",
            "nds_kzt",
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
            "списан",
            "поступление",
        )
        if any(marker in lowered for marker in stock_markers):
            return "stock"
        explicit_product_dimension_markers = (
            "dwh.llm.dimension_product",
            "[dwh].[llm].[dimension_product]",
            "llm.dimension_product",
            "dimension_product",
            "product dimension",
            "product dictionary",
            "product attributes",
            "product master",
            "справочник товаров",
            "справочник товара",
            "карточк",
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
            "sold",
            "return",
            "возврат",
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
            "кредит",
            "бонус",
            "сертификат",
            "certificate",
            "скид",
            "full_price",
            "полная цена",
        )
        if any(marker in lowered for marker in sales_markers) or re.search(
            r"\bкарт(?:а|ы|е|у|ой|ою|ами|ах)\b",
            lowered,
        ):
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
        if any(marker in lowered for marker in ("магазин", "бутик", "точка продаж", "подразделен", "город", "city")):
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
            recorder_type_markers = (
                ("Перемещение товаров", ("перемещен",)),
                ("ввод_остатков", ("ввод остатков", "ввод_остатков")),
                ("Списание товаров", ("списан",)),
                (
                    "Поступление товаров и услуг",
                    (
                        "поступление товаров и услуг",
                        "поступления товаров и услуг",
                    ),
                ),
                (
                    "Реализация товаров и услуг",
                    ("реализация товаров и услуг", "реализацию товаров и услуг"),
                ),
            )
            for recorder_type, markers in recorder_type_markers:
                if any(marker in lowered for marker in markers):
                    filters.equality_filters["recorder_type"] = recorder_type
                    break
            warehouse_match = re.search(
                r"(?:по\s+)?(?:складом|складу|склада|склад)\b\s*[=:№#-]?\s*"
                r"([A-Za-zА-Яа-яЁё0-9_.-]+)",
                question,
                flags=re.IGNORECASE,
            )
            if warehouse_match and not warehouse_match.group(1).lower().startswith("ам"):
                filters.equality_filters["warehouse_id"] = warehouse_match.group(1)
            document_match = re.search(
                r"(?:document_id|номер(?:у)?\s+документа|по\s+документу)\s*"
                r"[=:№#-]?\s*([A-Za-zА-Яа-яЁё0-9_.-]+)",
                question,
                flags=re.IGNORECASE,
            )
            if document_match:
                filters.equality_filters["document_id"] = document_match.group(1)

        if domain == "purchases":
            lowered = question.lower()
            recorder_type_markers = (
                ("Возврат товаров поставщику", ("возврат", "поставщик")),
                ("ГТД по импорту", ("гтд",)),
                (
                    "Поступление доп. расходов",
                    ("доп. расход", "доп расход", "дополнительн"),
                ),
                ("Поступление товаров и услуг", ("поступление товаров и услуг",)),
            )
            for recorder_type, markers in recorder_type_markers:
                if (
                    recorder_type == "Возврат товаров поставщику"
                    and all(marker in lowered for marker in markers)
                ) or (
                    recorder_type != "Возврат товаров поставщику"
                    and any(marker in lowered for marker in markers)
                ):
                    filters.equality_filters["recorder_type"] = recorder_type
                    break
            recorder_match = re.search(
                r"(?:recorder_number|номер(?:у)?\s+документа|по\s+документу)\s*"
                r"[=:№#-]?\s*([A-Za-zА-Яа-яЁё0-9_.-]+)",
                question,
                flags=re.IGNORECASE,
            )
            if recorder_match:
                filters.equality_filters["recorder_number"] = recorder_match.group(1)
            division_match = re.search(
                r"(?:division_id|подразделению|подразделения|подразделение)\b"
                r"\s*[=:№#-]?\s*"
                r"([A-Za-zА-Яа-яЁё0-9_.-]+)",
                question,
                flags=re.IGNORECASE,
            )
            if division_match:
                filters.equality_filters["division_id"] = division_match.group(1)

        if domain == "retail_price":
            rank_match = re.search(
                r"(?:_rank|ранг(?:ом|а|у)?|rank)\s*[=:№#-]?\s*(\d+)",
                question,
                flags=re.IGNORECASE,
            )
            if rank_match:
                filters.equality_filters["_RANK"] = rank_match.group(1)

        if domain == "sales":
            if (
                re.search(r"\b(?:возврат\w*|returns?)\b", question, flags=re.IGNORECASE)
                and not filters.threshold_column
            ):
                filters.threshold_column = "quantity"
                filters.threshold_operator = "<"
                filters.threshold_value = "0"
            division_id_match = re.search(
                r"division_id\s*[=:№#-]?\s*([A-Za-zА-Яа-яЁё0-9_.-]+)",
                question,
                flags=re.IGNORECASE,
            )
            if division_id_match:
                filters.equality_filters["division_id"] = division_id_match.group(1)
            sales_filter_patterns = {
                "document_number": (
                    r"(?:document_number|по\s+документу|документ(?:у|а)?)\b"
                    r"\s*[=:№#-]?\s*([A-Za-zА-Яа-яЁё0-9_.-]+)"
                ),
                "channel": (
                    r"(?:канал(?:а|у)?|channel)\b\s*[=:№#-]?\s*"
                    r"([A-Za-zА-Яа-яЁё0-9_.-]+)"
                ),
                "payment_method": (
                    r"(?:способ(?:у)?\s+оплаты|payment_method)\b\s*[=:№#-]?\s*"
                    r"([A-Za-zА-Яа-яЁё0-9_.-]+)"
                ),
                "partner_id": (
                    r"partner_id\b\s*[=:№#-]?\s*([A-Za-zА-Яа-яЁё0-9_.-]+)"
                ),
                "customer_status": (
                    r"customer_status\b\s*[=:№#-]?\s*"
                    r"([A-Za-zА-Яа-яЁё0-9_.-]+)"
                ),
            }
            for column_name, pattern in sales_filter_patterns.items():
                match = re.search(pattern, question, flags=re.IGNORECASE)
                if not match:
                    continue
                filter_value = match.group(1)
                if filter_value.lower() in {
                    "и",
                    "and",
                    "by",
                    "for",
                    "за",
                    "на",
                    "с",
                    "со",
                    "по",
                    "где",
                    "where",
                    "group",
                    "order",
                }:
                    continue
                filters.equality_filters[column_name] = filter_value

        filters.dimension_filters = self._extract_dimension_filters(filter_question, domain)
        filters.dimension_prefix_filters = self._extract_dimension_prefix_filters(
            filter_question,
            domain,
        )
        filters.dimension_contains_filters = self._extract_dimension_contains_filters(
            filter_question,
            domain,
        )
        filters.dimension_suffix_filters = self._extract_dimension_suffix_filters(
            filter_question,
            domain,
        )
        for column_name in (
            filters.dimension_prefix_filters
            | filters.dimension_contains_filters
            | filters.dimension_suffix_filters
        ):
            filters.dimension_filters.pop(column_name, None)
        filters.division_filters = self._extract_division_filters(question, domain)
        filters.division_prefix_filters = self._extract_division_like_filters(
            question,
            domain,
            r"(?:начина\w*(?:\s+(?:с|на))?|starts?\s+with|begins?\s+with)",
        )
        filters.division_contains_filters = self._extract_division_like_filters(
            question,
            domain,
            r"(?:содерж\w*|contain(?:s|ing)?|includes?|including)",
        )
        filters.division_suffix_filters = self._extract_division_like_filters(
            question,
            domain,
            r"(?:(?:заканчива|оканчива)\w*(?:\s+(?:на|с))?|ends?\s+with)",
        )
        for column_name in (
            filters.division_prefix_filters
            | filters.division_contains_filters
            | filters.division_suffix_filters
        ):
            filters.division_filters.pop(column_name, None)
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
                filters[column_name] = (
                    canonicalize_division_name(value)
                    if column_name == "division"
                    else value
                )
        known_division = find_contextual_division_name(question)
        if known_division:
            filters["division"] = known_division
        return filters

    def _extract_division_like_filters(
        self,
        question: str,
        domain: str,
        relation_pattern: str,
    ) -> dict[str, str]:
        if domain not in {"sales", "division_dimension"}:
            return {}

        filters: dict[str, str] = {}
        for column_name, aliases in DIVISION_ATTRIBUTE_ALIASES.items():
            for alias in sorted(aliases, key=len, reverse=True):
                pattern = (
                    re.escape(alias)
                    + r"(?:ами|ями|ах|ях|ов|ев|ей|ом|ем|ам|ям|ы|и|у|а|е)?"
                    r"\s*,?\s*(?:(?:котор\w*|что)\s+)?"
                    + relation_pattern
                    + r"\s+"
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
            if column_name == "product" and re.search(
                r"\bproduct\s+(?:attributes?|details?)\b",
                question,
                flags=re.IGNORECASE,
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
        return self._extract_dimension_like_filters(
            question,
            domain,
            r"(?:начина\w*(?:\s+(?:с|на))?|starts?\s+with|begins?\s+with)",
        )

    def _extract_dimension_contains_filters(
        self,
        question: str,
        domain: str,
    ) -> dict[str, str]:
        return self._extract_dimension_like_filters(
            question,
            domain,
            r"(?:содерж\w*|contain(?:s|ing)?|includes?|including)",
        )

    def _extract_dimension_suffix_filters(
        self,
        question: str,
        domain: str,
    ) -> dict[str, str]:
        return self._extract_dimension_like_filters(
            question,
            domain,
            r"(?:(?:заканчива|оканчива)\w*(?:\s+(?:на|с))?|ends?\s+with)",
        )

    def _extract_dimension_like_filters(
        self,
        question: str,
        domain: str,
        relation_pattern: str,
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
                    + r"(?:ами|ями|ах|ях|ов|ев|ей|ом|ем|ам|ям|ы|и|у|а|е)?"
                    r"\s*,?\s*(?:(?:котор\w*|что)\s+)?"
                    + relation_pattern
                    + r"\s+"
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
                + r"(?<![A-Za-zА-Яа-яЁё0-9_])"
                + re.escape(alias)
                + r"(?:ами|ями|ах|ях|ам|ям|ов|ев|ей|ом|ем|у|а|е)?"
                + r"(?=\s|=|:|№|#|$)\s*(?:=|:|№|#)?\s*"
                r"(?:"
                r'"([^"]+)"'
                r"|'([^']+)'"
                r"|«([^»]+)»"
                r"|([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9_./&,'()\- ]*)"
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
                r"^(?:(?:товар|product)[A-Za-zА-Яа-яЁё]*|и|and|by|for|за|на|с|по|у|из|from|для|где|where|order|sort|разбивка)\b",
                value,
                flags=re.IGNORECASE,
            ):
                continue
            if matched_group_index < 3:
                return [value]
            other_attribute_aliases = sorted(
                {
                    attribute_alias
                    for attribute_aliases in PRODUCT_DIMENSION_ATTRIBUTE_ALIASES.values()
                    for attribute_alias in attribute_aliases
                    if attribute_alias not in aliases
                },
                key=len,
                reverse=True,
            )
            attribute_boundary = "|".join(
                re.escape(attribute_alias)
                for attribute_alias in other_attribute_aliases
            )
            division_boundary = "|".join(
                re.escape(attribute_alias)
                for aliases_for_column in DIVISION_ATTRIBUTE_ALIASES.values()
                for attribute_alias in aliases_for_column
            )
            russian_month_boundary = "|".join(
                re.escape(month_name) for month_name in RUSSIAN_MONTHS
            )
            value = re.split(
                r"\s+(?:(?:за|на|с|со|по|при|в|во|до|после|позже|раньше|"
                r"где|where|order|sort|разбивка)\s+"
                r"|(?:группировк\w*|сгруппиров\w*|первые|первых|последние|"
                r"последних|top|топ|limit|типа|recorder_type|вчера|сегодня)\b"
                r"|(?:без\s+(?:лимита|топа?|ограничени\w*)|no\s+limit)\b"
                + rf"|(?=(?:{russian_month_boundary})\b)"
                r"|(?=(?:usd|eur|chf|kzt|доллар\w*|евро|тенге|франк\w*)\b)"
                + rf"|(?=(?:{attribute_boundary})(?:ами|ями|ах|ях|ам|ям|ов|ев|ей|ом|ем|у|а|е)?(?=\s|=|:|№|#|$))"
                + rf"|(?=(?:{division_boundary})(?:ами|ями|ах|ях|ам|ям|ов|ев|ей|ом|ем|у|а|е)?(?=\s|=|:|№|#|$)))",
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" .,:;")
            if value:
                values: list[str] = []
                for item in re.split(r"\s*(?:,|;|\bи\b|\band\b)\s*", value, flags=re.IGNORECASE):
                    cleaned_item = item.strip(" .,:;")
                    if not cleaned_item:
                        continue
                    if re.match(
                        rf"^(?:{attribute_boundary}|{division_boundary})"
                        r"(?:ами|ями|ах|ях|ам|ям|ов|ев|ей|ом|ем|у|а|е)?(?:\s|=|:|№|#|$)",
                        cleaned_item,
                        flags=re.IGNORECASE,
                    ):
                        break
                    if re.match(
                        r"^(?:in|from|where|order|sort|group|за|на|с|со|по|при|"
                        r"в|во|до|после|где|группировк|типа|recorder_type)\b",
                        cleaned_item,
                        flags=re.IGNORECASE,
                    ):
                        break
                    values.append(cleaned_item)
                return values
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
            r"product_id\s*(?:=|:|in)?\s*\(?\s*([0-9][0-9,\s;]*(?:(?:\bи\b|\band\b)[0-9,\s;]+)*)",
            r"(?:товар[а-яё]*|для\s+товара|у\s+товара)\s+([0-9][0-9,\s;]*(?:(?:\bи\b|\band\b)[0-9,\s;]+)*)",
            r"(?:код(?:ом)?\s+спрута|спрут(?:а|у)?|sprut(?:\s+code)?)\s*[#:№=\-]?\s*([0-9][0-9,\s;]*(?:(?:\bи\b|\band\b)[0-9,\s;]+)*)",
            r"product\s+([0-9][0-9,\s;]*(?:(?:\bи\b|\band\b)[0-9,\s;]+)*)",
        ]
        if domain == "stock":
            patterns.insert(
                0,
                r"\bостат(?:ок|ки)\s+([0-9][0-9,\s;]*(?:(?:\bи\b|\band\b)[0-9,\s;]+)*)",
            )
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
            if any(
                marker in lowered
                for marker in (
                    "за единиц",
                    "на единиц",
                    "стоимость единиц",
                    "unit cost",
                    "per unit",
                )
            ):
                if "usd" in lowered or "доллар" in lowered:
                    return PURCHASE_UNIT_COST_COLUMNS["USD"]
                if "eur" in lowered or "евро" in lowered:
                    return PURCHASE_UNIT_COST_COLUMNS["EUR"]
                if "chf" in lowered or "франк" in lowered:
                    return PURCHASE_UNIT_COST_COLUMNS["CHF"]
                return PURCHASE_UNIT_COST_COLUMNS["KZT"]
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

        if any(marker in lowered for marker in ("full_price", "full price", "полная цена")):
            return "full_price"
        if any(marker in lowered for marker in ("цена продажи", "sale price")):
            return "price"
        if "discount" in lowered or "скид" in lowered:
            return "discount"
        if "certificate" in lowered or "сертификат" in lowered:
            return "certificate"

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
        if re.search(r"\bкарт(?:а|ы|е|у|ой|ою|ами|ах)\b", lowered):
            return "card"
        payment_aliases = {
            "cash": ("cash", "налич", "наличн"),
            "card": ("card",),
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
        if any(
            marker in lowered
            for marker in ("сумм", "sum", "итого", "выручк", "оборот")
        ):
            return "sum"
        if any(marker in lowered for marker in ("сколько", "count", "количество")):
            return "count"
        return None

    def _extract_group_by(self, lowered: str, domain: str) -> str | None:
        if domain in {"sales", "division_dimension"}:
            division_group_by = self._extract_division_group_by(lowered)
            if division_group_by:
                return division_group_by
        if domain in {"sales", "retail_price", "product_cost", "stock", "purchases"}:
            dimension_group_by = self._extract_dimension_group_by(lowered)
            if dimension_group_by:
                return dimension_group_by
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
                    "по product_id",
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
            if self._has_top_limit(lowered) and any(
                marker in lowered for marker in ("товар", "product")
            ):
                return "product_id"
            if self._has_top_limit(lowered) and any(
                marker in lowered for marker in ("склад", "warehouse")
            ):
                return "warehouse_id"
            return None
        if domain == "product_cost":
            aliases = {
                "date": ("по дате", "по датам", "by date"),
                "product_id": (
                    "по товару",
                    "по товарам",
                    "по product_id",
                    "by product",
                    "by product_id",
                ),
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
                "product_id": (
                    "по товару",
                    "по товарам",
                    "по product_id",
                    "by product",
                    "by product_id",
                ),
                "recorder_type": ("по операц", "по типу", "by operation"),
                "recorder_number": ("по документ", "by document"),
                "division_id": ("по подраздел", "by division"),
                "source_database": ("по базе", "по источнику", "by source"),
            }
            for group_by, markers in aliases.items():
                if any(marker in lowered for marker in markers):
                    return group_by
            if self._has_top_limit(lowered):
                if "подраздел" in lowered or "division" in lowered:
                    return "division_id"
                if any(
                    marker in lowered
                    for marker in ("тип операц", "операци", "operation type")
                ):
                    return "recorder_type"
                if "товар" in lowered or "product" in lowered:
                    return "product_id"
            return None
        if domain == "sales":
            dimension_group_by = self._extract_dimension_group_by(lowered)
            if dimension_group_by:
                return dimension_group_by
            for group_by, aliases in SALES_GROUP_BY_ALIASES.items():
                if any(alias in lowered for alias in aliases):
                    return group_by
            if self._wants_sales_ranking(lowered) and any(
                marker in lowered for marker in ("товар", "product")
            ):
                return "product_id"
            if self._wants_sales_ranking(lowered) and any(
                marker in lowered for marker in ("бренд", "brand", "марк")
            ):
                return "brand"
            if self._has_top_limit(lowered):
                if "город" in lowered or "city" in lowered:
                    return "city"
                if any(
                    marker in lowered
                    for marker in ("магазин", "бутик", "подраздел", "division")
                ):
                    return "division"
            if self._wants_single_best(lowered) and any(
                marker in lowered for marker in ("товар", "product")
            ):
                return "product_id"
            if self._wants_all_sold_products(lowered):
                return "product_id"
            return None

        if domain in {"retail_price", "product_cost", "stock", "purchases"}:
            dimension_group_by = self._extract_dimension_group_by(lowered)
            if dimension_group_by:
                return dimension_group_by

        if domain == "retail_price" and self._has_top_limit(lowered):
            for column_name, markers in (
                ("brand", ("бренд", "brand", "марк")),
                ("category", ("категор", "category")),
                ("article", ("артикул", "article")),
            ):
                if any(marker in lowered for marker in markers):
                    return column_name

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
            positions = []
            for candidate in candidates:
                if candidate.isascii():
                    match = re.search(
                        rf"(?<![A-Za-z0-9_]){re.escape(candidate)}(?![A-Za-z0-9_])",
                        grouping_text,
                    )
                    if match:
                        positions.append(match.start())
                elif candidate in grouping_text:
                    positions.append(grouping_text.find(candidate))
            if positions:
                matches.append((min(positions), column_name))

        native_group_columns = {
            "sales": (
                "sale_date",
                "product_id",
                "channel",
                "payment_method",
                "division",
                "city",
            ),
            "stock": (
                "date",
                "product_id",
                "warehouse_id",
                "recorder_type",
                "document_id",
                "source_database",
            ),
            "product_cost": ("date", "product_id", "op_type", "db"),
            "purchases": (
                "purchase_date",
                "product_id",
                "recorder_type",
                "recorder_number",
                "division_id",
                "source_database",
            ),
        }
        for column_name in native_group_columns.get(domain, ()):
            match = re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(column_name)}(?![A-Za-z0-9_])",
                grouping_text,
            )
            if match:
                matches.append((match.start(), column_name))

        for _, column_name in sorted(matches):
            if column_name not in columns:
                columns.append(column_name)
        return columns

    def _has_explicit_grouping_marker(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in (
                "группировка по ",
                "группировкой по ",
                "сгруппировать по ",
                "в разрезе ",
                "group by ",
                "grouped by ",
                "breakdown by ",
            )
        )

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
        plural_shortcuts = {
            "brand": ("по брендам", "по маркам", "by brands"),
            "article": ("по артикулам", "by articles"),
            "category": ("по категориям", "by categories"),
            "season": ("по сезонам", "by seasons"),
            "common_size": ("по размерам", "by sizes"),
            "collection_jw": ("по коллекциям", "by collections"),
            "bu": (
                "по bu",
                "по направлениям",
                "по бизнес-направлениям",
                "by business unit",
            ),
        }
        for column_name, markers in plural_shortcuts.items():
            if any(marker in lowered for marker in markers):
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
        if re.search(
            r"\b(?:top|топ|limit)(?:\s*[-–—]\s*|\s+)\d+\b",
            lowered,
            flags=re.IGNORECASE,
        ):
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
            re.search(
                r"\b(?:top|limit)(?:\s*[-–—]\s*|\s+)\d+\b",
                lowered,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"(?:^|\s)топ(?:\s*[-–—]\s*|\s+)\d+\b",
                lowered,
                flags=re.IGNORECASE,
            )
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

    def _has_top_limit(self, lowered: str) -> bool:
        return bool(
            re.search(
                r"\b(?:top|топ|limit)(?:\s*[-–—]\s*|\s+)(\d+)\b",
                lowered,
                flags=re.IGNORECASE,
            )
        )

    def _wants_explicit_metric_sort(self, lowered: str) -> bool:
        return bool(
            re.search(
                r"(?:сортир\w*|упорядоч\w*)\s+(?:по\s+)?"
                r"(?:сумм\w*|выручк\w*|оборот\w*|количеств\w*|метрик\w*)"
                r"|по\s+(?:убыван|возрастан)"
                r"|от\s+(?:больш|высок|меньш|низк)\w*\s+к\s+"
                r"(?:больш|высок|меньш|низк)\w*",
                lowered,
            )
        )

    def _wants_all_sold_products(self, lowered: str) -> bool:
        if re.search(
            r"(?:все\s+(?:продан\w*\s+)?товар\w*|all\s+sold\s+products?)",
            lowered,
        ):
            return any(
                marker in lowered for marker in ("продан", "продав", "sold")
            )
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

    def _is_document_count_request(self, lowered: str) -> bool:
        return bool(
            re.search(
                r"(?:количеств|сколько|count).{0,40}(?:документ|documents?)"
                r"|(?:документ|documents?).{0,40}(?:количеств|сколько|count)",
                lowered,
                flags=re.IGNORECASE,
            )
        )

    def _is_document_or_row_count_request(self, lowered: str) -> bool:
        return self._is_document_count_request(lowered) or bool(
            re.search(r"\b(?:строк[аи]?|rows?)\b", lowered, flags=re.IGNORECASE)
        )

    def _infer_threshold_group_by(self, lowered: str, domain: str) -> str | None:
        if domain not in {"sales", "retail_price", "product_cost", "stock", "purchases"}:
            return None
        if re.search(r"\b(?:бренд\w*|мар(?:ка|ки|ок|кам|ками)|brands?)\b", lowered):
            return "brand"
        if re.search(r"\b(?:артикул\w*|articles?)\b", lowered):
            return "article"
        if re.search(r"\b(?:товар\w*|products?)\b", lowered):
            return "product_id"
        if domain == "stock" and re.search(r"\bостат\w*\b", lowered):
            return "product_id"
        return None

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

    def _wants_preview_sample(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in ("пример", "sample", "preview", "образец")
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
            column_text = re.sub(
                r"(?:\b(?:из|from)\s+|\bтаблиц[а-яё]*\s+)"
                r"(?:\[?dwh\]?\s*\.\s*)?(?:\[?llm\]?\s*\.\s*)?"
                r"\[?division\]?\b",
                " ",
                lowered,
                flags=re.IGNORECASE,
            )
            for column_name, aliases in DIVISION_ATTRIBUTE_ALIASES.items():
                if any(alias in column_text for alias in aliases):
                    columns.append(column_name)
            return self._dedupe(columns or list(DIVISION_COLUMNS))
        if domain == "product_dimension":
            if self._wants_all_columns(lowered):
                return list(PRODUCT_DIMENSION_COLUMNS)
            if self._is_bare_article_lookup(lowered):
                return list(PRODUCT_DIMENSION_COLUMNS)
            if any(
                marker in lowered
                for marker in (
                    "product attributes",
                    "product details",
                    "атрибут",
                    "характеристик",
                )
            ):
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
            if columns == ["product_id"] and self._extract_product_identifier_values(
                question,
                domain,
            ):
                return list(PRODUCT_DIMENSION_COLUMNS)
            if not columns or (
                include_context_columns
                and any(marker in lowered for marker in ("карточк", "product card"))
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
                if metric_column in PURCHASE_UNIT_COST_COLUMNS.values():
                    columns.extend(
                        [
                            "quantity",
                            metric_column.replace("unit_cost_", "amount_"),
                        ]
                    )
                columns.append(metric_column)
            if not columns or (
                include_context_columns and self._looks_like_sales_row_request(lowered)
                and metric_column not in PURCHASE_UNIT_COST_COLUMNS.values()
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
        if any(
            marker in lowered
            for marker in (
                "ввод остатков",
                "ввод_остатков",
                "перемещен",
                "списан",
                "реализация товаров и услуг",
            )
        ):
            return False
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
                "без топ",
                "без top",
                "без ограничений",
                "за весь период",
                "лимит не используй",
            )
        )

    def _wants_explicit_unbounded_rows(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in (
                "все строки",
                "все записи",
                "без лимита",
                "без топ",
                "без top",
                "без ограничений",
                "лимит не используй",
                "не используй лимит",
                "all rows",
                "no limit",
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

    def _is_bare_article_lookup(self, lowered: str) -> bool:
        match = re.fullmatch(
            r"\s*(?:артикул|артикула|артикулу|артикулом|артикуле|article)\s+"
            r"[\"']?([^\"']+?)[\"']?\s*",
            lowered,
            flags=re.IGNORECASE,
        )
        return bool(match and re.search(r"\d", match.group(1)))

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
            r"\b(?:при\s+|со\s+)?(?:скидк(?:а|е|у|и|ой)|discount(?:\s+of)?)\s*"
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
        if any(marker in lowered for marker in ("артикул", "артикукл", "article")):
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
        ) or bool(
            re.search(
                r"\b(?:список\s+(?:бренд\w*|марок)|list\s+of\s+brands?)\b",
                lowered,
            )
        )

    def _extract_distinct_count_column(
        self,
        lowered: str,
        domain: str,
    ) -> str | None:
        if not any(marker in lowered for marker in ("сколько", "count", "количество")):
            return None

        native_patterns: dict[str, tuple[tuple[str, str], ...]] = {
            "sales": (
                ("channel", r"\bканал\w*\b"),
                ("payment_method", r"\bспособ\w*\s+оплат\w*\b"),
                ("partner_id", r"\bпартн[её]р\w*\b|\bpartner_id\b"),
                ("customer_status", r"\bстатус\w*\s+клиент\w*\b"),
            ),
            "stock": (
                ("warehouse_id", r"\bсклад\w*\b"),
                ("document_id", r"\bдокумент\w*\b"),
            ),
            "purchases": (
                ("recorder_number", r"\bдокумент\w*\b"),
                ("division_id", r"\bподразделени\w*\b"),
            ),
        }
        explicitly_distinct = self._wants_distinct_values(lowered)
        if (
            not explicitly_distinct
            and re.search(r"(?:сколько|количеств\w*)\s+товар\w*", lowered)
            and not re.search(r"товар\w*\s+продавал\w*", lowered)
        ):
            return None
        native_matches: list[tuple[int, str]] = []
        for column_name, pattern in native_patterns.get(domain, ()):
            match = re.search(pattern, lowered, flags=re.IGNORECASE)
            if match:
                native_matches.append((match.start(), column_name))
        if native_matches and not explicitly_distinct:
            return min(native_matches)[1]

        explicit_dimension_patterns = (
            ("product_id", r"\bтовар\w*\b", True),
            ("brand", r"\bбренд\w*\b|\bмарк\w*\b", False),
            ("article", r"\bартикул\w*\b", False),
            ("category", r"\bкатегори\w*\b", False),
            ("common_size", r"\bразмер\w*\b", False),
            ("season", r"\bсезон\w*\b", False),
            ("collection_jw", r"\bколлекци\w*\b", False),
            ("buyer", r"\bбайер\w*\b|\bbuyer\w*\b", False),
        )
        matches: list[tuple[int, str]] = list(native_matches)
        for column_name, pattern, requires_explicit_distinct in explicit_dimension_patterns:
            if requires_explicit_distinct and not explicitly_distinct and not re.search(
                r"\bтовар\w*\s+продавал\w*\b", lowered
            ):
                continue
            match = re.search(pattern, lowered, flags=re.IGNORECASE)
            if match:
                matches.append((match.start(), column_name))
        if matches:
            return min(matches)[1]
        if not explicitly_distinct:
            return None
        for column_name, aliases in PRODUCT_DIMENSION_ATTRIBUTE_ALIASES.items():
            if any(alias in lowered for alias in (column_name, *aliases)):
                return column_name
        return None

    def _mentioned_fact_domains(self, lowered: str) -> set[str]:
        domains: set[str] = set()
        has_cost = bool(re.search(r"себес\w*|себестоим\w*|\bproduct\s+cost\b", lowered))
        if re.search(r"продаж\w*|выруч\w*|\bsales?\b|оборот\w*", lowered):
            domains.add("sales")
        if re.search(r"закуп\w*|\bpurchases?\b|\bprocurement\b", lowered):
            domains.add("purchases")
        if has_cost:
            domains.add("product_cost")

        stock_marker = bool(
            re.search(r"остат\w*|движени\w*\s+склад\w*|\bstock\b", lowered)
        )
        cost_balance_phrase = bool(
            has_cost
            and re.search(
                r"(?:себестоим\w*|стоимост\w*)\s+остат\w*|остат\w*\s+себестоим\w*",
                lowered,
            )
        )
        if stock_marker and not cost_balance_phrase:
            domains.add("stock")

        price_marker = bool(
            re.search(r"розничн\w*\s+цен\w*|\bцен(?:а|ы|у|е|ой|ами|ах)?\b|\bprices?\b", lowered)
        )
        native_unit_price = bool(
            re.search(r"цен\w*\s+продаж\w*|sale\s+price|закупочн\w*\s+цен\w*|purchase\s+(?:price|cost)", lowered)
        )
        if price_marker and not native_unit_price:
            domains.add("retail_price")
        return domains

    def _explicit_table_domain(self, lowered: str) -> str | None:
        explicit_markers = (
            ("retail_price", ("dwh.llm.price", "[dwh].[llm].[price]", "llm.price")),
            ("sales", ("[llm].[sales]", "llm.sales", "[bi].[sales_table]", "bi.sales_table")),
            ("product_cost", ("dwh.llm.cost", "[dwh].[llm].[cost]", "llm.cost")),
            ("stock", ("dwh.llm.stock", "[dwh].[llm].[stock]", "llm.stock")),
            (
                "purchases",
                ("dwh.llm.v_purchases", "[dwh].[llm].[v_purchases]", "llm.v_purchases"),
            ),
            (
                "product_dimension",
                (
                    "dwh.llm.dimension_product",
                    "[dwh].[llm].[dimension_product]",
                    "llm.dimension_product",
                ),
            ),
            ("division_dimension", ("dwh.llm.division", "[dwh].[llm].[division]", "llm.division")),
        )
        for domain, markers in explicit_markers:
            if any(marker in lowered for marker in markers):
                return domain
        return None

    def _unsupported_currency(self, lowered: str, domain: str) -> str | None:
        currency_patterns = {
            "USD": r"\busd\b|доллар\w*",
            "EUR": r"\beur\b|\bевро\b",
            "KZT": r"\bkzt\b|тенге",
            "CHF": r"\bchf\b|франк\w*",
            "RUB": r"\brub\b|рубл\w*",
        }
        supported = {
            "retail_price": {"USD", "EUR", "KZT"},
            "sales": {"USD", "EUR", "KZT"},
            "product_cost": {"KZT"},
            "purchases": {"USD", "EUR", "KZT", "CHF"},
            "stock": set(),
        }.get(domain)
        if supported is None:
            return None
        for currency, pattern in currency_patterns.items():
            if currency not in supported and re.search(pattern, lowered, re.IGNORECASE):
                return currency
        return None

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

    def _wants_current_cost_balance(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in (
                "текущ",
                "актуальн",
                "последн",
                "current",
                "latest",
            )
        ) and any(
            marker in lowered
            for marker in ("себестоим", "себестом", "себес", "product cost")
        )

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
