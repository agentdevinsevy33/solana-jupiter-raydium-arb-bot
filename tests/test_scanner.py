import unittest

from arbitrage_bot.detector import ArbitrageDetector
from arbitrage_bot.models import QuoteRequest, QuoteSnapshot
from arbitrage_bot.scanner import ArbitrageScanner


class FakeClient:
    def __init__(self, venue, quote_map):
        self.venue = venue
        self.quote_map = quote_map

    def get_quote(self, request: QuoteRequest) -> QuoteSnapshot:
        key = (request.input_mint, request.output_mint, request.amount)
        return self.quote_map[key]


class ArbitrageScannerTest(unittest.TestCase):
    def test_scanner_returns_two_directional_checks(self) -> None:
        sol = "SOL"
        eth = "ETH"
        start_amount = 1_000_000_000
        ray_forward = QuoteSnapshot(
            venue="raydium",
            input_mint=sol,
            output_mint=eth,
            in_amount=start_amount,
            out_amount=70_000,
            price_impact_pct=0.01,
            route_labels=["Raydium"],
            fetched_at="2026-07-03T00:00:00+00:00",
            metadata={},
        )
        ray_reverse = QuoteSnapshot(
            venue="raydium",
            input_mint=eth,
            output_mint=sol,
            in_amount=69_000,
            out_amount=1_010_000_000,
            price_impact_pct=0.01,
            route_labels=["Raydium"],
            fetched_at="2026-07-03T00:00:00+00:00",
            metadata={},
        )
        jup_forward = QuoteSnapshot(
            venue="jupiter",
            input_mint=sol,
            output_mint=eth,
            in_amount=start_amount,
            out_amount=69_000,
            price_impact_pct=0.01,
            route_labels=["Orca V2"],
            fetched_at="2026-07-03T00:00:00+00:00",
            metadata={},
        )
        jup_reverse = QuoteSnapshot(
            venue="jupiter",
            input_mint=eth,
            output_mint=sol,
            in_amount=70_000,
            out_amount=1_020_000_000,
            price_impact_pct=0.01,
            route_labels=["Orca V2"],
            fetched_at="2026-07-03T00:00:00+00:00",
            metadata={},
        )

        ray_client = FakeClient(
            "raydium",
            {
                (sol, eth, start_amount): ray_forward,
                (eth, sol, 69_000): ray_reverse,
            },
        )
        jup_client = FakeClient(
            "jupiter",
            {
                (sol, eth, start_amount): jup_forward,
                (eth, sol, 70_000): jup_reverse,
            },
        )

        scanner = ArbitrageScanner(
            base_symbol="SOL",
            quote_symbol="ETH",
            base_mint=sol,
            quote_mint=eth,
            start_amount=start_amount,
            detector=ArbitrageDetector(min_profit_bps=5),
            raydium_client=ray_client,
            jupiter_client=jup_client,
        )

        result = scanner.scan_once()

        self.assertEqual(len(result.quotes), 4)
        self.assertEqual(len(result.opportunities), 2)
        self.assertEqual(
            {op.direction for op in result.opportunities},
            {"raydium_to_jupiter", "jupiter_to_raydium"},
        )


if __name__ == "__main__":
    unittest.main()
