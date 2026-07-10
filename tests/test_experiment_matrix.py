import unittest

from scripts.run_experiments import build_default_experiments


class ExperimentMatrixTest(unittest.TestCase):
    def test_default_experiments_cover_key_pairs_and_venues(self) -> None:
        experiments = build_default_experiments()

        pairs = {(item["base_symbol"], item["quote_symbol"]) for item in experiments}
        venues = {(item["left_venue"], item["right_venue"]) for item in experiments}

        self.assertIn(("SOL", "USDC"), pairs)
        self.assertIn(("USDC", "USDT"), pairs)
        self.assertIn(("raydium", "jupiter"), venues)


if __name__ == "__main__":
    unittest.main()
