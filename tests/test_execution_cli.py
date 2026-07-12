import unittest

from bot import parse_args


class ExecutionCliTest(unittest.TestCase):
    def test_parse_args_accepts_execution_and_wallet_flags(self) -> None:
        args = parse_args(
            [
                "--once",
                "--mode",
                "prepare-swaps",
                "--wallet-path",
                "wallets/devnet.json",
                "--network",
                "devnet",
                "--max-cycles",
                "3",
            ]
        )

        self.assertEqual(args.mode, "prepare-swaps")
        self.assertEqual(args.wallet_path, "wallets/devnet.json")
        self.assertEqual(args.network, "devnet")
        self.assertEqual(args.max_cycles, 3)

    def test_parse_args_accepts_execute_mode_and_rpc_flags(self) -> None:
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
                "--confirm-timeout-seconds",
                "12",
                "--poll-interval-seconds",
                "0.25",
                "--skip-preflight",
                "--commitment",
                "processed",
                "--max-send-retries",
                "5",
            ]
        )

        self.assertEqual(args.mode, "execute-swaps")
        self.assertEqual(args.rpc_url, "https://rpc.example.invalid")
        self.assertEqual(args.confirm_timeout_seconds, 12.0)
        self.assertEqual(args.poll_interval_seconds, 0.25)
        self.assertTrue(args.skip_preflight)
        self.assertEqual(args.commitment, "processed")
        self.assertEqual(args.max_send_retries, 5)


if __name__ == "__main__":
    unittest.main()
