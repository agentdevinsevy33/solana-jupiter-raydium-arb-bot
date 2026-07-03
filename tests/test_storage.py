import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from arbitrage_bot.models import OpportunityRecord
from arbitrage_bot.storage import Storage


class StorageTest(unittest.TestCase):
    def test_persists_and_reads_opportunities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "arb.db"
            storage = Storage(db_path)
            record = OpportunityRecord(
                observed_at="2026-07-03T00:00:00+00:00",
                base_symbol="SOL",
                quote_symbol="ETH",
                direction="raydium_to_jupiter",
                start_amount=1_000_000_000,
                intermediate_amount=70_000,
                end_amount=1_020_000_000,
                profit_lamports=20_000_000,
                profit_bps=200.0,
                buy_venue="raydium",
                sell_venue="jupiter",
                buy_route_labels=["Raydium"],
                sell_route_labels=["Orca V2"],
                buy_price_impact_pct=0.01,
                sell_price_impact_pct=0.02,
                evaluation_status="pending",
                evaluation_notes="",
            )

            storage.save_opportunities([record])
            rows = storage.fetch_recent(limit=5)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].direction, record.direction)
            self.assertEqual(rows[0].profit_lamports, 20_000_000)
            self.assertEqual(rows[0].buy_route_labels, ["Raydium"])

            with sqlite3.connect(db_path) as conn:
                saved = conn.execute(
                    "select sell_route_labels from opportunities limit 1"
                ).fetchone()[0]
            self.assertEqual(json.loads(saved), ["Orca V2"])


if __name__ == "__main__":
    unittest.main()
