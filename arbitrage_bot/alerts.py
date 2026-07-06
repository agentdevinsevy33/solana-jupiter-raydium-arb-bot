from __future__ import annotations

from arbitrage_bot.models import OpportunityRecord


class AlertFormatter:
    def format_opportunity(self, record: OpportunityRecord) -> str:
        profit_sol = record.profit_lamports / 1_000_000_000
        return (
            f"SOL/ETH arbitrage detected | direction={record.direction} | "
            f"profit={record.profit_bps:.2f} bps ({profit_sol:.6f} SOL) | "
            f"buy={record.buy_venue} -> sell={record.sell_venue} | "
            f"status={record.evaluation_status} | notes={record.evaluation_notes}"
        )


def should_emit_alert(record: OpportunityRecord, *, min_alert_bps: float) -> bool:
    return record.profit_bps >= min_alert_bps
