from __future__ import annotations

from sql_agent.intent_parser import IntentParser
from sql_agent.sql_builder import SqlBuilder


def test_local_llm_payload_uses_canonical_table_and_whitelisted_fields() -> None:
    intent = IntentParser()._intent_from_payload(
        {
            "operation": "aggregate",
            "domain": "sales",
            "database_name": "attacker_db",
            "schema_name": "dbo",
            "table_name": "secrets",
            "requested_columns": ["product_id", "customer_name", "amount_eur"],
            "metric_column": "amount_eur",
            "aggregate_function": "sum",
            "group_by": "brand",
            "limit": 1000000,
            "sort_column": "brand",
            "sort_direction": "sideways",
            "distinct": "false",
            "filters": {
                "date_from": "2026-02-01",
                "date_to": "not-a-date",
                "identifier_value": "12345",
                "threshold_column": "brand",
                "threshold_operator": ">",
                "threshold_value": "0 OR 1=1",
                "equality_filters": {
                    "channel": "Retail",
                    "customer_name": "Not allowed",
                },
                "dimension_filters": {
                    "brand": "Cartier",
                    "unknown_dimension": "Not allowed",
                },
                "division_filters": {
                    "city": "Алматы",
                    "unknown_division": "Not allowed",
                },
                "in_stock_only": "false",
            },
        }
    )

    assert intent is not None
    assert intent.database_name is None
    assert intent.schema_name == "LLM"
    assert intent.table_name == "sales"
    assert intent.requested_columns == ["product_id", "amount_eur"]
    assert intent.limit == 100
    assert intent.sort_direction == "desc"
    assert not intent.distinct
    assert intent.filters.date_from == "2026-02-01"
    assert intent.filters.date_to is None
    assert intent.filters.threshold_column is None
    assert intent.filters.threshold_operator is None
    assert intent.filters.threshold_value is None
    assert intent.filters.equality_filters == {"channel": "Retail"}
    assert intent.filters.dimension_filters == {"brand": "Cartier"}
    assert intent.filters.division_filters == {"city": "Алматы"}
    assert not intent.filters.in_stock_only


def test_local_llm_payload_rejects_unknown_domain_or_operation() -> None:
    parser = IntentParser()

    assert parser._intent_from_payload(
        {"operation": "select", "domain": "payroll"}
    ) is None
    assert parser._intent_from_payload(
        {"operation": "drop", "domain": "sales"}
    ) is None


def test_local_llm_aggregate_requires_a_valid_metric() -> None:
    intent = IntentParser()._intent_from_payload(
        {
            "operation": "aggregate",
            "domain": "sales",
            "metric_column": "customer_name",
            "aggregate_function": "sum",
        }
    )

    assert intent is None


def test_local_llm_boolean_flags_accept_only_explicit_true_values() -> None:
    parser = IntentParser()

    assert parser._safe_payload_bool(True)
    assert parser._safe_payload_bool("true")
    assert not parser._safe_payload_bool(False)
    assert not parser._safe_payload_bool("false")
    assert not parser._safe_payload_bool(1)


def test_local_llm_aggregate_requires_explicit_function() -> None:
    intent = IntentParser()._intent_from_payload(
        {
            "operation": "aggregate",
            "domain": "sales",
            "metric_column": "amount",
            "aggregate_function": None,
        }
    )

    assert intent is None


def test_local_llm_dimension_count_builds_required_join() -> None:
    intent = IntentParser()._intent_from_payload(
        {
            "operation": "aggregate",
            "domain": "sales",
            "metric_column": "brand",
            "aggregate_function": "count",
            "distinct": True,
        }
    )

    assert intent is not None
    assert SqlBuilder()._uses_dimension_join(intent)
    assert "dimension_product" in SqlBuilder()._build_from_clause(intent)
    assert SqlBuilder()._aggregate_sql(intent, "count", "brand") == "COUNT(DISTINCT dim.[brand])"


def test_local_llm_dimension_sort_builds_required_join() -> None:
    intent = IntentParser()._intent_from_payload(
        {
            "operation": "select",
            "domain": "stock",
            "requested_columns": ["product_id"],
            "sort_column": "brand",
            "limit": 10,
        }
    )

    assert intent is not None
    assert "dimension_product" in SqlBuilder()._build_from_clause(intent)
    assert SqlBuilder()._column_expr(intent, "brand") == "dim.[brand]"


def test_local_llm_rejects_categorical_or_running_balance_aggregates() -> None:
    parser = IntentParser()

    assert parser._intent_from_payload(
        {
            "operation": "aggregate",
            "domain": "sales",
            "metric_column": "brand",
            "aggregate_function": "sum",
        }
    ) is None
    assert parser._intent_from_payload(
        {
            "operation": "aggregate",
            "domain": "product_cost",
            "metric_column": "cost_sum",
            "aggregate_function": "sum",
        }
    ) is None
    assert parser._intent_from_payload(
        {
            "operation": "aggregate",
            "domain": "product_cost",
            "metric_column": "qnt_sum",
            "aggregate_function": "sum",
        }
    ) is None


def test_local_llm_rejects_invalid_threshold_metric_for_operation() -> None:
    parser = IntentParser()

    assert parser._intent_from_payload(
        {
            "operation": "aggregate",
            "domain": "sales",
            "metric_column": "amount",
            "aggregate_function": "sum",
            "filters": {
                "threshold_column": "channel",
                "threshold_operator": ">",
                "threshold_value": "5",
            },
        }
    ) is None
    assert parser._intent_from_payload(
        {
            "operation": "stock_balance",
            "domain": "stock",
            "filters": {
                "threshold_column": "amount",
                "threshold_operator": ">",
                "threshold_value": "5",
            },
        }
    ) is None
