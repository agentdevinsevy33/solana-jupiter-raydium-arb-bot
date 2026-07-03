import unittest

from bot import build_scanner


class CliWiringTest(unittest.TestCase):
    def test_build_scanner_excludes_raydium_when_requested(self) -> None:
        class Args:
            amount_sol = 0.1
            min_profit_bps = 5.0
            jupiter_exclude_raydium = True

        scanner = build_scanner(Args())

        self.assertEqual(scanner.jupiter_client.exclude_dexes, ["Raydium"])
        self.assertEqual(scanner.start_amount, 100_000_000)


if __name__ == "__main__":
    unittest.main()
