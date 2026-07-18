from __future__ import annotations

import argparse
import json
import time
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
from arbitrage_bot.execution import ExecutionPlanBuilder, ExecutionPlanError
from arbitrage_bot.executor import TradeExecutor
from arbitrage_bot.runtime import BotRuntime
from arbitrage_bot.scanner import ArbitrageScanner
from arbitrage_bot.token_config import resolve_token
from arbitrage_bot.wallet import SolanaWallet, create_devnet_wallet, load_wallet

LAMPORTS_PER_SOL = 1_000_000_000
SOL_MINT = "So11111111111111111111111111111111111111112"
# Conservative per-transaction network fee estimate (Solana base fee = 5000 lamports/sig).
NETWORK_FEE_LAMPORTS_PER_TX = 5_000


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
    parser.add_argument("--mode", choices=["monitor", "prepare-swaps", "execute-swaps"], default="monitor", help="Run as a pure monitor, prepare unsigned swap transactions for review, or sign/send prepared swaps")
    parser.add_argument("--wallet-path", default="", help="Optional JSON wallet path for devnet/mainnet transaction preparation")
    parser.add_argument("--network", choices=["devnet", "mainnet-beta"], default="devnet", help="Target Solana cluster for wallet metadata and dry-run prep")
    parser.add_argument("--rpc-url", default="", help="Solana RPC URL used for execute-swaps mode")
    parser.add_argument("--confirm-timeout-seconds", type=float, default=30.0, help="How long execute-swaps waits for confirmation before failing")
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0, help="Polling interval used while waiting for transaction confirmation")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip Solana RPC preflight checks in execute-swaps mode")
    parser.add_argument("--commitment", choices=["processed", "confirmed", "finalized"], default="confirmed", help="Commitment level required before execute-swaps considers a transaction settled")
    parser.add_argument("--max-send-retries", type=int, default=3, help="Maximum RPC retries when broadcasting signed transactions")
    parser.add_argument(
        "--execute-min-profit-bps",
        type=float,
        default=10.0,
        help="Minimum NET profit (after fees) in bps required before the executor will act on a detected opportunity",
    )
    parser.add_argument(
        "--priority-fee-lamports",
        type=int,
        default=20_000,
        help="Fixed per-transaction Solana priority fee in lamports for execute-swaps (kept small; execution only fires on net-profitable opportunities)",
    )
    parser.add_argument(
        "--raydium-compute-unit-price-micro-lamports",
        type=int,
        default=50_000,
        help="Raydium swap compute-unit price in micro-lamports",
    )
    parser.add_argument(
        "--max-execute-opportunities",
        type=int,
        default=1,
        help="Maximum number of opportunities the executor will act on per scan",
    )
    parser.add_argument(
        "--execute-slippage-buffer",
        type=float,
        default=0.01,
        help="Fraction to reduce the reverse-leg input by to stay safe against forward-leg slippage",
    )
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


def _reconstruct_quote_response(quote: dict, slippage_bps: int = 50) -> dict:
    """Fallback quote-response payload when metadata.raw_quote_response is missing."""
    venue = quote.get("venue")
    if venue == "jupiter":
        return {
            "inputMint": quote["input_mint"],
            "inAmount": str(quote["in_amount"]),
            "outputMint": quote["output_mint"],
            "outAmount": str(quote["out_amount"]),
            "otherAmountThreshold": str(quote["out_amount"]),
            "swapMode": "ExactIn",
            "slippageBps": slippage_bps,
            "priceImpactPct": str(quote.get("price_impact_pct", 0.0)),
            "routePlan": [{"swapInfo": {"label": label}} for label in quote.get("route_labels", [])],
        }
    return {
        "success": True,
        "data": {
            "swapType": "BaseIn",
            "inputMint": quote["input_mint"],
            "inputAmount": str(quote["in_amount"]),
            "outputMint": quote["output_mint"],
            "outputAmount": str(quote["out_amount"]),
            "otherAmountThreshold": str(quote["out_amount"]),
            "slippageBps": slippage_bps,
            "priceImpactPct": quote.get("price_impact_pct", 0.0),
            "referrerAmount": "0",
            "routePlan": [
                {
                    "poolId": label,
                    "inputMint": quote["input_mint"],
                    "outputMint": quote["output_mint"],
                    "feeAmount": "0",
                    "feeMint": quote["input_mint"],
                }
                for label in quote.get("route_labels", [])
            ],
        },
    }


def _buffer_quote_input(quote: dict, buffer: float) -> dict:
    """Return a raw_quote_response copy with the input amount reduced by ``buffer``.
    Used for the reverse leg so we never ask to swap more than the forward leg actually
    returned (forward-leg slippage safety)."""
    raw = dict(quote.get("metadata", {}).get("raw_quote_response") or _reconstruct_quote_response(quote))
    factor = 1.0 - float(buffer)
    if "inAmount" in raw:
        raw["inAmount"] = str(int(int(raw["inAmount"]) * factor))
    data = raw.get("data")
    if isinstance(data, dict) and "inputAmount" in data:
        data["inputAmount"] = str(int(int(data["inputAmount"]) * factor))
    return raw


