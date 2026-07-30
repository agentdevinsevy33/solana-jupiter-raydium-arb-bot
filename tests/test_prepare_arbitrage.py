import unittest
from types import SimpleNamespace
from unittest.mock import patch

from solders.pubkey import Pubkey

from bot import _risk_state, _update_risk_state, estimate_net_profit_bps, prepare_swap_execution

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


class FakePlan:
    def __init__(self, venue, public_key, txs):
        self.venue = venue
        self.public_key = public_key
        self.transaction_count = len(txs)
        self.transactions_base64 = txs
        self.metadata = {}


class FakeBuilder:
    def __init__(self, *args, **kwargs):
        pass

    def build_jupiter_swap_plan(self, *, public_key, quote_response, priority_fee_lamports=20_000):
        return FakePlan("jupiter", public_key, ["AQID"])

    def build_raydium_swap_plan(
        self, *, public_key, quote_response, wrap_sol=False, unwrap_sol=False,
        compute_unit_price_micro_lamports=50_000, input_account=None, output_account=None,
    ):
        return FakePlan("raydium", public_key, ["AQID"])


def make_quote(venue, input_mint, output_mint, in_amount, out_amount, raw=None):
    return {
        "venue": venue,
        "input_mint": input_mint,
        "output_mint": output_mint,
        "in_amount": in_amount,
        "out_amount": out_amount,
        "price_impact_pct": 0.0,
        "route_labels": ["X"],
        "fetched_at": "now",
        "metadata": {"raw_quote_response": raw or {}},
    }


def jup_raw(in_mint, in_amt, out_mint, out_amt):
    return {
        "inputMint": in_mint,
        "inAmount": str(in_amt),
        "outputMint": out_mint,
        "outAmount": str(out_amt),
        "otherAmountThreshold": str(out_amt),
        "swapMode": "ExactIn",
        "slippageBps": 50,
        "priceImpactPct": "0",
        "routePlan": [],
    }


def ray_raw(in_mint, in_amt, out_mint, out_amt):
    return {
        "success": True,
        "data": {
            "swapType": "BaseIn",
            "inputMint": in_mint,
            "inputAmount": str(in_amt),
            "outputMint": out_mint,
            "outputAmount": str(out_amt),
            "otherAmountThreshold": str(out_amt),
            "slippageBps": 50,
            "priceImpactPct": 0,
            "referrerAmount": "0",
            "routePlan": [],
        },
    }


def make_args(**overrides):
    args = SimpleNamespace(
        execute_min_profit_bps=10.0,
        priority_fee_lamports=20_000,
        raydium_compute_unit_price_micro_lamports=50_000,
        max_execute_opportunities=1,
        execute_slippage_buffer=0.01,
        execution_drift_buffer_bps=0.0,
        slippage_bps=0,
    )
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


VALID_PUBKEY = str(Pubkey.new_unique())


def fake_wallet():
    return SimpleNamespace(public_key=VALID_PUBKEY, to_public_dict=lambda: {"public_key": VALID_PUBKEY})


class FakeFreshClient:
    def __init__(self, venue, outputs):
        self.venue = venue
        self.outputs = outputs

    def get_quote(self, request):
        out_amount = self.outputs[(request.input_mint, request.output_mint)]
        raw = (
            ray_raw(request.input_mint, request.amount, request.output_mint, out_amount)
            if self.venue == "raydium"
            else jup_raw(request.input_mint, request.amount, request.output_mint, out_amount)
        )
        quote = make_quote(self.venue, request.input_mint, request.output_mint, request.amount, out_amount, raw=raw)
        return SimpleNamespace(out_amount=out_amount, to_dict=lambda: quote)


