from __future__ import annotations

import argparse
import json
from pathlib import Path

from arbitrage_bot.analytics import AnalyticsEngine
from arbitrage_bot.clients import JupiterQuoteClient, QuoteClientError, RaydiumQuoteClient
from arbitrage_bot.dashboard import DashboardWriter
from arbitrage_bot.detector import ArbitrageDetector
from arbitrage_bot.runtime import BotRuntime
from arbitrage_bot.scanner import ArbitrageScanner
from arbitrage_bot.token_config import ETH_MINT, SOL_MINT

LAMPORTS_PER_SOL = 1_000_000_000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor SOL/ETH arbitrage between Jupiter and Raydium")
    parser.add_argument("--once", action="store_true", help="Run a single scan and exit")
    parser.add_argument("--interval", type=int, default=0, help="Polling interval in seconds")
    parser.add_argument("--amount-sol", type=float, default=0.1, help="Trade size in SOL")
    parser.add_argument("--min-profit-bps", type=float, default=5.0, help="Minimum profit in basis points")
    parser.add_argument("--db-path", default="data/arbitrage.db", help="SQLite path")
    parser.add_argument("--monitor-seconds", type=int, default=0, help="Seconds to wait before re-checking an opportunity")
    parser.add_argument(
        "--jupiter-exclude-raydium",
        action="store_true",
        help="Exclude Raydium liquidity from Jupiter quotes for a cleaner comparison",
    )
    parser.add_argument("--alert-min-bps", type=float, default=0.0, help="Only emit alerts at or above this profit threshold")
    parser.add_argument("--dashboard-output", default="", help="Optional HTML dashboard output path")
    return parser.parse_args(argv)


def build_scanner(args: argparse.Namespace) -> ArbitrageScanner:
    jupiter_client = JupiterQuoteClient(
        exclude_dexes=["Raydium"] if args.jupiter_exclude_raydium else []
    )
    raydium_client = RaydiumQuoteClient()
    detector = ArbitrageDetector(min_profit_bps=args.min_profit_bps)
    start_amount = int(args.amount_sol * LAMPORTS_PER_SOL)
    return ArbitrageScanner(
        base_symbol="SOL",
        quote_symbol="ETH",
        base_mint=SOL_MINT,
        quote_mint=ETH_MINT,
        start_amount=start_amount,
        detector=detector,
        raydium_client=raydium_client,
        jupiter_client=jupiter_client,
    )


def run_once(args: argparse.Namespace) -> dict:
    scanner = build_scanner(args)
    runtime = BotRuntime.from_components(
        scanner=scanner,
        db_path=Path(args.db_path),
        min_alert_bps=args.alert_min_bps,
    )
    result = runtime.run_cycle(monitor_seconds=args.monitor_seconds)
    if args.dashboard_output:
        writer = DashboardWriter(Path(args.dashboard_output))
        result["dashboard_path"] = writer.write(AnalyticsEngine(runtime.storage), limit=250)
    return result


def main() -> int:
    args = parse_args()
    try:
        if args.once or args.interval <= 0:
            print(json.dumps(run_once(args), indent=2))
            return 0

        while True:
            result = run_once(args)
            print(json.dumps(result, indent=2))
            for alert in result.get("alerts", []):
                print(f"ALERT: {alert}")
            import time

            time.sleep(args.interval)
    except QuoteClientError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
