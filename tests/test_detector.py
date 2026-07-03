import unittest
from datetime import datetime, timedelta, timezone

from arbitrage_bot.detector import ArbitrageDetector
from arbitrage_bot.models import OpportunityRecord, QuoteSnapshot


class ArbitrageDetectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = ArbitrageDetector(min_profit_bps=5)

    def test_detects_profitable_cycle_from_raydium_to_jupiter(self) -> None:
        ray_buy = QuoteSnapshot(
            venue="raydium",
            input_mint="SOL",
            output_mint="ETH",
            in_amount=1_000_000_000,
            out_amount=70_000,
            price_impact_pct=0.01,
            route_labels=["Raydium"],
            fetched_at="2026-07-03T00:00:00+00:00",
            metadata={},
        )
        jup_sell = QuoteSnapshot(
            venue="jupiter",
            input_mint="ETH",
            output_mint="SOL",
            in_amount=70_000,
            out_amount=1_020_000_000,
            price_impact_pct=0.02,
            route_labels=["Orca V2"],
            fetched_at="2026-07-03T00:00:01+00:00",
            metadata={},
        )

        opportunity = self.detector.evaluate_cycle(
            base_symbol="SOL",
            quote_symbol="ETH",
            start_amount=1_000_000_000,
            buy_quote=ray_buy,
            sell_quote=jup_sell,
        )

        self.assertIsNotNone(opportunity)
        assert opportunity is not None
        self.assertEqual(opportunity.direction, "raydium_to_jupiter")
        self.assertGreater(opportunity.profit_bps, 5)
        self.assertEqual(opportunity.end_amount, 1_020_000_000)

    def test_rejects_unprofitable_cycle(self) -> None:
        ray_buy = QuoteSnapshot(
            venue="raydium",
            input_mint="SOL",
            output_mint="ETH",
            in_amount=1_000_000_000,
            out_amount=60_000,
            price_impact_pct=0.01,
            route_labels=["Raydium"],
            fetched_at="2026-07-03T00:00:00+00:00",
            metadata={},
        )
        jup_sell = QuoteSnapshot(
            venue="jupiter",
            input_mint="ETH",
            output_mint="SOL",
            in_amount=60_000,
            out_amount=995_000_000,
            price_impact_pct=0.02,
            route_labels=["Orca V2"],
            fetched_at="2026-07-03T00:00:01+00:00",
            metadata={},
        )

        opportunity = self.detector.evaluate_cycle(
            base_symbol="SOL",
            quote_symbol="ETH",
            start_amount=1_000_000_000,
            buy_quote=ray_buy,
            sell_quote=jup_sell,
        )

        self.assertIsNone(opportunity)

    def test_summarizes_learning_metrics(self) -> None:
        now = datetime.now(timezone.utc)
        records = [
            OpportunityRecord(
                observed_at=(now - timedelta(minutes=3)).isoformat(),
                base_symbol="SOL",
                quote_symbol="ETH",
                direction="raydium_to_jupiter",
                start_amount=1_000_000_000,
                intermediate_amount=70_000,
                end_amount=1_015_000_000,
                profit_lamports=15_000_000,
                profit_bps=150.0,
                buy_venue="raydium",
                sell_venue="jupiter",
                buy_route_labels=["Raydium"],
                sell_route_labels=["Orca V2"],
                buy_price_impact_pct=0.01,
                sell_price_impact_pct=0.02,
                evaluation_status="expired",
                evaluation_notes="spread vanished",
            ),
            OpportunityRecord(
                observed_at=(now - timedelta(minutes=1)).isoformat(),
                base_symbol="SOL",
                quote_symbol="ETH",
                direction="jupiter_to_raydium",
                start_amount=1_000_000_000,
                intermediate_amount=71_000,
                end_amount=1_030_000_000,
                profit_lamports=30_000_000,
                profit_bps=300.0,
                buy_venue="jupiter",
                sell_venue="raydium",
                buy_route_labels=["Orca V2"],
                sell_route_labels=["Raydium"],
                buy_price_impact_pct=0.01,
                sell_price_impact_pct=0.02,
                evaluation_status="persisted",
                evaluation_notes="held for 60s",
            ),
        ]

        summary = self.detector.learning_summary(records)

        self.assertEqual(summary["observations"], 2)
        self.assertEqual(summary["persisted"], 1)
        self.assertAlmostEqual(summary["persistence_rate"], 0.5)
        self.assertGreater(summary["avg_profit_bps"], 200)


if __name__ == "__main__":
    unittest.main()