def _build_swap_plan(
    builder: ExecutionPlanBuilder,
    venue: str,
    quote: dict,
    wallet: SolanaWallet,
    *,
    priority_fee_lamports: int,
    raydium_cu_price: int,
    in_mint: str,
    out_mint: str,
    slippage_bps: int,
) -> "object":
    raw = quote.get("metadata", {}).get("raw_quote_response") or _reconstruct_quote_response(quote, slippage_bps)
    if venue == "jupiter":
        return builder.build_jupiter_swap_plan(
            public_key=wallet.public_key,
            quote_response=raw,
            priority_fee_lamports=priority_fee_lamports,
        )
    if venue == "raydium":
        return builder.build_raydium_swap_plan(
            public_key=wallet.public_key,
            quote_response=raw,
            wrap_sol=(in_mint == SOL_MINT),
            unwrap_sol=(out_mint == SOL_MINT),
            compute_unit_price_micro_lamports=raydium_cu_price,
        )
    raise ExecutionPlanError(f"Execution is not supported for venue '{venue}' (only jupiter and raydium are executable)")


def estimate_net_profit_bps(
    opp: dict, *, priority_fee_lamports: int, network_fee_lamports: int = NETWORK_FEE_LAMPORTS_PER_TX
) -> float:
    """Gross opportunity profit minus estimated round-trip transaction fees, in bps."""
    start = opp.get("start_amount") or 0
    gross_bps = opp.get("profit_bps", 0.0)
    # Round trip = 2 swaps: network fee + priority fee on each.
    fee_lamports = 2 * (network_fee_lamports + priority_fee_lamports)
    fee_bps = (fee_lamports / start) * 10_000 if start else 0.0
    return gross_bps - fee_bps


def prepare_swap_execution(args: argparse.Namespace, result: dict, wallet: SolanaWallet) -> dict:
    """Build swap plans for arbitrage execution, GATED on detected profitable opportunities.

    Critical safety properties (vs. the old implementation which blindly sold SOL):
    - Only acts when ``scan.opportunities`` contains a qualifying opportunity.
    - Each plan is a full round trip: buy base->quote on the buy venue, then sell
      quote->base on the sell venue (the actual arbitrage cycle).
    - Requires the opportunity to be NET-profitable after estimated fees.
    - If nothing qualifies, returns an empty ``prepared_swaps`` list so the executor
      broadcasts nothing.
    """
    scan = result.get("scan", {})
    quotes = scan.get("quotes", [])
    opportunities = scan.get("opportunities", [])
    if not quotes:
        return {"wallet": wallet.to_public_dict(), "prepared_swaps": [], "execution_skipped": "no_quotes"}
    if not opportunities:
        return {"wallet": wallet.to_public_dict(), "prepared_swaps": [], "execution_skipped": "no_opportunities"}

    quotes_by_venue_input = {(q["venue"], q["input_mint"]): q for q in quotes}
    base_mint = quotes[0]["input_mint"]
    quote_mint = quotes[0]["output_mint"]
    execute_min_profit_bps = float(getattr(args, "execute_min_profit_bps", 10.0))
    priority_fee_lamports = int(getattr(args, "priority_fee_lamports", 20_000))
    raydium_cu_price = int(getattr(args, "raydium_compute_unit_price_micro_lamports", 50_000))
    max_opps = int(getattr(args, "max_execute_opportunities", 1))
    slippage_buffer = float(getattr(args, "execute_slippage_buffer", 0.01))
    slippage_bps = int(getattr(args, "slippage_bps", 50))

    builder = ExecutionPlanBuilder()
    plans: list[dict] = []
    skipped: list[dict] = []

    for opp in opportunities:
        if len(plans) >= max_opps:
            break
        gross_bps = opp.get("profit_bps", 0.0)
        if gross_bps < execute_min_profit_bps:
            skipped.append({"direction": opp.get("direction"), "reason": "below_gross_threshold", "gross_profit_bps": gross_bps})
            continue
        net_bps = estimate_net_profit_bps(opp, priority_fee_lamports=priority_fee_lamports)
        if net_bps < execute_min_profit_bps:
            skipped.append(
                {
                    "direction": opp.get("direction"),
                    "reason": "below_net_threshold_after_fees",
                    "gross_profit_bps": gross_bps,
                    "est_net_profit_bps": net_bps,
                }
            )
            continue
        buy_venue = opp.get("buy_venue")
        sell_venue = opp.get("sell_venue")
        buy_quote = quotes_by_venue_input.get((buy_venue, base_mint))
        sell_quote = quotes_by_venue_input.get((sell_venue, quote_mint))
        if not buy_quote or not sell_quote:
            skipped.append(
                {
                    "direction": opp.get("direction"),
                    "reason": "missing_quote_for_leg",
                    "buy_venue": buy_venue,
                    "sell_venue": sell_venue,
                }
            )
            continue
        try:
            leg1 = _build_swap_plan(
                builder,
                buy_venue,
                buy_quote,
                wallet,
                priority_fee_lamports=priority_fee_lamports,
                raydium_cu_price=raydium_cu_price,
                in_mint=base_mint,
                out_mint=quote_mint,
                slippage_bps=slippage_bps,
            )
            sell_quote_buffered = dict(sell_quote)
            sell_quote_buffered["metadata"] = dict(sell_quote.get("metadata", {}))
            sell_quote_buffered["metadata"]["raw_quote_response"] = _buffer_quote_input(sell_quote, slippage_buffer)
            leg2 = _build_swap_plan(
                builder,
                sell_venue,
                sell_quote_buffered,
                wallet,
                priority_fee_lamports=priority_fee_lamports,
                raydium_cu_price=raydium_cu_price,
                in_mint=quote_mint,
                out_mint=base_mint,
                slippage_bps=slippage_bps,
            )
        except (ExecutionPlanError, Exception) as exc:  # noqa: BLE001 - skip this opp, never abort the run
            skipped.append({"direction": opp.get("direction"), "reason": "plan_build_failed", "error": str(exc)})
            continue

        plans.append(
            {
                "venue": f"{buy_venue}_to_{sell_venue}",
                "public_key": wallet.public_key,
                "transactions_base64": leg1.transactions_base64 + leg2.transactions_base64,
                "transaction_count": leg1.transaction_count + leg2.transaction_count,
                "metadata": {
                    "direction": opp.get("direction"),
                    "buy_venue": buy_venue,
                    "sell_venue": sell_venue,
                    "start_amount": opp.get("start_amount"),
                    "intermediate_amount": opp.get("intermediate_amount"),
                    "end_amount": opp.get("end_amount"),
                    "gross_profit_bps": gross_bps,
                    "est_net_profit_bps": net_bps,
                    "priority_fee_lamports": priority_fee_lamports,
                    "legs": [leg1.metadata, leg2.metadata],
                },
            }
        )

    return {
        "wallet": wallet.to_public_dict(),
        "prepared_swaps": plans,
        "execution_skipped": None if plans else "no_qualifying_opportunities",
        "skipped_opportunities": skipped,
    }


