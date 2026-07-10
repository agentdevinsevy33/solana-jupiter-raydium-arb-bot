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


if __name__ == "__main__":
    unittest.main()