@patch("bot.ExecutionPlanBuilder", FakeBuilder)
class PrepareArbitrageTest(unittest.TestCase):
    def test_no_opportunities_prepares_nothing(self):
        args = make_args()
        result = {
            "scan": {
                "quotes": [make_quote("jupiter", SOL, USDC, 100, 100)],
                "opportunities": [],
            }
        }
        out = prepare_swap_execution(args, result, fake_wallet())
        self.assertEqual(out["prepared_swaps"], [])
        self.assertEqual(out["execution_skipped"], "no_opportunities")

    def test_gross_ok_but_net_negative_after_fees_is_skipped(self):
        # 0.25 SOL start, gross 11 bps, fee ~2 bps -> net 9 bps < 10 threshold.
        start = 250_000_000
        gross = 11.0
        end = start + int(start * gross / 10_000)
        opp = {
            "direction": "raydium_to_jupiter",
            "buy_venue": "raydium",
            "sell_venue": "jupiter",
            "start_amount": start,
            "intermediate_amount": 100,
            "end_amount": end,
            "profit_bps": gross,
        }
        quotes = [
            make_quote("raydium", SOL, USDC, start, 100, raw=ray_raw(SOL, start, USDC, 100)),
            make_quote("jupiter", SOL, USDC, start, 100, raw=jup_raw(SOL, start, USDC, 100)),
            make_quote("jupiter", USDC, SOL, 100, end, raw=jup_raw(USDC, 100, SOL, end)),
        ]
        result = {"scan": {"quotes": quotes, "opportunities": [opp]}}
        out = prepare_swap_execution(make_args(), result, fake_wallet())
        self.assertEqual(out["prepared_swaps"], [])
        self.assertEqual(out["execution_skipped"], "no_qualifying_opportunities")
        self.assertTrue(any(s["reason"] == "below_net_threshold_after_fees" for s in out["skipped_opportunities"]))

    def test_net_positive_opportunity_builds_two_leg_round_trip(self):
        start = 250_000_000
        gross = 50.0
        end = start + int(start * gross / 10_000)
        opp = {
            "direction": "raydium_to_jupiter",
            "buy_venue": "raydium",
            "sell_venue": "jupiter",
            "start_amount": start,
            "intermediate_amount": 100,
            "end_amount": end,
            "profit_bps": gross,
        }
        quotes = [
            make_quote("raydium", SOL, USDC, start, 100, raw=ray_raw(SOL, start, USDC, 100)),
            make_quote("jupiter", SOL, USDC, start, 100, raw=jup_raw(SOL, start, USDC, 100)),
            make_quote("jupiter", USDC, SOL, 100, end, raw=jup_raw(USDC, 100, SOL, end)),
        ]
        result = {"scan": {"quotes": quotes, "opportunities": [opp]}}
        clients = {
            "raydium": FakeFreshClient("raydium", {(SOL, USDC): 100}),
            "jupiter": FakeFreshClient("jupiter", {(USDC, SOL): end}),
        }
        with patch("bot._quote_client_for", side_effect=lambda venue: clients[venue]):
            out = prepare_swap_execution(make_args(), result, fake_wallet())
        self.assertEqual(len(out["prepared_swaps"]), 1)
        plan = out["prepared_swaps"][0]
        self.assertEqual(plan["venue"], "raydium_to_jupiter")
        # Only leg 1 is prebuilt. Leg 2 is built after confirmation from the
        # actual USDC balance delta.
        self.assertEqual(plan["transaction_count"], 1)
        self.assertEqual(len(plan["transactions_base64"]), 1)
        self.assertEqual(plan["metadata"]["deferred_leg_index"], 1)
        self.assertTrue(plan["metadata"]["legs"][1]["deferred"])
        self.assertIsNone(plan["metadata"]["legs"][1]["amount"])
        self.assertAlmostEqual(plan["metadata"]["gross_profit_bps"], 50.0, places=4)
        self.assertGreater(plan["metadata"]["est_net_profit_bps"], 10.0)
        self.assertIsNone(out["execution_skipped"])

    def test_estimate_net_profit_bps_math(self):
        # 0.25 SOL, priority 20000 lamports/tx, network 5000/tx -> fee 50000 lamports = 2.0 bps.
        opp = {"start_amount": 250_000_000, "profit_bps": 11.0}
        self.assertAlmostEqual(
            estimate_net_profit_bps(opp, priority_fee_lamports=20_000), 9.0, places=4
        )
        self.assertAlmostEqual(
            estimate_net_profit_bps(
                opp,
                priority_fee_lamports=20_000,
                slippage_bps=3,
                drift_buffer_bps=2,
            ),
            1.0,
            places=4,
        )
        # Zero start amount must not divide by zero.
        self.assertEqual(estimate_net_profit_bps({"start_amount": 0, "profit_bps": 5.0}, priority_fee_lamports=20_000), 5.0)

    def test_realized_loss_circuit_breaker_persists_after_two_losses(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(
                risk_state_path=str(Path(tmp) / "risk.json"),
                max_consecutive_losses=2,
                max_daily_loss_sol=1.0,
            )
            path, state = _risk_state(args)
            losing = {
                "execution_summary": {"completed": True},
                "execution_results": [
                    {
                        "transactions": [
                            {"err": None, "confirmation_status": "confirmed", "wallet_lamport_delta": -500}
                        ]
                    }
                ],
            }
            state = _update_risk_state(args, losing, path, state)
            self.assertFalse(state["halted"])
            state = _update_risk_state(args, losing, path, state)
            self.assertTrue(state["halted"])
            self.assertEqual(state["halt_reason"], "consecutive_loss_limit")
            _, reloaded = _risk_state(args)
            self.assertTrue(reloaded["halted"])

    def test_incomplete_round_trip_immediately_halts_risk_state(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(risk_state_path=str(Path(tmp) / "risk.json"))
            path, state = _risk_state(args)
            incomplete = {
                "execution_summary": {"completed": False},
                "execution_results": [
                    {
                        "metadata": {},
                        "transactions": [
                            {"err": None, "confirmation_status": "confirmed", "wallet_lamport_delta": -5000},
                            {"err": "leg 2 failed", "confirmation_status": None, "wallet_lamport_delta": None},
                        ],
                    }
                ],
            }
            state = _update_risk_state(args, incomplete, path, state)
            self.assertTrue(state["halted"])
            self.assertEqual(state["halt_reason"], "incomplete_round_trip")
            self.assertEqual(state["daily_loss_lamports"], 5000)


if __name__ == "__main__":
    unittest.main()
