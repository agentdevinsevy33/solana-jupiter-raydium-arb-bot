import tempfile
import unittest
from pathlib import Path

from arbitrage_bot.analytics import AnalyticsEngine
from arbitrage_bot.models import OpportunityRecord, QuoteSnapshot
from arbitrage_bot.storage import Storage


class AnalyticsTest(unittest.TestCase):
    def test_builds_summary_and_html_dashboard(self) -> None:
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
                    ),
                    QuoteSnapshot(
                        venue="jupiter",
                        input_mint="USDC",
                        output_mint="SOL",
                        in_amount=70,
                        out_amount=101,
                        price_impact_pct=0.02,
                        route_labels=["Orca V2"],
                        fetched_at="2026-07-03T00:01:00+00:00",
                        metadata={},
                    ),
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
                    ),
                    OpportunityRecord(
                        observed_at="2026-07-03T01:00:00+00:00",
                        base_symbol="SOL",
                        quote_symbol="USDC",
                        direction="jupiter_to_raydium",
                        start_amount=100,
                        intermediate_amount=71,
                        end_amount=102,
                        profit_lamports=2,
                        profit_bps=200.0,
                        buy_venue="jupiter",
                        sell_venue="raydium",
                        buy_route_labels=["Orca V2"],
                        sell_route_labels=["Raydium"],
                        buy_price_impact_pct=0.01,
                        sell_price_impact_pct=0.02,
                        evaluation_status="expired",
                        evaluation_notes="faded",
                    ),
                ]
            )
            engine = AnalyticsEngine(storage)

            summary = engine.build_summary(limit=50)
            html = engine.render_html_dashboard(
                limit=50,
                pair_label="SOL/USDC",
                heartbeat={
                    "scan_status": "healthy",
                    "last_scan_at": "2026-07-03T00:01:00+00:00",
                    "quote_count_this_scan": 2,
                    "opportunity_count_this_scan": 1,
                    "errors": [],
                },
                config={
                    "left_venue": "raydium",
                    "right_venue": "jupiter",
                    "slippage_bps": 50,
                    "amount": 100,
                },
            )

            self.assertEqual(summary["observations"], 2)
            self.assertEqual(summary["by_status"]["persisted"], 1)
            self.assertIn("SOL/USDC Arbitrage Dashboard", html)
            self.assertIn("raydium_to_jupiter", html)
            self.assertIn("System Health", html)
            self.assertIn("Quote Activity", html)
            self.assertIn("healthy", html)
            self.assertIn("2 quotes", html)


if __name__ == "__main__":
    unittest.main()
