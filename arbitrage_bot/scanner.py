from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from arbitrage_bot.detector import ArbitrageDetector
from arbitrage_bot.models import OpportunityRecord, QuoteRequest, QuoteSnapshot, ScanResult


class QuoteClient(Protocol):
    venue: str

    def get_quote(self, request: QuoteRequest) -> QuoteSnapshot: ...


class ArbitrageScanner:
    def __init__(
        self,
        *,
        base_symbol: str,
        quote_symbol: str,
        base_mint: str,
        quote_mint: str,
        start_amount: int,
        detector: ArbitrageDetector,
        raydium_client: QuoteClient,
        jupiter_client: QuoteClient,
        slippage_bps: int = 50,
    ) -> None:
        self.base_symbol = base_symbol
        self.quote_symbol = quote_symbol
        self.base_mint = base_mint
        self.quote_mint = quote_mint
        self.start_amount = start_amount
        self.detector = detector
        self.raydium_client = raydium_client
        self.jupiter_client = jupiter_client
        self.slippage_bps = slippage_bps

    def _request(self, input_mint: str, output_mint: str, amount: int) -> QuoteRequest:
        return QuoteRequest(
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount,
            slippage_bps=self.slippage_bps,
        )

    def scan_once(self) -> ScanResult:
        ray_forward = self.raydium_client.get_quote(
            self._request(self.base_mint, self.quote_mint, self.start_amount)
        )
        jup_forward = self.jupiter_client.get_quote(
            self._request(self.base_mint, self.quote_mint, self.start_amount)
        )
        ray_reverse = self.raydium_client.get_quote(
            self._request(self.quote_mint, self.base_mint, jup_forward.out_amount)
        )
        jup_reverse = self.jupiter_client.get_quote(
            self._request(self.quote_mint, self.base_mint, ray_forward.out_amount)
        )

        opportunities: list[OpportunityRecord] = []
        left_to_right = self.detector.evaluate_cycle(
            base_symbol=self.base_symbol,
            quote_symbol=self.quote_symbol,
            start_amount=self.start_amount,
            buy_quote=ray_forward,
            sell_quote=jup_reverse,
        )
        if left_to_right is not None:
            opportunities.append(left_to_right)

        right_to_left = self.detector.evaluate_cycle(
            base_symbol=self.base_symbol,
            quote_symbol=self.quote_symbol,
            start_amount=self.start_amount,
            buy_quote=jup_forward,
            sell_quote=ray_reverse,
        )
        if right_to_left is not None:
            opportunities.append(right_to_left)

        return ScanResult(
            scanned_at=datetime.now(timezone.utc).isoformat(),
            quotes=[ray_forward, jup_forward, ray_reverse, jup_reverse],
            opportunities=opportunities,
            errors=[],
        )
