import unittest

from arbitrage_bot.token_config import KNOWN_ETH_MINTS


class TokenConfigTest(unittest.TestCase):
    def test_known_eth_mints_include_sollet_and_wormhole(self) -> None:
        self.assertIn("sollet_eth", KNOWN_ETH_MINTS)
        self.assertIn("wormhole_weth", KNOWN_ETH_MINTS)


if __name__ == "__main__":
    unittest.main()
