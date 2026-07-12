import unittest

from arbitrage_bot.executor import TradeExecutor
from arbitrage_bot.wallet import create_devnet_wallet


class FakeRpcSession:
    def __init__(self):
        self.requests = []
        self._status_checks = 0

    def post(self, url, json=None, timeout=None, headers=None):
        self.requests.append({"url": url, "json": json, "timeout": timeout, "headers": headers})
        method = json["method"]
        if method == "sendTransaction":
            payload = {"jsonrpc": "2.0", "id": 1, "result": "rpc-signature-123"}
        elif method == "getSignatureStatuses":
            self._status_checks += 1
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "value": [
                        {
                            "slot": 99,
                            "confirmations": None,
                            "err": None,
                            "confirmationStatus": "confirmed",
                        }
                    ]
                },
            }
        else:
            raise AssertionError(f"Unexpected RPC method: {method}")

        class Response:
            def raise_for_status(self):
                return None

            def json(self_nonlocal):
                return payload

        return Response()


class FakeVersionedTransaction:
    signed_instances = []

    def __init__(self, message, keypairs):
        self.message = message
        self.keypairs = keypairs
        self.signatures = ["local-signature-abc"]
        FakeVersionedTransaction.signed_instances.append(self)

    @classmethod
    def from_bytes(cls, raw):
        instance = cls.__new__(cls)
        instance.message = {"decoded": raw}
        instance.keypairs = []
        instance.signatures = []
        return instance

    def __bytes__(self):
        return b"signed-transaction-bytes"


class FakeKeypair:
    @classmethod
    def from_bytes(cls, raw):
        return {"raw": raw}


class ExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeVersionedTransaction.signed_instances = []

    def test_execute_prepared_swaps_signs_sends_and_confirms(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            wallet = create_devnet_wallet(Path(tmp) / "wallet.json")
            session = FakeRpcSession()
            executor = TradeExecutor(
                rpc_url="https://example-rpc.invalid",
                session=session,
                confirm_timeout_seconds=0.1,
                poll_interval_seconds=0.0,
            )
            prepared_swaps = [
                {
                    "venue": "jupiter",
                    "public_key": wallet.public_key,
                    "transactions_base64": ["AQID"],
                    "metadata": {"source": "test"},
                }
            ]

            with patch.object(TradeExecutor, "_load_solders", return_value=(FakeKeypair, FakeVersionedTransaction)):
                result = executor.execute_prepared_swaps(wallet, prepared_swaps)

        self.assertTrue(result["execution_summary"]["completed"])
        self.assertEqual(result["execution_summary"]["submitted_transaction_count"], 1)
        self.assertEqual(result["execution_summary"]["confirmed_transaction_count"], 1)
        self.assertEqual(result["execution_results"][0]["transactions"][0]["rpc_signature"], "rpc-signature-123")
        self.assertEqual(session.requests[0]["json"]["method"], "sendTransaction")
        self.assertEqual(session.requests[1]["json"]["method"], "getSignatureStatuses")
        self.assertEqual(FakeVersionedTransaction.signed_instances[0].message, {"decoded": b"\x01\x02\x03"})


if __name__ == "__main__":
    unittest.main()
