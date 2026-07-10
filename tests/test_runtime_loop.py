import tempfile
import unittest
from pathlib import Path

from arbitrage_bot.models import OpportunityRecord, QuoteSnapshot, ScanResult
from arbitrage_bot.runtime import BotRuntime


class FakeDetector:
    def learning_summary(self, records):
        return {
            "observations": len(records),
            "persisted": len([record for record in records if record.evaluation_status == "persisted"]),
            "expired": len([record for record in records if record.evaluation_status == "expired"]),
            "persistence_rate": 1.0 if records else 0.0,
            "avg_profit_bps": sum(record.profit_bps for record in records) / len(records) if records else 0.0,
            "best_direction": records[0].direction if records else None,
        }


class FakeScanner:
    def __init__(self, result: ScanResult):
        self.result = result
        self.detector = FakeDetector()
        self.base_symbol = "SOL"
        self.quote_symbol = "ETH"
        self.start_amount = 100
        self.slippage_bps = 50

        class Client:
            def __init__(self, venue):
                self.venue = venue

        self.left_client = Client("raydium")
        self.right_client = Client("jupiter")

    def scan_once(self) -> ScanResult:
        return self.result


class RuntimeLoopTest(unittest.TestCase):
    def test_run_loop_collects_cycles_and_stops_at_max_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quote = QuoteSnapshot(
                venue="raydium",
                input_mint="SOL",
                output_mint="ETH",
                in_amount=100,
                out_amount=70,
                price_impact_pct=0.01,
                route_labels=["Raydium"],
                fetched_at="2026-07-03T00:00:00+00:00",
                metadata={},
            )
            opp = OpportunityRecord(
                observed_at="2026-07-03T00:00:00+00:00",
                base_symbol="SOL",
                quote_symbol="ETH",
                direction="raydium_to_jupiter",
                start_amount=100,
                intermediate_amount=70,
                end_amount=105,
                profit_lamports=5,
                profit_bps=500.0,
                buy_venue="raydium",
                sell_venue="jupiter",
                buy_route_labels=["Raydium"],
                sell_route_labels=["Orca V2"],
                buy_price_impact_pct=0.01,
                sell_price_impact_pct=0.02,
                evaluation_status="persisted",
                evaluation_notes="stable",
            )
            runtime = BotRuntime.from_components(
                scanner=FakeScanner(ScanResult(scanned_at="now", quotes=[quote], opportunities=[opp], errors=[])),
                db_path=Path(tmp) / "arb.db",
                min_alert_bps=100.0,
            )

            results = runtime.run_loop(interval_seconds=0, max_cycles=2, monitor_seconds=0)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["alerts"], results[1]["alerts"])
            self.assertEqual(results[0]["saved_opportunities"][0]["direction"], "raydium_to_jupiter")


if __name__ == "__main__":
    unittest.main()
