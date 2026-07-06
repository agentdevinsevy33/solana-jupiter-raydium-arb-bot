from __future__ import annotations

from collections import Counter
from statistics import mean

from arbitrage_bot.models import OpportunityRecord
from arbitrage_bot.storage import Storage


class AnalyticsEngine:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def build_summary(self, *, limit: int = 250) -> dict:
        records = self.storage.fetch_recent(limit=limit)
        if not records:
            return {
                "observations": 0,
                "avg_profit_bps": 0.0,
                "avg_profit_lamports": 0.0,
                "best_direction": None,
                "by_status": {},
                "by_direction": {},
                "recent_records": [],
            }

        by_status = Counter(record.evaluation_status for record in records)
        by_direction_counts = Counter(record.direction for record in records)
        by_direction_avg: dict[str, float] = {}
        for direction in by_direction_counts:
            profits = [record.profit_bps for record in records if record.direction == direction]
            by_direction_avg[direction] = mean(profits)

        best_direction = max(by_direction_avg.items(), key=lambda item: item[1])[0]
        return {
            "observations": len(records),
            "avg_profit_bps": mean(record.profit_bps for record in records),
            "avg_profit_lamports": mean(record.profit_lamports for record in records),
            "best_direction": best_direction,
            "by_status": dict(by_status),
            "by_direction": {
                direction: {
                    "count": by_direction_counts[direction],
                    "avg_profit_bps": by_direction_avg[direction],
                }
                for direction in by_direction_counts
            },
            "recent_records": [record.to_dict() for record in records[:25]],
        }

    def render_html_dashboard(self, *, limit: int = 250) -> str:
        summary = self.build_summary(limit=limit)
        rows = []
        for record in summary["recent_records"]:
            rows.append(
                "<tr>"
                f"<td>{record['observed_at']}</td>"
                f"<td>{record['direction']}</td>"
                f"<td>{record['profit_bps']:.2f}</td>"
                f"<td>{record['evaluation_status']}</td>"
                f"<td>{record['evaluation_notes']}</td>"
                "</tr>"
            )
        direction_items = "".join(
            f"<li>{direction}: {metrics['count']} obs, avg {metrics['avg_profit_bps']:.2f} bps</li>"
            for direction, metrics in summary["by_direction"].items()
        )
        status_items = "".join(
            f"<li>{status}: {count}</li>" for status, count in summary["by_status"].items()
        )
        return f"""
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>SOL/ETH Arbitrage Dashboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 2rem; }}
    .card {{ background: #111827; border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 1rem; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 0.6rem; border-bottom: 1px solid #334155; text-align: left; }}
    h1, h2 {{ color: #f8fafc; }}
  </style>
</head>
<body>
  <h1>SOL/ETH Arbitrage Dashboard</h1>
  <div class=\"card\">
    <h2>Overview</h2>
    <p>Observations: {summary['observations']}</p>
    <p>Average profit: {summary['avg_profit_bps']:.2f} bps</p>
    <p>Best direction: {summary['best_direction']}</p>
  </div>
  <div class=\"card\">
    <h2>By Status</h2>
    <ul>{status_items}</ul>
  </div>
  <div class=\"card\">
    <h2>By Direction</h2>
    <ul>{direction_items}</ul>
  </div>
  <div class=\"card\">
    <h2>Recent Opportunities</h2>
    <table>
      <thead>
        <tr><th>Observed At</th><th>Direction</th><th>Profit (bps)</th><th>Status</th><th>Notes</th></tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
