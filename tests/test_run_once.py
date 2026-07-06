import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bot import run_once
from arbitrage_bot.models import OpportunityRecord, QuoteSnapshot, ScanResult


class FakeDetector:
    def learning_summary(self, records):
        return {
            "observations": len(records),
            "persisted": len(records),
            "expired": 0,
            "persistence_rate": 1.0 if records else 0.0,
            "avg_profit_bps": sum(record.profit_bps for record in records) / len(records) if records else 0.0,
            "best_direction": records[0].direction if records else None,
        }


class FakeScanner:
    def __init__(self):
        self.detector = FakeDetector()

    def scan_once(self):
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
        opportunity = OpportunityRecord(
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
        return ScanResult(scanned_at="now", quotes=[quote], opportunities=[opportunity], errors=[])


class RunOnceDashboardTest(unittest.TestCase):
    @patch("bot.build_scanner", return_value=FakeScanner())
    def test_run_once_writes_dashboard_and_alerts(self, _build_scanner) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(
                db_path=str(Path(tmp) / "arb.db"),
                alert_min_bps=100.0,
                monitor_seconds=0,
                dashboard_output=str(Path(tmp) / "reports" / "dashboard.html"),
            )

            result = run_once(args)

            self.assertEqual(len(result["alerts"]), 1)
            self.assertTrue(Path(result["dashboard_path"]).exists())
            self.assertIn("SOL/ETH Arbitrage Dashboard", Path(result["dashboard_path"]).read_text())


if __name__ == "__main__":
    unittest.main()
