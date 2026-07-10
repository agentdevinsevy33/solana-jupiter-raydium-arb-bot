from __future__ import annotations

import json
from argparse import Namespace
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot import run_once


DEFAULT_PAIRS = [("SOL", "USDC"), ("SOL", "USDT"), ("USDC", "USDT"), ("SOL", "ETH")]
DEFAULT_VENUE_PAIRS = [
    ("raydium", "jupiter"),
    ("orca", "jupiter"),
    ("raydium", "orca"),
]
DEFAULT_AMOUNTS = [0.1, 1.0, 10.0]


def build_default_experiments() -> list[dict[str, Any]]:
    experiments: list[dict[str, Any]] = []
    for base_symbol, quote_symbol in DEFAULT_PAIRS:
        for left_venue, right_venue in DEFAULT_VENUE_PAIRS:
            for amount in DEFAULT_AMOUNTS:
                experiments.append(
                    {
                        "base_symbol": base_symbol,
                        "quote_symbol": quote_symbol,
                        "amount": amount,
                        "amount_units": "base",
                        "left_venue": left_venue,
                        "right_venue": right_venue,
                        "slippage_bps": 50,
                        "min_profit_bps": 5.0,
                        "monitor_seconds": 0,
                        "alert_min_bps": 0.0,
                        "jupiter_exclude_raydium": left_venue != "raydium" and right_venue == "jupiter",
                    }
                )
    return experiments


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _build_args(experiment: dict[str, Any], *, db_path: str | None = None) -> Namespace:
    payload = {
        "once": True,
        "interval": 0,
        "amount_sol": experiment.get("amount", 0.1),
        "amount": experiment.get("amount"),
        "amount_units": experiment.get("amount_units", "base"),
        "base_symbol": experiment["base_symbol"],
        "quote_symbol": experiment["quote_symbol"],
        "base_mint": experiment.get("base_mint"),
        "quote_mint": experiment.get("quote_mint"),
        "base_decimals": experiment.get("base_decimals"),
        "quote_decimals": experiment.get("quote_decimals"),
        "left_venue": experiment["left_venue"],
        "right_venue": experiment["right_venue"],
        "slippage_bps": experiment.get("slippage_bps", 50),
        "min_profit_bps": experiment.get("min_profit_bps", 5.0),
        "db_path": db_path or experiment.get("db_path", "data/arbitrage.db"),
        "monitor_seconds": experiment.get("monitor_seconds", 0),
        "jupiter_exclude_raydium": experiment.get("jupiter_exclude_raydium", False),
        "jupiter_dexes": experiment.get("jupiter_dexes", ""),
        "jupiter_exclude_dexes": experiment.get("jupiter_exclude_dexes", ""),
        "alert_min_bps": experiment.get("alert_min_bps", 0.0),
        "dashboard_output": experiment.get("dashboard_output", ""),
    }
    return Namespace(**payload)


def run_experiments(
    *,
    output_dir: Path,
    experiments: list[dict[str, Any]] | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    matrix = experiments or build_default_experiments()
    results: list[dict[str, Any]] = []
    for experiment in matrix:
        args = _build_args(experiment, db_path=db_path)
        record = deepcopy(experiment)
        try:
            result = run_once(cast(Namespace, args))
            record.update(
                {
                    "status": "ok",
                    "result": result,
                    "scan_time": result["scan"].get("scanned_at"),
                    "experiment_metrics": result.get("experiment_metrics", {}),
                }
            )
        except Exception as exc:
            record.update(
                {
                    "status": "error",
                    "error": str(exc),
                    "scan_time": None,
                    "experiment_metrics": {},
                }
            )
        results.append(record)

    latest_path = output_dir / "latest.json"
    latest_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    timestamped = output_dir / f"run_{_timestamp()}.json"
    timestamped.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


if __name__ == "__main__":
    run_experiments(output_dir=Path("reports/experiments"))
