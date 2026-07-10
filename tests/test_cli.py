import unittest

from bot import build_scanner, parse_args


class CliWiringTest(unittest.TestCase):
    def test_build_scanner_excludes_raydium_when_requested(self) -> None:
        class Args:
            amount_sol = 0.1
            amount = None
            amount_units = None
            min_profit_bps = 5.0
            jupiter_exclude_raydium = True
            base_symbol = "SOL"
            quote_symbol = "ETH"
            base_mint = None
            quote_mint = None
            slippage_bps = 50
            left_venue = "raydium"
            right_venue = "jupiter"
            jupiter_dexes = ""
            jupiter_exclude_dexes = ""

        scanner = build_scanner(Args())

        self.assertEqual(scanner.right_client.exclude_dexes, ["Raydium"])
        self.assertEqual(scanner.start_amount, 100_000_000)
        self.assertEqual(scanner.base_symbol, "SOL")
        self.assertEqual(scanner.quote_symbol, "ETH")
        self.assertEqual(scanner.slippage_bps, 50)

    def test_parse_args_accepts_pair_and_venue_overrides(self) -> None:
        args = parse_args(
            [
                "--once",
                "--base-symbol",
                "SOL",
                "--quote-symbol",
                "USDC",
                "--amount",
                "25",
                "--left-venue",
                "orca",
                "--right-venue",
                "jupiter",
                "--slippage-bps",
                "30",
            ]
        )

        self.assertEqual(args.base_symbol, "SOL")
        self.assertEqual(args.quote_symbol, "USDC")
        self.assertEqual(args.amount, 25.0)
        self.assertEqual(args.left_venue, "orca")
        self.assertEqual(args.right_venue, "jupiter")
        self.assertEqual(args.slippage_bps, 30)


if __name__ == "__main__":
    unittest.main()
