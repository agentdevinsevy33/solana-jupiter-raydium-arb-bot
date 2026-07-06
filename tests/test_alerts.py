import unittest

from arbitrage_bot.alerts import AlertFormatter, should_emit_alert
from arbitrage_bot.models import OpportunityRecord


class AlertingTest(unittest.TestCase):
    def make_record(self, profit_bps: float = 125.0) -> OpportunityRecord:
        return OpportunityRecord(
            observed_at="2026-07-03T00:00:00+00:00",
            base_symbol="SOL",
            quote_symbol="ETH",
            direction="raydium_to_jupiter",
            start_amount=100_000_000,
            intermediate_amount=67_000,
            end_amount=101_250_000,
            profit_lamports=1_250_000,
            profit_bps=profit_bps,
            buy_venue="raydium",
            sell_venue="jupiter",
            buy_route_labels=["Raydium"],
            sell_route_labels=["Orca V2"],
            buy_price_impact_pct=0.02,
            sell_price_impact_pct=0.01,
            evaluation_status="persisted",
            evaluation_notes="held for 30s",
        )

    def test_formats_human_readable_alert(self) -> None:
        message = AlertFormatter().format_opportunity(self.make_record())

        self.assertIn("SOL/ETH arbitrage", message)
        self.assertIn("raydium_to_jupiter", message)
        self.assertIn("125.00 bps", message)
        self.assertIn("held for 30s", message)

    def test_only_emits_above_threshold(self) -> None:
        self.assertTrue(should_emit_alert(self.make_record(125.0), min_alert_bps=100.0))
        self.assertFalse(should_emit_alert(self.make_record(80.0), min_alert_bps=100.0))


if __name__ == "__main__":
    unittest.main()
