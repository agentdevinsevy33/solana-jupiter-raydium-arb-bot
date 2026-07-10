import tempfile
import unittest
from pathlib import Path

from arbitrage_bot.models import OpportunityRecord, QuoteSnapshot
from arbitrage_bot.storage import Storage


class StorageHeartbeatTest(unittest.TestCase):
    def test_fetch_dashboard_state_includes_latest_quote_and_opportunity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "arb.db")
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
                        metadata={"route": "a"},
                    )
                ]
            )
            storage.save_opportunities(
                [
                    OpportunityRecord(
                        observed_at="2026-07-03T00:01:00+00:00",
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

            state = storage.fetch_dashboard_state()

            self.assertEqual(state["quote_count_total"], 1)
            self.assertEqual(state["opportunity_count_total"], 1)
            self.assertEqual(state["latest_quote"]["venue"], "raydium")
            self.assertEqual(state["latest_opportunity"]["direction"], "raydium_to_jupiter")


if __name__ == "__main__":
    unittest.main()
