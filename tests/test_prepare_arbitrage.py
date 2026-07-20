import unittest
from types import SimpleNamespace
from unittest.mock import patch

from solders.pubkey import Pubkey

from bot import estimate_net_profit_bps, prepare_swap_execution

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
        slippage_bps=50,
    )
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


VALID_PUBKEY = str(Pubkey.new_unique())


def fake_wallet():
    return SimpleNamespace(public_key=VALID_PUBKEY, to_public_dict=lambda: {"public_key": VALID_PUBKEY})


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
        out = prepare_swap_execution(make_args(), result, fake_wallet())
        self.assertEqual(len(out["prepared_swaps"]), 1)
        plan = out["prepared_swaps"][0]
        self.assertEqual(plan["venue"], "raydium_to_jupiter")
        # Round trip = 2 transactions: buy leg + sell leg.
        self.assertEqual(plan["transaction_count"], 2)
        self.assertEqual(len(plan["transactions_base64"]), 2)
        self.assertAlmostEqual(plan["metadata"]["gross_profit_bps"], 50.0, places=4)
        self.assertGreater(plan["metadata"]["est_net_profit_bps"], 10.0)
        self.assertIsNone(out["execution_skipped"])

    def test_estimate_net_profit_bps_math(self):
        # 0.25 SOL, priority 20000 lamports/tx, network 5000/tx -> fee 50000 lamports = 2.0 bps.
        opp = {"start_amount": 250_000_000, "profit_bps": 11.0}
        self.assertAlmostEqual(
            estimate_net_profit_bps(opp, priority_fee_lamports=20_000), 9.0, places=4
        )
        # Zero start amount must not divide by zero.
        self.assertEqual(estimate_net_profit_bps({"start_amount": 0, "profit_bps": 5.0}, priority_fee_lamports=20_000), 5.0)


if __name__ == "__main__":
    unittest.main()
