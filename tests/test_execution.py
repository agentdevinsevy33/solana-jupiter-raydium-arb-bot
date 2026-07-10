import unittest

from arbitrage_bot.execution import ExecutionPlanBuilder
from arbitrage_bot.models import QuoteRequest


class FakeJupiterSession:
    def __init__(self):
        self.last_url = None
        self.last_json = None

    def post(self, url, json=None, timeout=None, headers=None):
        self.last_url = url
        self.last_json = json

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "swapTransaction": "AQID",
                    "lastValidBlockHeight": 123,
                    "prioritizationFeeLamports": 456,
                    "dynamicSlippageReport": {"slippageBps": 12},
                }

        return Response()


class FakeRaydiumSession:
    def __init__(self):
        self.last_url = None
        self.last_json = None

    def post(self, url, json=None, timeout=None, headers=None):
        self.last_url = url
        self.last_json = json

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "id": "abc",
                    "success": True,
                    "version": "V1",
                    "data": [{"transaction": "AQID"}],
                }

        return Response()


class ExecutionPlanBuilderTest(unittest.TestCase):
    def test_builds_jupiter_swap_plan(self) -> None:
        session = FakeJupiterSession()
        builder = ExecutionPlanBuilder(jupiter_session=session)
        quote_response = {
            "inputMint": "So11111111111111111111111111111111111111112",
            "inAmount": "100000000",
            "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "outAmount": "17000000",
            "otherAmountThreshold": "16800000",
            "swapMode": "ExactIn",
            "slippageBps": 50,
            "priceImpactPct": "0.0001",
            "routePlan": [],
        }

        plan = builder.build_jupiter_swap_plan(
            public_key="ExamplePubkey1111111111111111111111111111111",
            quote_response=quote_response,
        )

        self.assertEqual(plan.venue, "jupiter")
        self.assertEqual(plan.transaction_count, 1)
        self.assertEqual(plan.transactions_base64, ["AQID"])
        self.assertEqual(session.last_url, "https://api.jup.ag/swap/v1/swap")
        self.assertEqual(session.last_json["userPublicKey"], "ExamplePubkey1111111111111111111111111111111")
        self.assertEqual(session.last_json["quoteResponse"]["outAmount"], "17000000")

    def test_builds_raydium_swap_plan(self) -> None:
        session = FakeRaydiumSession()
        builder = ExecutionPlanBuilder(raydium_session=session)
        quote_response = {
            "success": True,
            "data": {
                "swapType": "BaseIn",
                "inputMint": "So11111111111111111111111111111111111111112",
                "inputAmount": "100000000",
                "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "outputAmount": "17000000",
                "otherAmountThreshold": "16800000",
                "slippageBps": 50,
                "priceImpactPct": 0.0012,
                "referrerAmount": "0",
                "routePlan": [],
            },
        }

        plan = builder.build_raydium_swap_plan(
            public_key="ExamplePubkey1111111111111111111111111111111",
            quote_response=quote_response,
            wrap_sol=True,
            unwrap_sol=False,
        )

        self.assertEqual(plan.venue, "raydium")
        self.assertEqual(plan.transaction_count, 1)
        self.assertEqual(plan.transactions_base64, ["AQID"])
        self.assertEqual(session.last_url, "https://transaction-v1.raydium.io/transaction/swap-base-in")
        self.assertEqual(session.last_json["wallet"], "ExamplePubkey1111111111111111111111111111111")
        self.assertTrue(session.last_json["wrapSol"])
        self.assertFalse(session.last_json["unwrapSol"])


if __name__ == "__main__":
    unittest.main()
