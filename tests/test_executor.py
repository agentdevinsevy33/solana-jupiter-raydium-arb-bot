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


class BuildSwapPlanQuoteSnapshotTest(unittest.TestCase):
    """Regression: _build_swap_plan must accept a live QuoteSnapshot object.

    rebuild_leg / _reverse_partial_plan pass QuoteSnapshot instances (from
    client.get_quote), while the prepare path passes dicts. The previous code
    did quote.get(...) unconditionally and raised AttributeError on a
    QuoteSnapshot, which crashed execute_plan and defeated mid-route recovery.
    """

    def test_build_swap_plan_accepts_quote_snapshot(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from arbitrage_bot.models import QuoteSnapshot
        from bot import _build_swap_plan

        fake_builder = MagicMock()
        fake_plan = MagicMock()
        fake_plan.transactions_base64 = ["tx1"]
        fake_plan.metadata = {}
        fake_builder.build_jupiter_swap_plan.return_value = fake_plan

        quote = QuoteSnapshot(
            venue="jupiter",
            input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTdt1v",
            output_mint="So11111111111111111111111111111111111111112",
            in_amount=1000,
            out_amount=9000,
            price_impact_pct=0.0,
            route_labels=["Meteora DLMM"],
            fetched_at="2026-07-23T00:00:00Z",
        )
        wallet = SimpleNamespace(public_key="WalletPubkey1111")

        out = _build_swap_plan(
            fake_builder,
            "jupiter",
            quote,
            wallet,
            priority_fee_lamports=20000,
            raydium_cu_price=50000,
            in_mint=quote.input_mint,
            out_mint=quote.output_mint,
            slippage_bps=50,
        )

        self.assertIs(out, fake_plan)
        _, kwargs = fake_builder.build_jupiter_swap_plan.call_args
        # The quote passed through must be a normalized dict, not a QuoteSnapshot.
        self.assertIsInstance(kwargs["quote_response"], dict)


class PartialRecoveryRegressionTest(unittest.TestCase):
    """Regression: a later-leg failure whose rebuild_leg raises must NOT crash.

    Reproduces the production failure: leg1 (SOL->USDC) confirms, leg2
    (USDC->SOL) fails at broadcast, and rebuild_leg raises (the QuoteSnapshot
    bug). execute_plan must swallow that, return a partial result, and let
    mid-route recovery sell the intermediate asset back -- never strand funds.
    """

    def test_execute_plan_returns_partial_when_rebuild_leg_raises(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        calls = {"sends": 0}

        class Session(FakeRpcSession):
            def post(self, url, json=None, timeout=None, headers=None):
                if json["method"] == "sendTransaction":
                    calls["sends"] += 1
                    if calls["sends"] == 1:
                        return super().post(url, json=json, timeout=timeout, headers=headers)
                    # Second send simulates the Jupiter simulation failure (0x1789).
                    payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {
                            "code": -32002,
                            "message": "Transaction simulation failed",
                            "data": {"err": {"InstructionError": [2, {"Custom": 6025}]}},
                        },
                    }

                    class Resp:
                        def raise_for_status(self):
                            return None

                        def json(self):
                            return payload

                    return Resp()
                return super().post(url, json=json, timeout=timeout, headers=headers)

        def boom(plan, index):
            raise AttributeError("'QuoteSnapshot' object has no attribute 'get'")

        with tempfile.TemporaryDirectory() as tmp:
            wallet = create_devnet_wallet(Path(tmp) / "wallet.json")
            executor = TradeExecutor(
                rpc_url="https://example-rpc.invalid",
                session=Session(),
                confirm_timeout_seconds=0.1,
                poll_interval_seconds=0.0,
                rebuild_leg=boom,
                max_leg_retries=1,
            )
            plan = {
                "venue": "raydium_to_jupiter",
                "public_key": wallet.public_key,
                "transactions_base64": ["AQID", "BAIF"],
                "metadata": {
                    "legs": [
                        {"in_mint": "x", "out_mint": "y"},
                        {"in_mint": "y", "out_mint": "x"},
                    ]
                },
            }
            with patch.object(TradeExecutor, "_load_solders", return_value=(FakeKeypair, FakeVersionedTransaction)):
                # Must not raise; must return a partial result.
                result = executor.execute_prepared_swaps(wallet, [plan])

        self.assertEqual(len(result["execution_results"]), 1)
        plan_result = result["execution_results"][0]
        self.assertFalse(plan_result["ok"])
        self.assertTrue(plan_result["partial"])  # 1 of 2 legs confirmed
        self.assertIsNone(plan_result["transactions"][1]["rpc_signature"])
        self.assertIn("QuoteSnapshot", plan_result["transactions"][1]["err"])


if __name__ == "__main__":
    unittest.main()