def _augment_result_with_execution_preparation(args: argparse.Namespace, result: dict) -> dict:
    if getattr(args, "mode", "monitor") not in {"prepare-swaps", "execute-swaps"}:
        return result
    wallet = ensure_wallet(args)
    if wallet is None:
        raise ValueError("--wallet-path is required when --mode prepare-swaps or --mode execute-swaps is used")
    result.update(prepare_swap_execution(args, result, wallet))
    return result


def execute_prepared_swaps(args: argparse.Namespace, result: dict, wallet: SolanaWallet) -> dict:
    rpc_url = getattr(args, "rpc_url", "") or ""
    if not rpc_url:
        raise ValueError("--rpc-url is required when --mode execute-swaps is used")
    executor = TradeExecutor(
        rpc_url=rpc_url,
        confirm_timeout_seconds=getattr(args, "confirm_timeout_seconds", 30.0),
        poll_interval_seconds=getattr(args, "poll_interval_seconds", 1.0),
        skip_preflight=getattr(args, "skip_preflight", False),
        commitment=getattr(args, "commitment", "confirmed"),
        max_retries=getattr(args, "max_send_retries", 3),
    )
    return executor.execute_prepared_swaps(wallet, result.get("prepared_swaps", []))


def _augment_result_with_execution(args: argparse.Namespace, result: dict) -> dict:
    mode = getattr(args, "mode", "monitor")
    if mode not in {"prepare-swaps", "execute-swaps"}:
        return result
    wallet = ensure_wallet(args)
    if wallet is None:
        raise ValueError("--wallet-path is required when --mode prepare-swaps or --mode execute-swaps is used")
    if "prepared_swaps" not in result:
        result.update(prepare_swap_execution(args, result, wallet))
    if mode == "execute-swaps":
        result.update(execute_prepared_swaps(args, result, wallet))
    return result


def main() -> int:
    args = parse_args()
    try:
        if args.once or args.interval <= 0:
            result = run_once(args)
            result = _augment_result_with_execution(args, result)
            print(json.dumps(result, indent=2))
            return 0

        # Continuous monitoring loop: run a full scan+prepare cycle on an
        # interval. run_once() writes the live dashboard (with heartbeat) on
        # every cycle, so the dashboard stays current while this process lives.
        cycles = 0
        while True:
            result = run_once(args)
            result = _augment_result_with_execution(args, result)
            print(json.dumps(result, indent=2))
            for alert in result.get("alerts", []):
                print(f"ALERT: {alert}")
            cycles += 1
            if args.max_cycles > 0 and cycles >= args.max_cycles:
                break
            time.sleep(args.interval)
        return 0
    except QuoteClientError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
