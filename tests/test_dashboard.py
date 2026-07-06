import tempfile
import unittest
from pathlib import Path

from arbitrage_bot.analytics import AnalyticsEngine
from arbitrage_bot.dashboard import DashboardWriter
from arbitrage_bot.models import OpportunityRecord
from arbitrage_bot.storage import Storage


class DashboardWriterTest(unittest.TestCase):
    def test_writes_html_dashboard_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "arb.db"
            storage = Storage(db_path)
            storage.save_opportunities(
                [
                    OpportunityRecord(
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
                ]
            )
            output_path = Path(tmp) / "reports" / "dashboard.html"
            writer = DashboardWriter(output_path)

            written = writer.write(AnalyticsEngine(storage), limit=10)

            self.assertEqual(written, str(output_path))
            self.assertTrue(output_path.exists())
            self.assertIn("SOL/ETH Arbitrage Dashboard", output_path.read_text())


if __name__ == "__main__":
    unittest.main()
