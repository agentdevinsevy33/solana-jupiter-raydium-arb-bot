from __future__ import annotations

from dataclasses import dataclass

SOL_MINT = "So11111111111111111111111111111111111111112"
ETH_MINT = "2FPyTwcZLUg1MDrwsyoP4D6s1tM7hAkHYRjkNb5w6Pxk"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4uJ8V4aHcRUW2YCiMzFx"

KNOWN_ETH_MINTS = {
    "sollet_eth": ETH_MINT,
    "wormhole_weth": "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
}


@dataclass(frozen=True, slots=True)
class TokenDefinition:
    symbol: str
    mint: str
    decimals: int


TOKEN_DEFAULTS = {
    "SOL": TokenDefinition(symbol="SOL", mint=SOL_MINT, decimals=9),
    "ETH": TokenDefinition(symbol="ETH", mint=ETH_MINT, decimals=6),
    "USDC": TokenDefinition(symbol="USDC", mint=USDC_MINT, decimals=6),
    "USDT": TokenDefinition(symbol="USDT", mint=USDT_MINT, decimals=6),
}


def resolve_token(*, symbol: str, mint: str | None = None, decimals: int | None = None) -> TokenDefinition:
    normalized = symbol.upper()
    default = TOKEN_DEFAULTS.get(normalized)
    if default is None and mint is None:
        raise KeyError(f"Unknown token symbol: {symbol}")
    return TokenDefinition(
        symbol=normalized,
        mint=mint or (default.mint if default else ""),
        decimals=decimals if decimals is not None else (default.decimals if default else 0),
    )
