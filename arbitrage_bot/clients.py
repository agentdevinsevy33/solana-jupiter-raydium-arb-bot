from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import requests

from arbitrage_bot.models import QuoteRequest, QuoteSnapshot


class QuoteClientError(RuntimeError):
    pass


class BaseHttpQuoteClient:
    venue: str = "unknown"

    def __init__(self, *, session: requests.Session | None = None, timeout: int = 15) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.session.get(
            url,
            params=params,
            timeout=self.timeout,
            headers={"User-Agent": "solana-jupiter-raydium-arb-bot/0.1"},
        )
        response.raise_for_status()
        payload = response.json()
        return payload


class JupiterQuoteClient(BaseHttpQuoteClient):
    venue = "jupiter"

    def __init__(self, *, dexes: list[str] | None = None, exclude_dexes: list[str] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.dexes = dexes or []
        self.exclude_dexes = exclude_dexes or []

    def get_quote(self, request: QuoteRequest) -> QuoteSnapshot:
        params: dict[str, Any] = {
            "inputMint": request.input_mint,
            "outputMint": request.output_mint,
            "amount": request.amount,
            "slippageBps": request.slippage_bps,
        }
        if self.dexes:
            params["dexes"] = ",".join(self.dexes)
        if self.exclude_dexes:
            params["excludeDexes"] = ",".join(self.exclude_dexes)

        payload = self._get_json("https://lite-api.jup.ag/swap/v1/quote", params)
        if "outAmount" not in payload:
            raise QuoteClientError(f"Unexpected Jupiter response: {payload}")
        route_labels = [leg["swapInfo"]["label"] for leg in payload.get("routePlan", [])]
        return QuoteSnapshot(
            venue=self.venue,
            input_mint=payload["inputMint"],
            output_mint=payload["outputMint"],
            in_amount=int(payload["inAmount"]),
            out_amount=int(payload["outAmount"]),
            price_impact_pct=float(payload.get("priceImpactPct") or 0.0),
            route_labels=route_labels,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "context_slot": payload.get("contextSlot"),
                "time_taken": payload.get("timeTaken"),
                "swap_usd_value": payload.get("swapUsdValue"),
            },
        )


class RaydiumQuoteClient(BaseHttpQuoteClient):
    venue = "raydium"

    def get_quote(self, request: QuoteRequest) -> QuoteSnapshot:
        params = {
            "inputMint": request.input_mint,
            "outputMint": request.output_mint,
            "amount": request.amount,
            "slippageBps": request.slippage_bps,
            "txVersion": "V0",
        }
        payload = self._get_json(
            "https://transaction-v1.raydium.io/compute/swap-base-in",
            params,
        )
        if not payload.get("success"):
            raise QuoteClientError(f"Raydium quote failed: {payload.get('msg', payload)}")
        data = payload["data"]
        route_labels = [leg.get("poolId", "unknown") for leg in data.get("routePlan", [])]
        return QuoteSnapshot(
            venue=self.venue,
            input_mint=data["inputMint"],
            output_mint=data["outputMint"],
            in_amount=int(data["inputAmount"]),
            out_amount=int(data["outputAmount"]),
            price_impact_pct=float(data.get("priceImpactPct") or 0.0),
            route_labels=route_labels,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "id": payload.get("id"),
                "version": payload.get("version"),
            },
        )


class OpportunityMonitor:
    def __init__(self, persistence_seconds: int = 45) -> None:
        self.persistence_seconds = persistence_seconds

    def evaluate_persistence(self, initial: QuoteSnapshot, follow_up: QuoteSnapshot) -> tuple[str, str]:
        if follow_up.out_amount >= initial.out_amount:
            return "persisted", f"spread still available after {self.persistence_seconds}s"
        delta_pct = ((follow_up.out_amount - initial.out_amount) / initial.out_amount) * 100 if initial.out_amount else 0.0
        return "expired", f"edge decayed by {delta_pct:.4f}% after {self.persistence_seconds}s"

    def wait(self) -> None:
        time.sleep(self.persistence_seconds)
