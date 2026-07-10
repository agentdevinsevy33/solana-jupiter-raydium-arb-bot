from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from arbitrage_bot.analytics import AnalyticsEngine
from arbitrage_bot.clients import (
    JupiterQuoteClient,
    OrcaQuoteClient,
    QuoteClientError,
    RaydiumQuoteClient,
)
from arbitrage_bot.dashboard import DashboardWriter
from arbitrage_bot.detector import ArbitrageDetector
from arbitrage_bot.execution import ExecutionPlanBuilder
from arbitrage_bot.runtime import BotRuntime
from arbitrage_bot.scanner import ArbitrageScanner
from arbitrage_bot.token_config import resolve_token
from arbitrage_bot.wallet import SolanaWallet, create_devnet_wallet, load_wallet

LAMPORTS_PER_SOL = 1_000_000_000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor Solana arbitrage opportunities across configurable venues")
    parser.add_argument("--once", action="store_true", help="Run a single scan and exit")
    parser.add_argument("--interval", type=int, default=0, help="Polling interval in seconds")
    parser.add_argument("--amount-sol", type=float, default=0.1, help="Legacy shorthand for base amount when base token is SOL")
    parser.add_argument("--amount", type=float, default=None, help="Trade size in token units for the selected amount side")
    parser.add_argument("--amount-units", choices=["base", "quote"], default="base", help="Whether --amount refers to the base or quote token")
    parser.add_argument("--base-symbol", default="SOL", help="Base token symbol")
    parser.add_argument("--quote-symbol", default="ETH", help="Quote token symbol")
    parser.add_argument("--base-mint", default=None, help="Override base token mint")
    parser.add_argument("--quote-mint", default=None, help="Override quote token mint")
    parser.add_argument("--base-decimals", type=int, default=None, help="Override base token decimals")
    parser.add_argument("--quote-decimals", type=int, default=None, help="Override quote token decimals")
    parser.add_argument("--left-venue", choices=["raydium", "jupiter", "orca"], default="raydium", help="Venue used for the left side of the comparison")
    parser.add_argument("--right-venue", choices=["raydium", "jupiter", "orca"], default="jupiter", help="Venue used for the right side of the comparison")
    parser.add_argument("--slippage-bps", type=int, default=50, help="Slippage tolerance in basis points")
    parser.add_argument("--min-profit-bps", type=float, default=5.0, help="Minimum profit in basis points")
    parser.add_argument("--db-path", default="data/arbitrage.db", help="SQLite path")
    parser.add_argument("--monitor-seconds", type=int, default=0, help="Seconds to wait before re-checking an opportunity")
    parser.add_argument(
        "--jupiter-exclude-raydium",
        action="store_true",
        help="Exclude Raydium liquidity from Jupiter quotes for a cleaner comparison",
    )
    parser.add_argument("--jupiter-dexes", default="", help="Comma-separated Jupiter dex allowlist")
    parser.add_argument("--jupiter-exclude-dexes", default="", help="Comma-separated Jupiter dex blocklist")
    parser.add_argument("--alert-min-bps", type=float, default=0.0, help="Only emit alerts at or above this profit threshold")
    parser.add_argument("--dashboard-output", default="", help="Optional HTML dashboard output path")
    parser.add_argument("--mode", choices=["monitor", "prepare-swaps"], default="monitor", help="Run as a pure monitor or also prepare unsigned swap transactions for review")
    parser.add_argument("--wallet-path", default="", help="Optional JSON wallet path for devnet/mainnet transaction preparation")
    parser.add_argument("--network", choices=["devnet", "mainnet-beta"], default="devnet", help="Target Solana cluster for wallet metadata and dry-run prep")
    parser.add_argument("--max-cycles", type=int, default=0, help="Optional cap for loop iterations when running continuously")
    return parser.parse_args(argv)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_venue_client(venue: str, args: argparse.Namespace):
    if venue == "raydium":
        return RaydiumQuoteClient()
    if venue == "orca":
        return OrcaQuoteClient()
    if venue == "jupiter":
        exclude = _split_csv(getattr(args, "jupiter_exclude_dexes", ""))
        if getattr(args, "jupiter_exclude_raydium", False) and "Raydium" not in exclude:
            exclude.append("Raydium")
        dexes = _split_csv(getattr(args, "jupiter_dexes", ""))
        return JupiterQuoteClient(dexes=dexes, exclude_dexes=exclude)
    raise ValueError(f"Unsupported venue: {venue}")


