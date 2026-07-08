from __future__ import annotations

import unittest

from sql_agent.query_utils import format_rows, format_sql_for_display, format_sql_response


class SqlFormattingTests(unittest.TestCase):
    def test_format_sql_response_uses_multiline_sql(self) -> None:
        response = format_sql_response(
            sql="SELECT TOP 10 [sale_date], [product_id], SUM([amount]) AS sum_value FROM [LLM].[sales] WHERE [sale_date] >= '2025-01-01' AND [sale_date] <= '2025-01-31' GROUP BY [sale_date], [product_id] ORDER BY sum_value DESC",
            result_text="sale_date, product_id, sum_value",
            explanation_text="test",
        )

        self.assertIn("SQL:\nSELECT\n    TOP 10 [sale_date],\n    [product_id],\n    SUM([amount]) AS sum_value\nFROM [LLM].[sales]\nWHERE", response)
        self.assertIn("    [sale_date] >= '2025-01-01' AND\n    [sale_date] <= '2025-01-31'", response)
        self.assertIn("\nGROUP BY [sale_date], [product_id]\nORDER BY sum_value DESC", response)

    def test_window_order_by_stays_inside_over_clause(self) -> None:
        formatted = format_sql_for_display(
            "WITH latest_price AS (SELECT [price_date], [ware_id], ROW_NUMBER() OVER (PARTITION BY [ware_id] ORDER BY [price_date] DESC) AS rn FROM [DWH].[LLM].[price] WHERE [ware_id] = '12345') SELECT [price_date], [ware_id] FROM latest_price WHERE rn = 1 ORDER BY [price_date] DESC, [ware_id]"
        )

        self.assertIn(
            "ROW_NUMBER() OVER (PARTITION BY [ware_id] ORDER BY [price_date] DESC) AS rn",
            formatted,
        )
        self.assertIn("\nORDER BY [price_date] DESC, [ware_id]", formatted)

    def test_format_rows_displays_16_byte_values_as_guid(self) -> None:
        result = format_rows(
            ["recorder_guid"],
            [(bytes.fromhex("9d5800505690995c11ef9bff60f33c4f"),)],
        )

        self.assertIn("5000589d-9056-5c99-11ef-9bff60f33c4f", result)
        self.assertNotIn("b'", result)


if __name__ == "__main__":
    unittest.main()
