from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class QuoteRequest:
    input_mint: str
    output_mint: str
    amount: int
    slippage_bps: int = 50
    input_symbol: str = ""
    output_symbol: str = ""
    input_decimals: int = 0
    output_decimals: int = 0


@dataclass(slots=True)
class QuoteSnapshot:
    venue: str
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    price_impact_pct: float
    route_labels: list[str]
    fetched_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OpportunityRecord:
    observed_at: str
    base_symbol: str
    quote_symbol: str
    direction: str
    start_amount: int
    intermediate_amount: int
    end_amount: int
    profit_lamports: int
    profit_bps: float
    buy_venue: str
    sell_venue: str
    buy_route_labels: list[str]
    sell_route_labels: list[str]
    buy_price_impact_pct: float
    sell_price_impact_pct: float
    evaluation_status: str = "pending"
    evaluation_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScanResult:
    scanned_at: str
    quotes: list[QuoteSnapshot]
    opportunities: list[OpportunityRecord]
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_at": self.scanned_at,
            "quotes": [quote.to_dict() for quote in self.quotes],
            "opportunities": [opportunity.to_dict() for opportunity in self.opportunities],
            "errors": list(self.errors),
        }
