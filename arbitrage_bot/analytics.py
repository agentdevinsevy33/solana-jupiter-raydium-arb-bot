from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from statistics import mean
from typing import Any

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

    def build_heartbeat(
        self,
        *,
        latest_result: dict[str, Any] | None = None,
        stale_after_seconds: int = 180,
    ) -> dict[str, Any]:
        state = self.storage.fetch_dashboard_state()
        latest_quote = state.get("latest_quote")
        recent_scans = state.get("recent_scans", [])
        last_scan_at = latest_result.get("scan", {}).get("scanned_at") if latest_result else None
        if not last_scan_at and recent_scans:
            last_scan_at = recent_scans[0].get("scanned_at")
        if not last_scan_at and latest_quote:
            last_scan_at = latest_quote.get("fetched_at")

        age_seconds = None
        scan_status = "unknown"
        if last_scan_at:
            try:
                scan_dt = datetime.fromisoformat(last_scan_at)
                age_seconds = (datetime.now(timezone.utc) - scan_dt).total_seconds()
                scan_status = "stale" if age_seconds > stale_after_seconds else "healthy"
            except ValueError:
                scan_status = "unknown"

        errors = []
        if latest_result:
            errors = list(latest_result.get("scan", {}).get("errors", []))
            if not errors and latest_result.get("error"):
                errors = [str(latest_result["error"])]
        elif recent_scans and recent_scans[0].get("error_count", 0) > 0:
            errors = [f"Recent scan recorded {recent_scans[0]['error_count']} error(s)"]

        quote_count_this_scan = len(latest_result.get("scan", {}).get("quotes", [])) if latest_result else (recent_scans[0].get("quote_count", 0) if recent_scans else 0)
        opportunity_count_this_scan = len(latest_result.get("scan", {}).get("opportunities", [])) if latest_result else (recent_scans[0].get("opportunity_count", 0) if recent_scans else 0)
        alert_count_this_scan = len(latest_result.get("alerts", [])) if latest_result else (recent_scans[0].get("alert_count", 0) if recent_scans else 0)

        return {
            "scan_status": scan_status,
            "last_scan_at": last_scan_at,
            "age_seconds": age_seconds,
            "quote_count_this_scan": quote_count_this_scan,
            "opportunity_count_this_scan": opportunity_count_this_scan,
            "alert_count_this_scan": alert_count_this_scan,
            "quote_count_total": state.get("quote_count_total", 0),
            "opportunity_count_total": state.get("opportunity_count_total", 0),
            "latest_quote": latest_quote,
            "latest_opportunity": state.get("latest_opportunity"),
            "recent_scans": recent_scans,
            "errors": errors,
        }

    def render_html_dashboard(
        self,
        *,
        limit: int = 250,
        pair_label: str = "SOL/ETH",
        heartbeat: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> str:
        summary = self.build_summary(limit=limit)
        heartbeat = heartbeat or self.build_heartbeat()
        config = config or {}
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
        scan_rows = []
        for scan in heartbeat.get("recent_scans", [])[:20]:
            scan_rows.append(
                "<tr>"
                f"<td>{scan['scanned_at']}</td>"
                f"<td>{scan['scan_status']}</td>"
                f"<td>{scan['pair_label']}</td>"
                f"<td>{scan['left_venue']}</td>"
                f"<td>{scan['right_venue']}</td>"
                f"<td>{scan['quote_count']}</td>"
                f"<td>{scan['opportunity_count']}</td>"
                f"<td>{scan['alert_count']}</td>"
                f"<td>{scan['error_count']}</td>"
                "</tr>"
            )
        direction_items = "".join(
            f"<li>{direction}: {metrics['count']} obs, avg {metrics['avg_profit_bps']:.2f} bps</li>"
            for direction, metrics in summary["by_direction"].items()
        ) or "<li>No opportunities yet</li>"
        status_items = "".join(
            f"<li>{status}: {count}</li>" for status, count in summary["by_status"].items()
        ) or "<li>No opportunities yet</li>"
        config_items = "".join(
            f"<li><strong>{key}</strong>: {value}</li>" for key, value in config.items() if value is not None and value != ""
        ) or "<li>No config metadata available</li>"
        error_items = "".join(f"<li>{error}</li>" for error in heartbeat.get("errors", [])) or "<li>None</li>"
        latest_quote = heartbeat.get("latest_quote") or {}
        latest_opportunity = heartbeat.get("latest_opportunity") or {}
        quote_activity = f"{heartbeat.get('quote_count_this_scan', 0)} quotes, {heartbeat.get('opportunity_count_this_scan', 0)} opportunities, {heartbeat.get('alert_count_this_scan', 0)} alerts"
        age_display = "unknown" if heartbeat.get("age_seconds") is None else f"{heartbeat['age_seconds']:.1f}s"
        return f"""
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>{pair_label} Arbitrage Dashboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 2rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }}
    .card {{ background: #111827; border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 1rem; border: 1px solid #1f2937; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 0.6rem; border-bottom: 1px solid #334155; text-align: left; vertical-align: top; }}
    h1, h2, h3 {{ color: #f8fafc; }}
    .healthy {{ color: #22c55e; font-weight: 700; }}
    .stale {{ color: #f59e0b; font-weight: 700; }}
    .unknown {{ color: #94a3b8; font-weight: 700; }}
    code {{ color: #cbd5e1; }}
  </style>
</head>
<body>
  <h1>{pair_label} Arbitrage Dashboard</h1>
  <div class=\"grid\">
    <div class=\"card\">
      <h2>System Health</h2>
      <p>Scan status: <span class=\"{heartbeat.get('scan_status', 'unknown')}\">{heartbeat.get('scan_status', 'unknown')}</span></p>
      <p>Last scan: {heartbeat.get('last_scan_at') or 'never'}</p>
      <p>Scan age: {age_display}</p>
      <p>Quote Activity: {quote_activity}</p>
      <p>Total stored quotes: {heartbeat.get('quote_count_total', 0)}</p>
      <p>Total stored opportunities: {heartbeat.get('opportunity_count_total', 0)}</p>
    </div>
    <div class=\"card\">
      <h2>Current Configuration</h2>
      <ul>{config_items}</ul>
    </div>
    <div class=\"card\">
      <h2>Latest Quote Snapshot</h2>
      <p>Venue: {latest_quote.get('venue', 'n/a')}</p>
      <p>Fetched: {latest_quote.get('fetched_at', 'n/a')}</p>
      <p>Route: {', '.join(latest_quote.get('route_labels', [])) if latest_quote else 'n/a'}</p>
      <p>Amounts: {latest_quote.get('in_amount', 'n/a')} → {latest_quote.get('out_amount', 'n/a')}</p>
    </div>
    <div class=\"card\">
      <h2>Latest Opportunity</h2>
      <p>Direction: {latest_opportunity.get('direction', 'none')}</p>
      <p>Observed: {latest_opportunity.get('observed_at', 'n/a')}</p>
      <p>Profit: {latest_opportunity.get('profit_bps', 'n/a')} bps</p>
      <p>Status: {latest_opportunity.get('evaluation_status', 'n/a')}</p>
    </div>
  </div>
  <div class=\"card\">
    <h2>Recent Errors</h2>
    <ul>{error_items}</ul>
  </div>
  <div class=\"card\">
    <h2>Recent Scans</h2>
    <table>
      <thead>
        <tr><th>Scanned At</th><th>Status</th><th>Pair</th><th>Left Venue</th><th>Right Venue</th><th>Quotes</th><th>Opportunities</th><th>Alerts</th><th>Errors</th></tr>
      </thead>
      <tbody>
        {''.join(scan_rows) or '<tr><td colspan="9">No scan history yet</td></tr>'}
      </tbody>
    </table>
  </div>
  <div class=\"card\">
    <h2>Opportunity Overview</h2>
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
