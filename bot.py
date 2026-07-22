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
from arbitrage_bot.executor import SolanaRpcClient, TradeExecutor
from arbitrage_bot.runtime import BotRuntime
from arbitrage_bot.scanner import ArbitrageScanner
from arbitrage_bot.models import QuoteRequest
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
    parser.add_argument("--max-leg-retries", type=int, default=3, help="When a later leg of a round trip fails at broadcast (e.g. stale quote), retry it this many times with a freshly-fetched quote before giving up")
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
        # Always pass the associated-token account for BOTH legs, including SOL.
        # For SOL input/output this is the wsSOL ATA; omitting it (the previous
        # behaviour) made Raydium's swap-base-in fail at chain simulation with
        # "Route error: ExpectedAccount" (custom program error 0x3).
        input_account = _ata_address(wallet.public_key, in_mint)
        output_account = _ata_address(wallet.public_key, out_mint)
        return builder.build_raydium_swap_plan(
            public_key=wallet.public_key,
            quote_response=raw,
            wrap_sol=(in_mint == SOL_MINT),
            unwrap_sol=(out_mint == SOL_MINT),
            compute_unit_price_micro_lamports=raydium_cu_price,
            input_account=input_account,
            output_account=output_account,
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
        # Re-fetch FRESH quotes for both legs right before building. The scan-time
        # quotes can be seconds old by now; Raydium rejects a stale swapResponse
        # with a generic UNKNOWN_ERROR and the trade never gets broadcast. A fresh
        # re-quote also applies the reverse-leg slippage buffer correctly: we quote
        # for the reduced amount instead of mutating the stale quote's inputAmount
        # (which left the route/output internally inconsistent and also failed).
        start_amount = int(opp.get("start_amount") or 0)
        intermediate_amount = int(opp.get("intermediate_amount") or 0)
        try:
            fresh_buy = _quote_client_for(buy_venue).get_quote(
                QuoteRequest(
                    input_mint=base_mint,
                    output_mint=quote_mint,
                    amount=start_amount,
                    slippage_bps=slippage_bps,
                )
            )
            sell_input = int(intermediate_amount * (1.0 - slippage_buffer))
            fresh_sell = _quote_client_for(sell_venue).get_quote(
                QuoteRequest(
                    input_mint=quote_mint,
                    output_mint=base_mint,
                    amount=max(sell_input, 1),
                    slippage_bps=slippage_bps,
                )
            )
        except QuoteClientError as exc:
            skipped.append(
                {
                    "direction": opp.get("direction"),
                    "reason": "fresh_quote_failed",
                    "error": str(exc),
                }
            )
            continue
        buy_quote = fresh_buy.to_dict()
        sell_quote = fresh_sell.to_dict()
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
            leg2 = _build_swap_plan(
                builder,
                sell_venue,
                sell_quote,
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
                    "legs": [
                        {
                            **leg1.metadata,
                            "venue": buy_venue,
                            "in_mint": base_mint,
                            "out_mint": quote_mint,
                            "amount": opp.get("start_amount"),
                            "slippage_bps": slippage_bps,
                        },
                        {
                            **leg2.metadata,
                            "venue": sell_venue,
                            "in_mint": quote_mint,
                            "out_mint": base_mint,
                            "amount": opp.get("intermediate_amount"),
                            "slippage_bps": slippage_bps,
                        },
                    ],
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
    rpc_client = SolanaRpcClient(rpc_url=rpc_url)
    # Raydium wrapSol swaps require the wsSOL ATA to pre-exist; create it once if missing.
    ensure_wsol_ata(wallet, rpc_client)
    executor = TradeExecutor(
        rpc_url=rpc_url,
        confirm_timeout_seconds=getattr(args, "confirm_timeout_seconds", 30.0),
        poll_interval_seconds=getattr(args, "poll_interval_seconds", 1.0),
        skip_preflight=getattr(args, "skip_preflight", False),
        commitment=getattr(args, "commitment", "confirmed"),
        max_retries=getattr(args, "max_send_retries", 3),
        rebuild_leg=_make_rebuild_leg(args, wallet, rpc_client),
        max_leg_retries=int(getattr(args, "max_leg_retries", 3)),
    )
    out = executor.execute_prepared_swaps(wallet, result.get("prepared_swaps", []))
    _recover_partial_plans(args, wallet, rpc_client, out)
    return out


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


# --- Round-trip resilience: fresh-quote retry + mid-route recovery ----------
def _ata_address(owner: str, mint: str) -> str:
    from solders.pubkey import Pubkey

    ata_program = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
    token_program = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
    owner_p = Pubkey.from_string(owner)
    mint_p = Pubkey.from_string(mint)
    # Standard SPL associated-token-account derivation: seeds are
    # [owner, token_program, mint]. (Using b"associated" as a seed is WRONG and
    # yields a non-existent address, which makes swaps fail at chain simulation.)
    seeds = [bytes(owner_p), bytes(token_program), bytes(mint_p)]
    addr, _ = Pubkey.find_program_address(seeds, ata_program)
    return str(addr)


def ensure_wsol_ata(wallet: SolanaWallet, rpc_client: "object") -> str | None:
    """Ensure the wallet's wsSOL associated-token account exists.

    Raydium's swap-base-in with wrapSol=True requires the wsSOL ATA to already
    exist on-chain (it does NOT create it). Without it, every SOL->token swap
    fails at chain simulation with "Route error: ExpectedAccount". This creates
    it once (idempotent: existence is checked first) if missing. Returns the ATA
    address, or None if it could not be ensured (the executor will then surface a
    clear error instead of a confusing simulation failure).
    """
    import base64 as _b64
    from solders.pubkey import Pubkey
    from solders.keypair import Keypair
    from solders.transaction import Transaction
    from solders.instruction import Instruction, AccountMeta
    from solders.message import Message
    from solders.hash import Hash

    ata = _ata_address(wallet.public_key, SOL_MINT)
    owner = Pubkey.from_string(wallet.public_key)
    ata_program = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
    token_program = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
    sys_program = Pubkey.from_string("11111111111111111111111111111111")
    sol_mint = Pubkey.from_string(SOL_MINT)

    # Cheap existence check first (no broadcast).
    try:
        if rpc_client._rpc("getAccountInfo", [ata, {"encoding": "base64"}]).get("value"):
            return ata
    except Exception:
        pass

    ix = Instruction(
        program_id=ata_program,
        accounts=[
            AccountMeta(pubkey=owner, is_signer=True, is_writable=True),
            AccountMeta(pubkey=Pubkey.from_string(ata), is_signer=False, is_writable=True),
            AccountMeta(pubkey=owner, is_signer=False, is_writable=False),
            AccountMeta(pubkey=sol_mint, is_signer=False, is_writable=False),
            AccountMeta(pubkey=sys_program, is_signer=False, is_writable=False),
            AccountMeta(pubkey=token_program, is_signer=False, is_writable=False),
        ],
        data=b"",
    )
    kp = Keypair.from_bytes(bytes(wallet.secret_key))
    bh = rpc_client._rpc("getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"]
    msg = Message.new_with_blockhash([ix], owner, Hash.from_string(bh))
    tx = Transaction([kp], msg, Hash.from_string(bh))
    raw = _b64.b64encode(bytes(tx)).decode()
    # skip_preflight=False so a bad tx can never land; max_retries=0 (one shot).
    try:
        rpc_client.send_transaction(
            raw, skip_preflight=False, preflight_commitment="finalized", max_retries=0
        )
    except Exception as exc:  # pragma: no cover - network/chain dependent
        # A benign race (already created elsewhere) still leaves us fine.
        try:
            if rpc_client._rpc("getAccountInfo", [ata, {"encoding": "base64"}]).get("value"):
                return ata
        except Exception:
            pass
        print(f"[warn] ensure_wsol_ata: could not create wsSOL ATA: {exc}", file=sys.stderr)
        return None
    return ata


def _quote_client_for(venue: str) -> "object":
    if venue == "jupiter":
        return JupiterQuoteClient()
    if venue == "raydium":
        return RaydiumQuoteClient()
    raise ExecutionPlanError(f"No quote client available for venue '{venue}'")


def _actual_input_amount(rpc_client: "object", pubkey: str, mint: str, fallback: int) -> int:
    """Actual balance of ``mint`` held by the wallet, used to re-quote a leg
    against reality (handles partial fills / dust)."""
    if mint == SOL_MINT:
        lamports = rpc_client._rpc("getBalance", [pubkey])["value"]
        rent_reserve = 5_000_000
        return max(lamports - rent_reserve, 0)
    ata = rpc_client._rpc("getTokenAccountsByOwner", [pubkey, {"mint": mint}, {"encoding": "jsonParsed"}])
    values = (ata.get("value") or []) if isinstance(ata, dict) else []
    if not values:
        return int(fallback or 0)
    return int(values[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])


def _make_rebuild_leg(args: argparse.Namespace, wallet: SolanaWallet, rpc_client: "object"):
    builder = ExecutionPlanBuilder()
    priority_fee = int(getattr(args, "priority_fee_lamports", 20_000))
    cu_price = int(getattr(args, "raydium_compute_unit_price_micro_lamports", 50_000))
    slippage_bps = int(getattr(args, "slippage_bps", 50))

    def rebuild_leg(plan: dict, index: int):
        legs = (plan.get("metadata") or {}).get("legs") or [None, None]
        leg_meta = legs[index] if index < len(legs) else None
        if not leg_meta:
            return None
        in_mint = leg_meta["in_mint"]
        out_mint = leg_meta["out_mint"]
        amount = _actual_input_amount(rpc_client, wallet.public_key, in_mint, fallback=leg_meta.get("amount") or 0)
        if amount <= 0:
            return None
        client = _quote_client_for(leg_meta["venue"])
        quote = client.get_quote(
            QuoteRequest(input_mint=in_mint, output_mint=out_mint, amount=amount, slippage_bps=slippage_bps)
        )
        return _build_swap_plan(
            builder,
            leg_meta["venue"],
            quote,
            wallet,
            priority_fee_lamports=priority_fee,
            raydium_cu_price=cu_price,
            in_mint=in_mint,
            out_mint=out_mint,
            slippage_bps=slippage_bps,
        )

    return rebuild_leg


def _reverse_partial_plan(args: argparse.Namespace, wallet: SolanaWallet, rpc_client: "object", plan_result: dict) -> None:
    """Reverse a partially-executed round trip so the wallet is never left
    holding an intermediate asset. The confirmed leg is the buy leg
    (base->quote); we swap the quote asset back to base via the same venue."""
    meta = plan_result.get("metadata", {})
    legs = meta.get("legs") or []
    if not legs:
        return
    buy_venue = meta.get("buy_venue")
    base_mint = legs[0].get("in_mint")
    quote_mint = legs[0].get("out_mint")
    if not (buy_venue and base_mint and quote_mint):
        return
    amount = _actual_input_amount(rpc_client, wallet.public_key, quote_mint, fallback=0)
    if amount <= 0:
        return
    client = _quote_client_for(buy_venue)
    quote = client.get_quote(
        QuoteRequest(input_mint=quote_mint, output_mint=base_mint, amount=amount, slippage_bps=int(getattr(args, "slippage_bps", 50)))
    )
    plan = _build_swap_plan(
        ExecutionPlanBuilder(),
        buy_venue,
        quote,
        wallet,
        priority_fee_lamports=int(getattr(args, "priority_fee_lamports", 20_000)),
        raydium_cu_price=int(getattr(args, "raydium_compute_unit_price_micro_lamports", 50_000)),
        in_mint=quote_mint,
        out_mint=base_mint,
        slippage_bps=int(getattr(args, "slippage_bps", 50)),
    )
    recovery_executor = TradeExecutor(
        rpc_url=getattr(args, "rpc_url", ""),
        skip_preflight=False,
        commitment=getattr(args, "commitment", "confirmed"),
        max_retries=getattr(args, "max_send_retries", 3),
    )
    recovery_out = recovery_executor.execute_prepared_swaps(wallet, [plan.to_dict()])
    print(json.dumps({"mid_route_recovery": {"buy_venue": buy_venue, "recovered_amount": amount, "result": recovery_out}}, indent=2))


def _recover_partial_plans(args: argparse.Namespace, wallet: SolanaWallet, rpc_client: "object", exec_out: dict) -> None:
    for item in exec_out.get("execution_results", []):
        if item.get("partial"):
            print(json.dumps({"warning": "partial round-trip execution detected; attempting midroute recovery", "venue": item.get("venue")}))
            try:
                _reverse_partial_plan(args, wallet, rpc_client, item)
            except Exception as exc:  # noqa: BLE001 - recovery must never crash the run
                print(json.dumps({"error": f"mid_route_recovery_failed: {exc}"}))


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
