from __future__ import annotations

import unittest
from datetime import date

from sql_agent.query_utils import parse_relative_date_filters


class RelativeDateFilterTests(unittest.TestCase):
    def test_yesterday(self) -> None:
        self.assertEqual(
            [("eq", "2026-06-20")],
            parse_relative_date_filters("Покажи продажи за вчера", date(2026, 6, 21)),
        )

    def test_previous_month_across_year_boundary(self) -> None:
        self.assertEqual(
            [("between", "2025-12-01"), ("between_end", "2025-12-31")],
            parse_relative_date_filters("Продажи за прошлый месяц", date(2026, 1, 15)),
        )

    def test_previous_year(self) -> None:
        self.assertEqual(
            [("between", "2025-01-01"), ("between_end", "2025-12-31")],
            parse_relative_date_filters("Выручка в прошлом году", date(2026, 6, 21)),
        )

    def test_from_start_of_year(self) -> None:
        self.assertEqual(
            [("between", "2026-01-01"), ("between_end", "2026-06-21")],
            parse_relative_date_filters("Продажи с начала года", date(2026, 6, 21)),
        )

    def test_from_start_of_month(self) -> None:
        self.assertEqual(
            [("between", "2026-06-01"), ("between_end", "2026-06-21")],
            parse_relative_date_filters("Продажи с начала месяца", date(2026, 6, 21)),
        )

    def test_half_year_uses_current_year(self) -> None:
        self.assertEqual(
            [("between", "2026-07-01"), ("between_end", "2026-12-31")],
            parse_relative_date_filters("Продажи за 2 полугодие года", date(2026, 6, 21)),
        )

    def test_half_year_accepts_explicit_year(self) -> None:
        self.assertEqual(
            [("between", "2025-01-01"), ("between_end", "2025-06-30")],
            parse_relative_date_filters("Продажи за 1 полугодие 2025 года", date(2026, 6, 21)),
        )

    def test_each_quarter(self) -> None:
        expected_ranges = (
            ("2026-01-01", "2026-03-31"),
            ("2026-04-01", "2026-06-30"),
            ("2026-07-01", "2026-09-30"),
            ("2026-10-01", "2026-12-31"),
        )
        for quarter, (date_from, date_to) in enumerate(expected_ranges, start=1):
            with self.subTest(quarter=quarter):
                self.assertEqual(
                    [("between", date_from), ("between_end", date_to)],
                    parse_relative_date_filters(
                        f"Продажи за {quarter} квартал года",
                        date(2026, 6, 21),
                    ),
                )

    def test_quarter_accepts_explicit_year(self) -> None:
        self.assertEqual(
            [("between", "2024-10-01"), ("between_end", "2024-12-31")],
            parse_relative_date_filters("Продажи за 4 квартал 2024 года", date(2026, 6, 21)),
        )


if __name__ == "__main__":
    unittest.main()
