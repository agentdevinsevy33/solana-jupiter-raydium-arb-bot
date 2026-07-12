import unittest
from unittest.mock import patch

from bot import _augment_result_with_execution, parse_args


class ExecuteSwapsIntegrationTest(unittest.TestCase):
    @patch("bot.ensure_wallet")
    @patch("bot.execute_prepared_swaps")
    @patch("bot.prepare_swap_execution")
    def test_execute_swaps_mode_prepares_and_executes(self, mock_prepare, mock_execute, mock_wallet) -> None:
        mock_wallet.return_value = object()
        mock_prepare.return_value = {
            "wallet": {"public_key": "abc", "network": "mainnet-beta"},
            "prepared_swaps": [{"venue": "jupiter", "transactions_base64": ["AQID"]}],
        }
        mock_execute.return_value = {
            "execution_summary": {"completed": True},
            "execution_results": [{"venue": "jupiter", "ok": True, "transactions": []}],
        }
        args = parse_args(
            [
                "--once",
                "--mode",
                "execute-swaps",
                "--wallet-path",
                "wallets/mainnet.json",
                "--network",
                "mainnet-beta",
                "--rpc-url",
                "https://rpc.example.invalid",
            ]
        )
        result = {"scan": {"quotes": [], "opportunities": [], "errors": [], "scanned_at": "now"}}

        updated = _augment_result_with_execution(args, result)

        self.assertIn("prepared_swaps", updated)
        self.assertIn("execution_summary", updated)
        mock_prepare.assert_called_once()
        mock_execute.assert_called_once()
        self.assertIs(updated, result)


if __name__ == "__main__":
    unittest.main()
