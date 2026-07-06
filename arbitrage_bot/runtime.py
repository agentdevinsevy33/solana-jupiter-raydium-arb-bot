from __future__ import annotations

from pathlib import Path
from typing import Any

from arbitrage_bot.alerts import AlertFormatter, should_emit_alert
from arbitrage_bot.models import OpportunityRecord
from arbitrage_bot.storage import Storage


def reassess_opportunities(
    opportunities: list[OpportunityRecord],
    scanner: Any,
    monitor_seconds: int,
) -> list[OpportunityRecord]:
    if not opportunities or monitor_seconds <= 0:
        return opportunities

    from arbitrage_bot.clients import OpportunityMonitor

    monitor = OpportunityMonitor(persistence_seconds=monitor_seconds)
    monitor.wait()
    refreshed = scanner.scan_once()
    refreshed_map = {item.direction: item for item in refreshed.opportunities}

    updated: list[OpportunityRecord] = []
    for record in opportunities:
        current = refreshed_map.get(record.direction)
        if current is None:
            record.evaluation_status = "expired"
            record.evaluation_notes = f"no profitable quote after {monitor_seconds}s"
        elif current.end_amount >= record.end_amount:
            record.evaluation_status = "persisted"
            record.evaluation_notes = f"still profitable after {monitor_seconds}s"
        else:
            record.evaluation_status = "expired"
            record.evaluation_notes = (
                f"profit dropped from {record.end_amount} to {current.end_amount} after {monitor_seconds}s"
            )
        updated.append(record)
    return updated


class BotRuntime:
    def __init__(self, *, scanner: Any, storage: Storage, min_alert_bps: float = 0.0) -> None:
        self.scanner = scanner
        self.storage = storage
        self.min_alert_bps = min_alert_bps
        self.formatter = AlertFormatter()

    @classmethod
    def from_components(cls, *, scanner: Any, db_path: Path, min_alert_bps: float = 0.0) -> "BotRuntime":
        return cls(scanner=scanner, storage=Storage(db_path), min_alert_bps=min_alert_bps)

    def run_cycle(self, *, monitor_seconds: int = 0) -> dict[str, Any]:
        scan = self.scanner.scan_once()
        self.storage.save_quotes(scan.quotes)
        opportunities = reassess_opportunities(scan.opportunities, self.scanner, monitor_seconds)
        self.storage.save_opportunities(opportunities)
        learning_summary = self.scanner.detector.learning_summary(self.storage.fetch_recent(limit=250))
        alerts = [
            self.formatter.format_opportunity(record)
            for record in opportunities
            if should_emit_alert(record, min_alert_bps=self.min_alert_bps)
        ]
        return {
            "scan": scan.to_dict(),
            "saved_opportunities": [item.to_dict() for item in opportunities],
            "learning_summary": learning_summary,
            "alerts": alerts,
        }
