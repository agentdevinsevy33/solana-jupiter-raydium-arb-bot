from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import requests


class ExecutionPlanError(RuntimeError):
    pass


@dataclass(slots=True)
class ExecutionPlan:
    venue: str
    public_key: str
    transaction_count: int
    transactions_base64: list[str]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "public_key": self.public_key,
            "transaction_count": self.transaction_count,
            "transactions_base64": list(self.transactions_base64),
            "metadata": dict(self.metadata),
        }


class _BaseExecutionClient:
    def __init__(self, *, session: requests.Session | None = None, timeout: int = 20) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            url,
            json=payload,
            timeout=self.timeout,
            headers={"Content-Type": "application/json", "User-Agent": "solana-jupiter-raydium-arb-bot/0.1"},
        )
        response.raise_for_status()
        return response.json()


class ExecutionPlanBuilder:
    def __init__(
        self,
        *,
        jupiter_session: requests.Session | None = None,
        raydium_session: requests.Session | None = None,
        timeout: int = 20,
    ) -> None:
        self._jupiter = _BaseExecutionClient(session=jupiter_session, timeout=timeout)
        self._raydium = _BaseExecutionClient(session=raydium_session, timeout=timeout)

    def build_jupiter_swap_plan(
        self, *, public_key: str, quote_response: dict[str, Any], priority_fee_lamports: int = 20_000
    ) -> ExecutionPlan:
        # NOTE: priority fee is a small FIXED lamport amount, not "veryHigh".
        # At 0.1-0.25 SOL trade sizes a veryHigh/1_000_000-lamport fee (~100 bps per
        # swap) guarantees a loss regardless of any arbitrage spread. Execution only
        # fires when a detected opportunity is net-profitable after this fee.
        payload = {
            "userPublicKey": public_key,
            "quoteResponse": quote_response,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": int(priority_fee_lamports),
        }
        response = self._jupiter._post_json("https://api.jup.ag/swap/v1/swap", payload)
        transaction = response.get("swapTransaction")
        if not transaction:
            raise ExecutionPlanError(f"Unexpected Jupiter swap response: {response}")
        return ExecutionPlan(
            venue="jupiter",
            public_key=public_key,
            transaction_count=1,
            transactions_base64=[transaction],
            metadata={
                "lastValidBlockHeight": response.get("lastValidBlockHeight"),
                "prioritizationFeeLamports": response.get("prioritizationFeeLamports"),
                "dynamicSlippageReport": response.get("dynamicSlippageReport"),
            },
        )

    def build_raydium_swap_plan(
        self,
        *,
        public_key: str,
        quote_response: dict[str, Any],
        wrap_sol: bool,
        unwrap_sol: bool,
        compute_unit_price_micro_lamports: int = 50_000,
        tx_version: str = "V0",
        input_account: str | None = None,
        output_account: str | None = None,
    ) -> ExecutionPlan:
        swap_response = quote_response
        if "success" not in swap_response and "data" in swap_response:
            swap_response = quote_response["data"]
        payload = {
            "computeUnitPriceMicroLamports": str(compute_unit_price_micro_lamports),
            "swapResponse": swap_response,
            "txVersion": tx_version,
            "wallet": public_key,
            "wrapSol": wrap_sol,
            "unwrapSol": unwrap_sol,
        }
        if input_account:
            payload["inputAccount"] = input_account
        if output_account:
            payload["outputAccount"] = output_account
        response = self._raydium._post_json(
            "https://transaction-v1.raydium.io/transaction/swap-base-in",
            payload,
        )
        if not response.get("success"):
            raise ExecutionPlanError(f"Unexpected Raydium swap response: {response}")
        entries = response.get("data") or []
        transactions = [entry["transaction"] for entry in entries if entry.get("transaction")]
        if not transactions:
            raise ExecutionPlanError(f"Raydium response did not include transactions: {response}")
        return ExecutionPlan(
            venue="raydium",
            public_key=public_key,
            transaction_count=len(transactions),
            transactions_base64=transactions,
            metadata={
                "id": response.get("id"),
                "version": response.get("version"),
            },
        )
