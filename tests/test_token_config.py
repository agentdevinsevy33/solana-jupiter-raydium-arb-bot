import unittest

from arbitrage_bot.token_config import (
    KNOWN_ETH_MINTS,
    TOKEN_DEFAULTS,
    resolve_token,
)


class TokenConfigTest(unittest.TestCase):
    def test_known_eth_mints_include_sollet_and_wormhole(self) -> None:
        self.assertIn("sollet_eth", KNOWN_ETH_MINTS)
        self.assertIn("wormhole_weth", KNOWN_ETH_MINTS)

    def test_token_defaults_include_major_research_pairs(self) -> None:
        self.assertIn("SOL", TOKEN_DEFAULTS)
        self.assertIn("USDC", TOKEN_DEFAULTS)
        self.assertIn("USDT", TOKEN_DEFAULTS)

    def test_resolve_token_prefers_known_defaults(self) -> None:
        token = resolve_token(symbol="USDC")

        self.assertEqual(token.symbol, "USDC")
        self.assertEqual(token.decimals, 6)
        self.assertTrue(token.mint)


if __name__ == "__main__":
    unittest.main()
