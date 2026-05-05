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
    threshold_column: str | None = None
    threshold_operator: str | None = None
    threshold_value: str | None = None


@dataclass
class QueryIntent:
    operation: str = "unknown"
    schema_name: str = "BI"
    table_name: str = "actual_retail_price"
    domain: str = "retail_price"
    requested_columns: list[str] = field(default_factory=list)
    metric_column: str | None = None
    aggregate_function: str | None = None
    group_by: str | None = None
    limit: int | None = None
    sort_column: str | None = None
    sort_direction: str = "desc"
    filters: QueryFilters = field(default_factory=QueryFilters)

    @property
    def qualified_table_name(self) -> str:
        return f"[{self.schema_name}].[{self.table_name}]"
