import tempfile
import unittest
from pathlib import Path

from arbitrage_bot.analytics import AnalyticsEngine
from arbitrage_bot.models import OpportunityRecord, QuoteSnapshot
from arbitrage_bot.storage import Storage


class AnalyticsScanHistoryTest(unittest.TestCase):
    def test_dashboard_renders_recent_scans_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "arb.db"
            storage = Storage(db_path)
            storage.save_quotes(
                [
                    QuoteSnapshot(
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
                ]
            )
            storage.save_opportunities(
                [
                    OpportunityRecord(
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
                ]
            )
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
            engine = AnalyticsEngine(storage)

            html = engine.render_html_dashboard(limit=50, pair_label="SOL/USDC")

            self.assertIn("Recent Scans", html)
            self.assertIn("degraded", html)
            self.assertIn("2026-07-03T00:01:00+00:00", html)
            self.assertIn("raydium", html)
            self.assertIn("jupiter", html)


if __name__ == "__main__":
    unittest.main()