def _resolve_amount(args: argparse.Namespace, *, base_decimals: int, quote_decimals: int) -> int:
    amount_units = getattr(args, "amount_units", "base") or "base"
    amount = getattr(args, "amount", None)
    if amount is None:
        amount = getattr(args, "amount_sol", 0.1)
    decimals = base_decimals if amount_units == "base" else quote_decimals
    value = int(amount * (10**decimals))
    return max(value, 1)


def build_scanner(args: argparse.Namespace) -> ArbitrageScanner:
    base_token = resolve_token(
        symbol=getattr(args, "base_symbol", "SOL"),
        mint=getattr(args, "base_mint", None),
        decimals=getattr(args, "base_decimals", None),
    )
    quote_token = resolve_token(
        symbol=getattr(args, "quote_symbol", "ETH"),
        mint=getattr(args, "quote_mint", None),
        decimals=getattr(args, "quote_decimals", None),
    )
    detector = ArbitrageDetector(min_profit_bps=args.min_profit_bps)
    start_amount = _resolve_amount(args, base_decimals=base_token.decimals, quote_decimals=quote_token.decimals)
    return ArbitrageScanner(
        base_symbol=base_token.symbol,
        quote_symbol=quote_token.symbol,
        base_mint=base_token.mint,
        quote_mint=quote_token.mint,
        base_decimals=base_token.decimals,
        quote_decimals=quote_token.decimals,
        start_amount=start_amount,
        detector=detector,
        left_client=_build_venue_client(args.left_venue, args),
        right_client=_build_venue_client(args.right_venue, args),
        slippage_bps=args.slippage_bps,
    )


def run_once(args: argparse.Namespace) -> dict:
    scanner = build_scanner(args)
    runtime = BotRuntime.from_components(
        scanner=scanner,
        db_path=Path(args.db_path),
        min_alert_bps=args.alert_min_bps,
    )
    result = runtime.run_cycle(monitor_seconds=args.monitor_seconds)
    left_venue = getattr(getattr(scanner, "left_client", None), "venue", None)
    right_venue = getattr(getattr(scanner, "right_client", None), "venue", None)
    if result["scan"]["opportunities"] and left_venue and right_venue:
        left_to_right = next((item for item in result["scan"]["opportunities"] if item["direction"] == f"{left_venue}_to_{right_venue}"), None)
        right_to_left = next((item for item in result["scan"]["opportunities"] if item["direction"] == f"{right_venue}_to_{left_venue}"), None)
    else:
        left_to_right = None
        right_to_left = None
    result["experiment_metrics"] = {
        "left_to_right_profit_bps": left_to_right["profit_bps"] if left_to_right else None,
        "right_to_left_profit_bps": right_to_left["profit_bps"] if right_to_left else None,
        "pair": f"{scanner.base_symbol}/{scanner.quote_symbol}",
        "left_venue": left_venue,
        "right_venue": right_venue,
        "amount": getattr(scanner, "start_amount", None),
        "slippage_bps": getattr(scanner, "slippage_bps", None),
    }
    result["production_config"] = {
        "pair": f"{scanner.base_symbol}/{scanner.quote_symbol}",
        "base_symbol": scanner.base_symbol,
        "quote_symbol": scanner.quote_symbol,
        "left_venue": left_venue,
        "right_venue": right_venue,
        "amount": getattr(scanner, "start_amount", None),
        "slippage_bps": getattr(scanner, "slippage_bps", None),
        "min_profit_bps": getattr(args, "min_profit_bps", None),
        "monitor_seconds": getattr(args, "monitor_seconds", None),
        "alert_min_bps": getattr(args, "alert_min_bps", None),
        "mode": getattr(args, "mode", "monitor"),
        "network": getattr(args, "network", None),
    }
    if args.dashboard_output:
        engine = AnalyticsEngine(runtime.storage)
        heartbeat = engine.build_heartbeat(latest_result=result)
        writer = DashboardWriter(Path(args.dashboard_output), pair_label=f"{scanner.base_symbol}/{scanner.quote_symbol}")
        result["dashboard_path"] = writer.write(
            engine,
            limit=250,
            heartbeat=heartbeat,
            config=result["production_config"],
        )
    return result


def ensure_wallet(args: argparse.Namespace) -> SolanaWallet | None:
    wallet_path = getattr(args, "wallet_path", "") or ""
    if not wallet_path:
        return None
    path = Path(wallet_path)
    network = getattr(args, "network", "devnet")
    if path.exists():
        return load_wallet(path, network=network)
    if network != "devnet":
        raise FileNotFoundError(f"Wallet file does not exist: {path}")
    return create_devnet_wallet(path, network=network)


