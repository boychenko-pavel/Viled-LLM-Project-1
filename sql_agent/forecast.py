from __future__ import annotations

import base64
from io import BytesIO
from dataclasses import dataclass
from datetime import date
from html import escape

from sqlalchemy import text

from sql_agent.database import DatabaseConnector
from sql_agent.query_utils import format_sql_response


SALES_FORECAST_SQL = """
SELECT
    CAST(DATEFROMPARTS(YEAR([sale_date]), MONTH([sale_date]), 1) AS date) AS month_start,
    SUM([quantity]) AS total_quantity,
    SUM([amount]) AS total_amount_kzt,
    COUNT(*) AS row_count
FROM [BI].[sales_table]
WHERE [sale_date] IS NOT NULL
GROUP BY DATEFROMPARTS(YEAR([sale_date]), MONTH([sale_date]), 1)
ORDER BY month_start ASC
""".strip()


@dataclass(frozen=True)
class MonthlySales:
    month_start: date
    total_quantity: float
    total_amount_kzt: float
    row_count: int
    is_forecast: bool = False


class SalesForecastAgent:
    def __init__(self, database_connector: DatabaseConnector | None = None) -> None:
        self.database_connector = database_connector or DatabaseConnector()

    def ask(self, message: str) -> str:
        engine = self.database_connector.build_engine()
        history = self._load_monthly_sales(engine)
        if len(history) < 2:
            return format_sql_response(
                sql=SALES_FORECAST_SQL,
                result_text=self._format_rows(history),
                explanation_text=(
                    "Для прогноза нужно минимум два месяца исторических продаж "
                    "из [BI].[sales_table] по полю [sale_date]."
                ),
            )

        forecast = self._forecast_next_year(history)
        chart_svg = self._build_svg(history, forecast)
        result_text = self._format_rows(history[-12:] + forecast)
        explanation = (
            "Продажи агрегированы ежемесячно из [BI].[sales_table]: "
            "месяц = DATEFROMPARTS(YEAR([sale_date]), MONTH([sale_date]), 1), "
            "метрики = SUM([amount]) в KZT, SUM([quantity]) и COUNT(*). "
            "Прогноз на 12 месяцев построен по total_amount_kzt простой моделью тренда "
            "с сезонностью по месяцу года."
        )
        return (
            format_sql_response(
                sql=SALES_FORECAST_SQL,
                result_text=result_text,
                explanation_text=explanation,
            )
            + "\n\nChart:\n"
            + chart_svg
        )

    def load_conversation(self) -> list[dict[str, str]]:
        return []

    def reset_memory(self) -> str:
        return "Forecast Sales does not store chat memory."

    def build_matplotlib_chart_data_uri(self) -> str:
        engine = self.database_connector.build_engine()
        history = self._load_monthly_sales(engine)
        if len(history) < 2:
            raise ValueError("Not enough monthly sales history to build a forecast chart.")
        forecast = self._forecast_next_year(history)
        image_bytes = self._build_matplotlib_png(history, forecast)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _load_monthly_sales(self, engine) -> list[MonthlySales]:
        with engine.connect() as connection:
            rows = connection.execute(text(SALES_FORECAST_SQL)).fetchall()

        monthly_sales = []
        for row in rows:
            month_start = row.month_start
            if not isinstance(month_start, date):
                month_start = date.fromisoformat(str(month_start)[:10])
            monthly_sales.append(
                MonthlySales(
                    month_start=month_start,
                    total_quantity=float(row.total_quantity or 0),
                    total_amount_kzt=float(row.total_amount_kzt or 0),
                    row_count=int(row.row_count or 0),
                )
            )
        return monthly_sales

    def _forecast_next_year(self, history: list[MonthlySales]) -> list[MonthlySales]:
        try:
            return self._forecast_with_sklearn(history)
        except Exception:
            return self._forecast_with_average(history)

    def _forecast_with_sklearn(self, history: list[MonthlySales]) -> list[MonthlySales]:
        from sklearn.linear_model import LinearRegression

        first_month = history[0].month_start
        x_train = [
            self._features(self._month_index(first_month, item.month_start), item.month_start.month)
            for item in history
        ]
        y_amount = [item.total_amount_kzt for item in history]
        y_quantity = [item.total_quantity for item in history]

        amount_model = LinearRegression().fit(x_train, y_amount)
        quantity_model = LinearRegression().fit(x_train, y_quantity)

        forecast = []
        last_month = history[-1].month_start
        for offset in range(1, 13):
            month_start = self._add_months(last_month, offset)
            month_index = self._month_index(first_month, month_start)
            features = [self._features(month_index, month_start.month)]
            forecast.append(
                MonthlySales(
                    month_start=month_start,
                    total_quantity=max(0.0, float(quantity_model.predict(features)[0])),
                    total_amount_kzt=max(0.0, float(amount_model.predict(features)[0])),
                    row_count=0,
                    is_forecast=True,
                )
            )
        return forecast

    def _forecast_with_average(self, history: list[MonthlySales]) -> list[MonthlySales]:
        recent = history[-12:] if len(history) >= 12 else history
        avg_amount = sum(item.total_amount_kzt for item in recent) / len(recent)
        avg_quantity = sum(item.total_quantity for item in recent) / len(recent)
        last_month = history[-1].month_start
        return [
            MonthlySales(
                month_start=self._add_months(last_month, offset),
                total_quantity=avg_quantity,
                total_amount_kzt=avg_amount,
                row_count=0,
                is_forecast=True,
            )
            for offset in range(1, 13)
        ]

    def _features(self, month_index: int, month_number: int) -> list[float]:
        season = [1.0 if month_number == month else 0.0 for month in range(1, 13)]
        return [float(month_index), *season]

    def _month_index(self, first_month: date, current_month: date) -> int:
        return (current_month.year - first_month.year) * 12 + current_month.month - first_month.month

    def _add_months(self, month_start: date, months: int) -> date:
        month_number = month_start.month + months - 1
        year = month_start.year + month_number // 12
        month = month_number % 12 + 1
        return date(year, month, 1)

    def _format_rows(self, rows: list[MonthlySales]) -> str:
        if not rows:
            return "No rows found."
        lines = ["month_start,total_amount_kzt,total_quantity,row_count,type"]
        for item in rows:
            row_type = "forecast" if item.is_forecast else "actual"
            lines.append(
                ",".join(
                    [
                        item.month_start.isoformat(),
                        f"{item.total_amount_kzt:.2f}",
                        f"{item.total_quantity:.2f}",
                        str(item.row_count),
                        row_type,
                    ]
                )
            )
        return "\n".join(lines)

    def _build_svg(self, history: list[MonthlySales], forecast: list[MonthlySales]) -> str:
        actual = history[-24:] if len(history) > 24 else history
        points = actual + forecast
        values = [item.total_amount_kzt for item in points]
        max_value = max(values) if values else 1.0
        if max_value <= 0:
            max_value = 1.0

        width = 920
        height = 340
        left = 72
        right = 24
        top = 28
        bottom = 62
        chart_width = width - left - right
        chart_height = height - top - bottom

        def xy(index: int, value: float) -> tuple[float, float]:
            x = left + (chart_width * index / max(1, len(points) - 1))
            y = top + chart_height - (chart_height * value / max_value)
            return x, y

        actual_path = " ".join(
            f"{'M' if index == 0 else 'L'} {xy(index, item.total_amount_kzt)[0]:.1f} {xy(index, item.total_amount_kzt)[1]:.1f}"
            for index, item in enumerate(actual)
        )
        forecast_start = max(0, len(actual) - 1)
        forecast_points = points[forecast_start:]
        forecast_path = " ".join(
            f"{'M' if index == 0 else 'L'} {xy(index + forecast_start, item.total_amount_kzt)[0]:.1f} {xy(index + forecast_start, item.total_amount_kzt)[1]:.1f}"
            for index, item in enumerate(forecast_points)
        )
        separator_x = xy(max(0, len(actual) - 1), 0)[0]
        y_ticks = [0, max_value / 2, max_value]
        labels = self._chart_labels(points)

        return f"""
<svg class="forecast-chart" viewBox="0 0 {width} {height}" role="img" aria-label="Monthly sales forecast">
  <rect width="{width}" height="{height}" rx="8" fill="#0a0e15" />
  <line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#2b3342" />
  <line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#2b3342" />
  {''.join(self._grid_line(left, right, width, top, chart_height, max_value, tick) for tick in y_ticks)}
  <line x1="{separator_x:.1f}" y1="{top}" x2="{separator_x:.1f}" y2="{height - bottom}" stroke="#8b5cf6" stroke-dasharray="5 5" opacity="0.75" />
  <path d="{actual_path}" fill="none" stroke="#21d07a" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />
  <path d="{forecast_path}" fill="none" stroke="#6ee7f9" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" stroke-dasharray="7 6" />
  {''.join(labels)}
  <text x="{left}" y="18" fill="#f5f7fb" font-size="14" font-weight="700">Monthly sales amount, KZT</text>
  <circle cx="{width - 252}" cy="16" r="5" fill="#21d07a" />
  <text x="{width - 240}" y="20" fill="#cbd3df" font-size="12">Actual</text>
  <circle cx="{width - 162}" cy="16" r="5" fill="#6ee7f9" />
  <text x="{width - 150}" y="20" fill="#cbd3df" font-size="12">Forecast</text>
</svg>
""".strip()

    def _grid_line(
        self,
        left: int,
        right: int,
        width: int,
        top: int,
        chart_height: int,
        max_value: float,
        tick: float,
    ) -> str:
        y = top + chart_height - (chart_height * tick / max_value)
        label = self._format_compact_number(tick)
        return (
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" '
            f'stroke="#202838" />'
            f'<text x="12" y="{y + 4:.1f}" fill="#9aa4b6" font-size="11">{escape(label)}</text>'
        )

    def _chart_labels(self, points: list[MonthlySales]) -> list[str]:
        if not points:
            return []
        label_indexes = sorted({0, len(points) // 2, len(points) - 1})
        width = 920
        left = 72
        right = 24
        chart_width = width - left - right
        labels = []
        for index in label_indexes:
            x = left + (chart_width * index / max(1, len(points) - 1))
            label = points[index].month_start.strftime("%Y-%m")
            labels.append(
                f'<text x="{x:.1f}" y="318" fill="#9aa4b6" font-size="11" text-anchor="middle">{escape(label)}</text>'
            )
        return labels

    def _format_compact_number(self, value: float) -> str:
        if abs(value) >= 1_000_000_000:
            return f"{value / 1_000_000_000:.1f}B"
        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if abs(value) >= 1_000:
            return f"{value / 1_000:.1f}K"
        return f"{value:.0f}"

    def _build_matplotlib_png(self, history: list[MonthlySales], forecast: list[MonthlySales]) -> bytes:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt

        actual = history[-36:] if len(history) > 36 else history
        actual_dates = [item.month_start for item in actual]
        forecast_dates = [item.month_start for item in forecast]

        figure, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
        figure.patch.set_facecolor("#0a0e15")
        figure.suptitle("Forecast Sales: monthly actuals and 12-month forecast", color="#f5f7fb", fontsize=16)

        self._plot_metric(
            axes[0],
            actual_dates,
            [item.total_amount_kzt for item in actual],
            forecast_dates,
            [item.total_amount_kzt for item in forecast],
            "Sales amount, KZT",
        )
        self._plot_metric(
            axes[1],
            actual_dates,
            [item.total_quantity for item in actual],
            forecast_dates,
            [item.total_quantity for item in forecast],
            "Quantity",
        )

        for axis in axes:
            axis.set_facecolor("#10131c")
            axis.tick_params(colors="#cbd3df")
            axis.yaxis.label.set_color("#cbd3df")
            axis.grid(True, color="#2b3342", linewidth=0.8, alpha=0.75)
            axis.legend(facecolor="#151a25", edgecolor="#2b3342", labelcolor="#cbd3df")
            axis.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
            axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

        axes[-1].set_xlabel("Month", color="#cbd3df")
        figure.autofmt_xdate(rotation=35)
        figure.tight_layout(rect=[0, 0, 1, 0.95])

        buffer = BytesIO()
        figure.savefig(buffer, format="png", dpi=150, facecolor=figure.get_facecolor())
        plt.close(figure)
        return buffer.getvalue()

    def _plot_metric(
        self,
        axis,
        actual_dates: list[date],
        actual_values: list[float],
        forecast_dates: list[date],
        forecast_values: list[float],
        ylabel: str,
    ) -> None:
        axis.plot(
            actual_dates,
            actual_values,
            color="#21d07a",
            marker="o",
            linewidth=2.2,
            label="Actual",
        )
        join_dates = actual_dates[-1:] + forecast_dates if actual_dates else forecast_dates
        join_values = actual_values[-1:] + forecast_values if actual_values else forecast_values
        axis.plot(
            join_dates,
            join_values,
            color="#6ee7f9",
            marker="o",
            linestyle="--",
            linewidth=2.2,
            label="Forecast",
        )
        if actual_dates:
            axis.axvline(actual_dates[-1], color="#8b5cf6", linestyle=":", linewidth=1.8)
        axis.set_ylabel(ylabel)
