import unittest
from unittest.mock import patch

from arbitrage_bot.clients import JupiterQuoteClient, OpportunityMonitor, OrcaQuoteClient, RaydiumQuoteClient
from arbitrage_bot.models import QuoteRequest, QuoteSnapshot


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.last_params = None
        self.last_url = None

    def get(self, url, params=None, timeout=None, headers=None):
        self.last_url = url
        self.last_params = params
        return FakeResponse(self.payload)


class QuoteClientsTest(unittest.TestCase):
    def test_jupiter_quote_client_supports_dex_filters(self) -> None:
        session = FakeSession(
            {
                "inputMint": "SOL",
                "outputMint": "ETH",
                "inAmount": "100",
                "outAmount": "7",
                "priceImpactPct": "0.01",
                "routePlan": [{"swapInfo": {"label": "Raydium"}}],
            }
        )
        client = JupiterQuoteClient(session=session, dexes=["Raydium"], exclude_dexes=[])

        quote = client.get_quote(QuoteRequest(input_mint="SOL", output_mint="ETH", amount=100))

        self.assertEqual(quote.route_labels, ["Raydium"])
        self.assertEqual(session.last_params["dexes"], "Raydium")

    def test_raydium_quote_client_parses_success_payload(self) -> None:
        session = FakeSession(
            {
                "success": True,
                "id": "abc",
                "version": "V1",
                "data": {
                    "inputMint": "SOL",
                    "outputMint": "ETH",
                    "inputAmount": "100",
                    "outputAmount": "7",
                    "priceImpactPct": 0.03,
                    "routePlan": [{"poolId": "pool-1"}],
                },
            }
        )
        client = RaydiumQuoteClient(session=session)

        quote = client.get_quote(QuoteRequest(input_mint="SOL", output_mint="ETH", amount=100))

        self.assertEqual(quote.route_labels, ["pool-1"])
        self.assertEqual(quote.out_amount, 7)

    def test_orca_quote_client_uses_search_endpoint_and_best_pool(self) -> None:
        session = FakeSession(
            {
                "data": [
                    {
                        "address": "pool-1",
                        "tokenA": {"mint": "SOL", "symbol": "SOL"},
                        "tokenB": {"mint": "USDC", "symbol": "USDC"},
                        "price": 150.0,
                        "liquidity": 2000000,
                        "feeRate": 0.003,
                    },
                    {
                        "address": "pool-2",
                        "tokenA": {"mint": "SOL", "symbol": "SOL"},
                        "tokenB": {"mint": "USDC", "symbol": "USDC"},
                        "price": 149.0,
                        "liquidity": 1000000,
                        "feeRate": 0.003,
                    },
                ]
            }
        )
        client = OrcaQuoteClient(session=session)

        quote = client.get_quote(
            QuoteRequest(
                input_mint="SOL",
                output_mint="USDC",
                amount=100_000_000,
                input_symbol="SOL",
                output_symbol="USDC",
                input_decimals=9,
                output_decimals=6,
            )
        )

        self.assertEqual(session.last_url, "https://api.orca.so/v2/solana/pools/search")
        self.assertEqual(session.last_params["q"], "SOL-USDC")
        self.assertEqual(quote.route_labels, ["pool-1"])
        self.assertEqual(quote.output_mint, "USDC")
        self.assertGreater(quote.out_amount, 0)

    @patch("arbitrage_bot.clients.time.sleep")
    def test_monitor_marks_expired_when_quote_deteriorates(self, _sleep) -> None:
        monitor = OpportunityMonitor(persistence_seconds=1)
        initial = QuoteSnapshot(
            venue="jupiter",
            input_mint="ETH",
            output_mint="SOL",
            in_amount=70_000,
            out_amount=1_020_000_000,
            price_impact_pct=0.01,
            route_labels=["Orca V2"],
            fetched_at="2026-07-03T00:00:00+00:00",
            metadata={},
        )
        follow_up = QuoteSnapshot(
            venue="jupiter",
            input_mint="ETH",
            output_mint="SOL",
            in_amount=70_000,
            out_amount=1_000_000_000,
            price_impact_pct=0.01,
            route_labels=["Orca V2"],
            fetched_at="2026-07-03T00:00:01+00:00",
            metadata={},
        )

        status, notes = monitor.evaluate_persistence(initial, follow_up)

        self.assertEqual(status, "expired")
        self.assertIn("decayed", notes)


if __name__ == "__main__":
    unittest.main()
