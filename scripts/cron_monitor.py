from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot import run_once  # noqa: E402


def main() -> int:
    args = argparse.Namespace(
        once=True,
        interval=0,
        amount_sol=0.1,
        amount=0.1,
        amount_units="base",
        base_symbol="SOL",
        quote_symbol="USDC",
        base_mint=None,
        quote_mint=None,
        base_decimals=None,
        quote_decimals=None,
        left_venue="raydium",
        right_venue="jupiter",
        slippage_bps=50,
        min_profit_bps=5.0,
        db_path=str(ROOT / "data" / "arbitrage.db"),
        monitor_seconds=15,
        jupiter_exclude_raydium=False,
        jupiter_dexes="",
        jupiter_exclude_dexes="",
        alert_min_bps=25.0,
        dashboard_output=str(ROOT / "reports" / "dashboard.html"),
    )
    result = run_once(args)
    latest_json = ROOT / "reports" / "latest_scan.json"
    latest_json.parent.mkdir(parents=True, exist_ok=True)
    latest_json.write_text(json.dumps(result, indent=2), encoding="utf-8")

    alerts = result.get("alerts", [])
    if alerts:
        print("Arbitrage alert(s):")
        for alert in alerts:
            print(f"- {alert}")
        dashboard_path = result.get("dashboard_path")
        if dashboard_path:
            print(f"Dashboard: {dashboard_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
