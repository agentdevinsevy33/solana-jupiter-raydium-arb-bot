from __future__ import annotations

from statistics import mean

from arbitrage_bot.models import OpportunityRecord, QuoteSnapshot


class ArbitrageDetector:
    def __init__(self, min_profit_bps: float = 10.0) -> None:
        self.min_profit_bps = min_profit_bps

    def evaluate_cycle(
        self,
        *,
        base_symbol: str,
        quote_symbol: str,
        start_amount: int,
        buy_quote: QuoteSnapshot,
        sell_quote: QuoteSnapshot,
    ) -> OpportunityRecord | None:
        end_amount = int(sell_quote.out_amount)
        profit_lamports = end_amount - int(start_amount)
        profit_bps = (profit_lamports / start_amount) * 10_000 if start_amount else 0.0
        if profit_bps < self.min_profit_bps:
            return None

        direction = f"{buy_quote.venue}_to_{sell_quote.venue}"
        return OpportunityRecord(
            observed_at=max(buy_quote.fetched_at, sell_quote.fetched_at),
            base_symbol=base_symbol,
            quote_symbol=quote_symbol,
            direction=direction,
            start_amount=start_amount,
            intermediate_amount=buy_quote.out_amount,
            end_amount=end_amount,
            profit_lamports=profit_lamports,
            profit_bps=profit_bps,
            buy_venue=buy_quote.venue,
            sell_venue=sell_quote.venue,
            buy_route_labels=list(buy_quote.route_labels),
            sell_route_labels=list(sell_quote.route_labels),
            buy_price_impact_pct=buy_quote.price_impact_pct,
            sell_price_impact_pct=sell_quote.price_impact_pct,
        )

    def learning_summary(self, records: list[OpportunityRecord]) -> dict[str, float | int | str | None]:
        if not records:
            return {
                "observations": 0,
                "persisted": 0,
                "expired": 0,
                "persistence_rate": 0.0,
                "avg_profit_bps": 0.0,
                "best_direction": None,
            }

        persisted = [record for record in records if record.evaluation_status == "persisted"]
        expired = [record for record in records if record.evaluation_status == "expired"]
        by_direction: dict[str, list[float]] = {}
        for record in records:
            by_direction.setdefault(record.direction, []).append(record.profit_bps)

        best_direction = max(
            by_direction.items(),
            key=lambda item: mean(item[1]),
        )[0]
        return {
            "observations": len(records),
            "persisted": len(persisted),
            "expired": len(expired),
            "persistence_rate": len(persisted) / len(records),
            "avg_profit_bps": mean(record.profit_bps for record in records),
            "best_direction": best_direction,
        }
