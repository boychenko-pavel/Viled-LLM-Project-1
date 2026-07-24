from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QueryFilters:
    date_column: str | None = None
    date_eq: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    identifier_column: str | None = None
    identifier_value: str | None = None
    identifier_values: list[str] = field(default_factory=list)
    threshold_column: str | None = None
    threshold_operator: str | None = None
    threshold_value: str | None = None
    equality_filters: dict[str, str] = field(default_factory=dict)
    dimension_filters: dict[str, str] = field(default_factory=dict)
    division_filters: dict[str, str] = field(default_factory=dict)
    in_stock_only: bool = False


@dataclass
class QueryIntent:
    operation: str = "unknown"
    database_name: str | None = None
    schema_name: str = "LLM"
    table_name: str = "price"
    domain: str = "retail_price"
    requested_columns: list[str] = field(default_factory=list)
    metric_column: str | None = None
    aggregate_function: str | None = None
    group_by: str | None = None
    group_by_columns: list[str] = field(default_factory=list)
    balance_mode: str | None = None
    limit: int | None = None
    sort_column: str | None = None
    sort_direction: str = "desc"
    latest_per_identifier: bool = False
    distinct: bool = False
    filters: QueryFilters = field(default_factory=QueryFilters)

    @property
    def qualified_table_name(self) -> str:
        if self.database_name:
            return f"[{self.database_name}].[{self.schema_name}].[{self.table_name}]"
        return f"[{self.schema_name}].[{self.table_name}]"
