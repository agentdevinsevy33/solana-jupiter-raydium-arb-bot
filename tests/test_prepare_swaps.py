import unittest
from unittest.mock import patch

from bot import _augment_result_with_execution_preparation, parse_args


class PrepareSwapsIntegrationTest(unittest.TestCase):
    @patch("bot.ensure_wallet")
    @patch("bot.prepare_swap_execution")
    def test_prepare_swaps_mode_uses_raw_quote_payloads(self, mock_prepare, mock_wallet) -> None:
        mock_wallet.return_value = object()
        mock_prepare.return_value = {"wallet": {"public_key": "abc"}, "prepared_swaps": []}
        args = parse_args(["--once", "--mode", "prepare-swaps", "--wallet-path", "wallets/devnet.json"])
        result = {
            "scan": {
                "quotes": [
                    {
                        "venue": "jupiter",
                        "input_mint": "So11111111111111111111111111111111111111112",
                        "output_mint": "2FPyTwcZLUg1MDrwsyoP4D6s1tM7hAkHYRjkNb5w6Pxk",
                        "in_amount": 100,
                        "out_amount": 50,
                        "price_impact_pct": 0.01,
                        "route_labels": ["Meteora"],
                        "metadata": {"raw_quote_response": {"inputMint": "So11111111111111111111111111111111111111112", "outAmount": "50"}},
                    }
                ],
                "opportunities": [],
                "errors": [],
                "scanned_at": "now",
            }
        }

        updated = _augment_result_with_execution_preparation(args, result)

        self.assertIn("wallet", updated)
        self.assertIn("prepared_swaps", updated)
        mock_prepare.assert_called_once()
        self.assertIs(updated, result)


if __name__ == "__main__":
    unittest.main()
