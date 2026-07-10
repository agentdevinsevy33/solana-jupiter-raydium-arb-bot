from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from arbitrage_bot.detector import ArbitrageDetector
from arbitrage_bot.models import QuoteRequest, QuoteSnapshot, ScanResult


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
        base_decimals: int = 9,
        quote_decimals: int = 6,
        start_amount: int,
        detector: ArbitrageDetector,
        left_client: QuoteClient,
        right_client: QuoteClient,
        slippage_bps: int = 50,
    ) -> None:
        self.base_symbol = base_symbol
        self.quote_symbol = quote_symbol
        self.base_mint = base_mint
        self.quote_mint = quote_mint
        self.base_decimals = base_decimals
        self.quote_decimals = quote_decimals
        self.start_amount = start_amount
        self.detector = detector
        self.left_client = left_client
        self.right_client = right_client
        self.slippage_bps = slippage_bps

    def _request(self, input_mint: str, output_mint: str, amount: int) -> QuoteRequest:
        if input_mint == self.base_mint:
            input_symbol = self.base_symbol
            input_decimals = self.base_decimals
        else:
            input_symbol = self.quote_symbol
            input_decimals = self.quote_decimals
        if output_mint == self.base_mint:
            output_symbol = self.base_symbol
            output_decimals = self.base_decimals
        else:
            output_symbol = self.quote_symbol
            output_decimals = self.quote_decimals
        return QuoteRequest(
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount,
            slippage_bps=self.slippage_bps,
            input_symbol=input_symbol,
            output_symbol=output_symbol,
            input_decimals=input_decimals,
            output_decimals=output_decimals,
        )

    def scan_once(self) -> ScanResult:
        left_forward = self.left_client.get_quote(
            self._request(self.base_mint, self.quote_mint, self.start_amount)
        )
        right_forward = self.right_client.get_quote(
            self._request(self.base_mint, self.quote_mint, self.start_amount)
        )
        left_reverse = self.left_client.get_quote(
            self._request(self.quote_mint, self.base_mint, right_forward.out_amount)
        )
        right_reverse = self.right_client.get_quote(
            self._request(self.quote_mint, self.base_mint, left_forward.out_amount)
        )

        opportunities = []
        left_to_right = self.detector.evaluate_cycle(
            base_symbol=self.base_symbol,
            quote_symbol=self.quote_symbol,
            start_amount=self.start_amount,
            buy_quote=left_forward,
            sell_quote=right_reverse,
        )
        if left_to_right is not None:
            opportunities.append(left_to_right)

        right_to_left = self.detector.evaluate_cycle(
            base_symbol=self.base_symbol,
            quote_symbol=self.quote_symbol,
            start_amount=self.start_amount,
            buy_quote=right_forward,
            sell_quote=left_reverse,
        )
        if right_to_left is not None:
            opportunities.append(right_to_left)

        return ScanResult(
            scanned_at=datetime.now(timezone.utc).isoformat(),
            quotes=[left_forward, right_forward, left_reverse, right_reverse],
            opportunities=opportunities,
            errors=[],
        )
