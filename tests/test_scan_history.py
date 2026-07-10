import tempfile
import unittest
from pathlib import Path

from arbitrage_bot.models import OpportunityRecord, QuoteSnapshot, ScanResult
from arbitrage_bot.runtime import BotRuntime
from arbitrage_bot.storage import Storage


class FakeDetector:
    def learning_summary(self, records):
        return {
            "observations": len(records),
            "persisted": sum(1 for record in records if record.evaluation_status == "persisted"),
            "expired": sum(1 for record in records if record.evaluation_status == "expired"),
            "persistence_rate": 1.0 if records else 0.0,
            "avg_profit_bps": sum(record.profit_bps for record in records) / len(records) if records else 0.0,
            "best_direction": records[0].direction if records else None,
        }


class FakeScanner:
    def __init__(self, result: ScanResult):
        self.result = result
        self.detector = FakeDetector()

    def scan_once(self) -> ScanResult:
        return self.result


class ScanHistoryTest(unittest.TestCase):
    def test_runtime_persists_scan_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quote = QuoteSnapshot(
                venue="raydium",
                input_mint="SOL",
                output_mint="USDC",
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
                quote_symbol="USDC",
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
                scanner=FakeScanner(ScanResult(scanned_at="2026-07-03T00:00:00+00:00", quotes=[quote], opportunities=[opp], errors=[])),
                db_path=Path(tmp) / "arb.db",
                min_alert_bps=100.0,
            )

            runtime.run_cycle(monitor_seconds=0)
            history = runtime.storage.fetch_recent_scans(limit=5)

            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["quote_count"], 1)
            self.assertEqual(history[0]["opportunity_count"], 1)
            self.assertEqual(history[0]["scan_status"], "ok")

    def test_dashboard_state_includes_recent_scans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "arb.db")
            storage.save_scan_summary(
                scanned_at="2026-07-03T00:00:00+00:00",
                quote_count=4,
                opportunity_count=1,
                alert_count=1,
                error_count=0,
                scan_status="ok",
                pair_label="SOL/USDC",
                left_venue="raydium",
                right_venue="jupiter",
            )
            storage.save_scan_summary(
                scanned_at="2026-07-03T00:01:00+00:00",
                quote_count=4,
                opportunity_count=0,
                alert_count=0,
                error_count=1,
                scan_status="degraded",
                pair_label="SOL/USDC",
                left_venue="raydium",
                right_venue="jupiter",
            )

            state = storage.fetch_dashboard_state()

            self.assertEqual(len(state["recent_scans"]), 2)
            self.assertEqual(state["recent_scans"][0]["scan_status"], "degraded")
            self.assertEqual(state["recent_scans"][1]["scan_status"], "ok")


if __name__ == "__main__":
    unittest.main()
