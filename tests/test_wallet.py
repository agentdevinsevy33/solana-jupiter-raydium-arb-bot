import json
import tempfile
import unittest
from pathlib import Path

from arbitrage_bot.wallet import create_devnet_wallet, load_wallet


class WalletTest(unittest.TestCase):
    def test_create_and_load_devnet_wallet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wallet_path = Path(tmp) / "devnet-wallet.json"

            created = create_devnet_wallet(wallet_path)
            loaded = load_wallet(wallet_path)
            saved = json.loads(wallet_path.read_text())

            self.assertEqual(created.public_key, loaded.public_key)
            self.assertEqual(created.secret_key, loaded.secret_key)
            self.assertEqual(len(saved), 64)
            self.assertTrue(all(isinstance(item, int) for item in saved))
            self.assertGreater(len(created.public_key), 30)
            self.assertEqual(created.network, "devnet")


if __name__ == "__main__":
    unittest.main()
