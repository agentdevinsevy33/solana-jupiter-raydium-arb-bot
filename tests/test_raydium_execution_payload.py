import unittest

from arbitrage_bot.execution import ExecutionPlanBuilder


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


class RaydiumPayloadShapeTest(unittest.TestCase):
    def test_full_quote_payload_is_forwarded_when_available(self) -> None:
        session = FakeRaydiumSession()
        builder = ExecutionPlanBuilder(raydium_session=session)
        full_quote = {
            "id": "quote-id",
            "success": True,
            "version": "V1",
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

        builder.build_raydium_swap_plan(
            public_key="ExamplePubkey1111111111111111111111111111111",
            quote_response=full_quote,
            wrap_sol=True,
            unwrap_sol=False,
        )

        self.assertTrue(session.last_json["swapResponse"]["success"])
        self.assertIn("data", session.last_json["swapResponse"])


if __name__ == "__main__":
    unittest.main()
