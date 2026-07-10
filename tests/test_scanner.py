import unittest

from arbitrage_bot.detector import ArbitrageDetector
from arbitrage_bot.models import QuoteRequest, QuoteSnapshot
from arbitrage_bot.scanner import ArbitrageScanner


class FakeClient:
    def __init__(self, venue, quote_map):
        self.venue = venue
        self.quote_map = quote_map
        self.requests = []

    def get_quote(self, request: QuoteRequest) -> QuoteSnapshot:
        self.requests.append(request)
        key = (request.input_mint, request.output_mint, request.amount)
        return self.quote_map[key]


class ArbitrageScannerTest(unittest.TestCase):
    def test_scanner_returns_two_directional_checks(self) -> None:
        sol = "SOL"
        eth = "ETH"
        start_amount = 1_000_000_000
        left_forward = QuoteSnapshot(
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
        left_reverse = QuoteSnapshot(
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
        right_forward = QuoteSnapshot(
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
        right_reverse = QuoteSnapshot(
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

        left_client = FakeClient(
            "raydium",
            {
                (sol, eth, start_amount): left_forward,
                (eth, sol, 69_000): left_reverse,
            },
        )
        right_client = FakeClient(
            "jupiter",
            {
                (sol, eth, start_amount): right_forward,
                (eth, sol, 70_000): right_reverse,
            },
        )

        scanner = ArbitrageScanner(
            base_symbol="SOL",
            quote_symbol="ETH",
            base_mint=sol,
            quote_mint=eth,
            start_amount=start_amount,
            detector=ArbitrageDetector(min_profit_bps=5),
            left_client=left_client,
            right_client=right_client,
        )

        result = scanner.scan_once()

        self.assertEqual(len(result.quotes), 4)
        self.assertEqual(len(result.opportunities), 2)
        self.assertEqual(
            {op.direction for op in result.opportunities},
            {"raydium_to_jupiter", "jupiter_to_raydium"},
        )

    def test_scanner_uses_configured_slippage_for_all_requests(self) -> None:
        sol = "SOL"
        usdc = "USDC"
        start_amount = 100_000_000
        left_forward = QuoteSnapshot(
            venue="orca",
            input_mint=sol,
            output_mint=usdc,
            in_amount=start_amount,
            out_amount=15_000_000,
            price_impact_pct=0.0,
            route_labels=["SOL-USDC"],
            fetched_at="2026-07-03T00:00:00+00:00",
            metadata={},
        )
        left_reverse = QuoteSnapshot(
            venue="orca",
            input_mint=usdc,
            output_mint=sol,
            in_amount=14_900_000,
            out_amount=99_000_000,
            price_impact_pct=0.0,
            route_labels=["SOL-USDC"],
            fetched_at="2026-07-03T00:00:00+00:00",
            metadata={},
        )
        right_forward = QuoteSnapshot(
            venue="jupiter",
            input_mint=sol,
            output_mint=usdc,
            in_amount=start_amount,
            out_amount=14_900_000,
            price_impact_pct=0.0,
            route_labels=["Meteora"],
            fetched_at="2026-07-03T00:00:00+00:00",
            metadata={},
        )
        right_reverse = QuoteSnapshot(
            venue="jupiter",
            input_mint=usdc,
            output_mint=sol,
            in_amount=15_000_000,
            out_amount=99_100_000,
            price_impact_pct=0.0,
            route_labels=["Meteora"],
            fetched_at="2026-07-03T00:00:00+00:00",
            metadata={},
        )

        left_client = FakeClient(
            "orca",
            {
                (sol, usdc, start_amount): left_forward,
                (usdc, sol, 14_900_000): left_reverse,
            },
        )
        right_client = FakeClient(
            "jupiter",
            {
                (sol, usdc, start_amount): right_forward,
                (usdc, sol, 15_000_000): right_reverse,
            },
        )

        scanner = ArbitrageScanner(
            base_symbol="SOL",
            quote_symbol="USDC",
            base_mint=sol,
            quote_mint=usdc,
            start_amount=start_amount,
            detector=ArbitrageDetector(min_profit_bps=5),
            left_client=left_client,
            right_client=right_client,
            slippage_bps=30,
        )

        scanner.scan_once()

        self.assertEqual([request.slippage_bps for request in left_client.requests], [30, 30])
        self.assertEqual([request.slippage_bps for request in right_client.requests], [30, 30])


if __name__ == "__main__":
    unittest.main()
