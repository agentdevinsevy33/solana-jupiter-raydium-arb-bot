from __future__ import annotations

import argparse
import json
from pathlib import Path

from arbitrage_bot.clients import JupiterQuoteClient, OpportunityMonitor, QuoteClientError, RaydiumQuoteClient
from arbitrage_bot.detector import ArbitrageDetector
from arbitrage_bot.models import OpportunityRecord
from arbitrage_bot.scanner import ArbitrageScanner
from arbitrage_bot.storage import Storage
from arbitrage_bot.token_config import ETH_MINT, SOL_MINT

LAMPORTS_PER_SOL = 1_000_000_000


def parse_args() -> argparse.Namespace:
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
    return parser.parse_args()


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


def reassess_opportunities(
    opportunities: list[OpportunityRecord],
    scanner: ArbitrageScanner,
    monitor_seconds: int,
) -> list[OpportunityRecord]:
    if not opportunities or monitor_seconds <= 0:
        return opportunities

    monitor = OpportunityMonitor(persistence_seconds=monitor_seconds)
    monitor.wait()
    refreshed = scanner.scan_once()
    refreshed_map = {item.direction: item for item in refreshed.opportunities}

    updated: list[OpportunityRecord] = []
    for record in opportunities:
        current = refreshed_map.get(record.direction)
        if current is None:
            record.evaluation_status = "expired"
            record.evaluation_notes = f"no profitable quote after {monitor_seconds}s"
        elif current.end_amount >= record.end_amount:
            record.evaluation_status = "persisted"
            record.evaluation_notes = f"still profitable after {monitor_seconds}s"
        else:
            record.evaluation_status = "expired"
            record.evaluation_notes = (
                f"profit dropped from {record.end_amount} to {current.end_amount} after {monitor_seconds}s"
            )
        updated.append(record)
    return updated


def run_once(args: argparse.Namespace) -> dict:
    scanner = build_scanner(args)
    storage = Storage(Path(args.db_path))
    scan = scanner.scan_once()
    storage.save_quotes(scan.quotes)
    opportunities = reassess_opportunities(scan.opportunities, scanner, args.monitor_seconds)
    storage.save_opportunities(opportunities)
    summary = scanner.detector.learning_summary(storage.fetch_recent(limit=250))
    return {
        "scan": scan.to_dict(),
        "saved_opportunities": [item.to_dict() for item in opportunities],
        "learning_summary": summary,
    }


def main() -> int:
    args = parse_args()
    try:
        if args.once or args.interval <= 0:
            print(json.dumps(run_once(args), indent=2))
            return 0

        while True:
            print(json.dumps(run_once(args), indent=2))
            import time

            time.sleep(args.interval)
    except QuoteClientError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