def prepare_swap_execution(args: argparse.Namespace, result: dict, wallet: SolanaWallet) -> dict:
    builder = ExecutionPlanBuilder()
    quotes = result.get("scan", {}).get("quotes", [])
    plans: list[dict] = []
    seen_venues: set[str] = set()
    quotes_by_venue_and_input = {
        (quote.get("venue", ""), quote.get("input_mint", "")): quote for quote in quotes
    }

    base_mint = quotes[0].get("input_mint") if quotes else ""
    for venue in sorted({quote.get("venue") for quote in quotes if quote.get("venue") in {"jupiter", "raydium"}}):
        if venue in seen_venues:
            continue
        forward_quote = quotes_by_venue_and_input.get((venue, base_mint))
        if forward_quote is None:
            continue
        if venue == "jupiter":
            quote_response = forward_quote.get("metadata", {}).get("raw_quote_response") or {
                "inputMint": forward_quote["input_mint"],
                "inAmount": str(forward_quote["in_amount"]),
                "outputMint": forward_quote["output_mint"],
                "outAmount": str(forward_quote["out_amount"]),
                "otherAmountThreshold": str(forward_quote["out_amount"]),
                "swapMode": "ExactIn",
                "slippageBps": getattr(args, "slippage_bps", 50),
                "priceImpactPct": str(forward_quote.get("price_impact_pct", 0.0)),
                "routePlan": [{"swapInfo": {"label": label}} for label in forward_quote.get("route_labels", [])],
            }
            plan = builder.build_jupiter_swap_plan(public_key=wallet.public_key, quote_response=quote_response)
        else:
            quote_response = forward_quote.get("metadata", {}).get("raw_quote_response") or {
                "success": True,
                "data": {
                    "swapType": "BaseIn",
                    "inputMint": forward_quote["input_mint"],
                    "inputAmount": str(forward_quote["in_amount"]),
                    "outputMint": forward_quote["output_mint"],
                    "outputAmount": str(forward_quote["out_amount"]),
                    "otherAmountThreshold": str(forward_quote["out_amount"]),
                    "slippageBps": getattr(args, "slippage_bps", 50),
                    "priceImpactPct": forward_quote.get("price_impact_pct", 0.0),
                    "referrerAmount": "0",
                    "routePlan": [
                        {
                            "poolId": label,
                            "inputMint": forward_quote["input_mint"],
                            "outputMint": forward_quote["output_mint"],
                            "feeAmount": "0",
                            "feeMint": forward_quote["input_mint"],
                        }
                        for label in forward_quote.get("route_labels", [])
                    ],
                },
            }
            plan = builder.build_raydium_swap_plan(
                public_key=wallet.public_key,
                quote_response=quote_response,
                wrap_sol=forward_quote["input_mint"] == "So11111111111111111111111111111111111111112",
                unwrap_sol=forward_quote["output_mint"] == "So11111111111111111111111111111111111111112",
            )
        plans.append(plan.to_dict())
        seen_venues.add(venue)

    return {
        "wallet": wallet.to_public_dict(),
        "prepared_swaps": plans,
    }


def _augment_result_with_execution_preparation(args: argparse.Namespace, result: dict) -> dict:
    if getattr(args, "mode", "monitor") != "prepare-swaps":
        return result
    wallet = ensure_wallet(args)
    if wallet is None:
        raise ValueError("--wallet-path is required when --mode prepare-swaps is used")
    result.update(prepare_swap_execution(args, result, wallet))
    return result


def main() -> int:
    args = parse_args()
    try:
        if args.once or args.interval <= 0:
            result = run_once(args)
            result = _augment_result_with_execution_preparation(args, result)
            print(json.dumps(result, indent=2))
            return 0

        scanner = build_scanner(args)
        runtime = BotRuntime.from_components(
            scanner=scanner,
            db_path=Path(args.db_path),
            min_alert_bps=args.alert_min_bps,
        )
        loop_results = runtime.run_loop(
            interval_seconds=args.interval,
            max_cycles=args.max_cycles if args.max_cycles > 0 else None,
            monitor_seconds=args.monitor_seconds,
        )
        for result in loop_results:
            result = _augment_result_with_execution_preparation(args, result)
            print(json.dumps(result, indent=2))
            for alert in result.get("alerts", []):
                print(f"ALERT: {alert}")
        return 0
    except QuoteClientError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
