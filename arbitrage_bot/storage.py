from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from arbitrage_bot.models import OpportunityRecord, QuoteSnapshot


class Storage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists quote_snapshots (
                    id integer primary key autoincrement,
                    fetched_at text not null,
                    venue text not null,
                    input_mint text not null,
                    output_mint text not null,
                    in_amount integer not null,
                    out_amount integer not null,
                    price_impact_pct real not null,
                    route_labels text not null,
                    metadata text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists opportunities (
                    id integer primary key autoincrement,
                    observed_at text not null,
                    base_symbol text not null,
                    quote_symbol text not null,
                    direction text not null,
                    start_amount integer not null,
                    intermediate_amount integer not null,
                    end_amount integer not null,
                    profit_lamports integer not null,
                    profit_bps real not null,
                    buy_venue text not null,
                    sell_venue text not null,
                    buy_route_labels text not null,
                    sell_route_labels text not null,
                    buy_price_impact_pct real not null,
                    sell_price_impact_pct real not null,
                    evaluation_status text not null,
                    evaluation_notes text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists scan_history (
                    id integer primary key autoincrement,
                    scanned_at text not null,
                    quote_count integer not null,
                    opportunity_count integer not null,
                    alert_count integer not null,
                    error_count integer not null,
                    scan_status text not null,
                    pair_label text not null,
                    left_venue text not null,
                    right_venue text not null
                )
                """
            )

    def save_quotes(self, quotes: list[QuoteSnapshot]) -> None:
        if not quotes:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                insert into quote_snapshots (
                    fetched_at, venue, input_mint, output_mint, in_amount, out_amount,
                    price_impact_pct, route_labels, metadata
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        quote.fetched_at,
                        quote.venue,
                        quote.input_mint,
                        quote.output_mint,
                        quote.in_amount,
                        quote.out_amount,
                        quote.price_impact_pct,
                        json.dumps(quote.route_labels),
                        json.dumps(quote.metadata),
                    )
                    for quote in quotes
                ],
            )

    def save_opportunities(self, records: list[OpportunityRecord]) -> None:
        if not records:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                insert into opportunities (
                    observed_at, base_symbol, quote_symbol, direction, start_amount,
                    intermediate_amount, end_amount, profit_lamports, profit_bps,
                    buy_venue, sell_venue, buy_route_labels, sell_route_labels,
                    buy_price_impact_pct, sell_price_impact_pct,
                    evaluation_status, evaluation_notes
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.observed_at,
                        record.base_symbol,
                        record.quote_symbol,
                        record.direction,
                        record.start_amount,
                        record.intermediate_amount,
                        record.end_amount,
                        record.profit_lamports,
                        record.profit_bps,
                        record.buy_venue,
                        record.sell_venue,
                        json.dumps(record.buy_route_labels),
                        json.dumps(record.sell_route_labels),
                        record.buy_price_impact_pct,
                        record.sell_price_impact_pct,
                        record.evaluation_status,
                        record.evaluation_notes,
                    )
                    for record in records
                ],
            )

    def save_scan_summary(
        self,
        *,
        scanned_at: str,
        quote_count: int,
        opportunity_count: int,
        alert_count: int,
        error_count: int,
        scan_status: str,
        pair_label: str,
        left_venue: str,
        right_venue: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into scan_history (
                    scanned_at, quote_count, opportunity_count, alert_count,
                    error_count, scan_status, pair_label, left_venue, right_venue
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scanned_at,
                    quote_count,
                    opportunity_count,
                    alert_count,
                    error_count,
                    scan_status,
                    pair_label,
                    left_venue,
                    right_venue,
                ),
            )

    def fetch_recent(self, limit: int = 50) -> list[OpportunityRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select observed_at, base_symbol, quote_symbol, direction, start_amount,
                       intermediate_amount, end_amount, profit_lamports, profit_bps,
                       buy_venue, sell_venue, buy_route_labels, sell_route_labels,
                       buy_price_impact_pct, sell_price_impact_pct,
                       evaluation_status, evaluation_notes
                from opportunities
                order by observed_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [
            OpportunityRecord(
                observed_at=row[0],
                base_symbol=row[1],
                quote_symbol=row[2],
                direction=row[3],
                start_amount=row[4],
                intermediate_amount=row[5],
                end_amount=row[6],
                profit_lamports=row[7],
                profit_bps=row[8],
                buy_venue=row[9],
                sell_venue=row[10],
                buy_route_labels=json.loads(row[11]),
                sell_route_labels=json.loads(row[12]),
                buy_price_impact_pct=row[13],
                sell_price_impact_pct=row[14],
                evaluation_status=row[15],
                evaluation_notes=row[16],
            )
            for row in rows
        ]

    def fetch_recent_scans(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select scanned_at, quote_count, opportunity_count, alert_count,
                       error_count, scan_status, pair_label, left_venue, right_venue
                from scan_history
                order by scanned_at desc, id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "scanned_at": row[0],
                "quote_count": row[1],
                "opportunity_count": row[2],
                "alert_count": row[3],
                "error_count": row[4],
                "scan_status": row[5],
                "pair_label": row[6],
                "left_venue": row[7],
                "right_venue": row[8],
            }
            for row in rows
        ]

    def fetch_dashboard_state(self) -> dict[str, Any]:
        with self._connect() as conn:
            quote_count_total = conn.execute("select count(*) from quote_snapshots").fetchone()[0]
            opportunity_count_total = conn.execute("select count(*) from opportunities").fetchone()[0]
            latest_quote_row = conn.execute(
                """
                select fetched_at, venue, input_mint, output_mint, in_amount, out_amount,
                       price_impact_pct, route_labels, metadata
                from quote_snapshots
                order by fetched_at desc, id desc
                limit 1
                """
            ).fetchone()
            latest_opportunity_row = conn.execute(
                """
                select observed_at, base_symbol, quote_symbol, direction, start_amount,
                       intermediate_amount, end_amount, profit_lamports, profit_bps,
                       buy_venue, sell_venue, buy_route_labels, sell_route_labels,
                       buy_price_impact_pct, sell_price_impact_pct,
                       evaluation_status, evaluation_notes
                from opportunities
                order by observed_at desc, id desc
                limit 1
                """
            ).fetchone()

        latest_quote = None
        if latest_quote_row:
            latest_quote = QuoteSnapshot(
                venue=latest_quote_row[1],
                input_mint=latest_quote_row[2],
                output_mint=latest_quote_row[3],
                in_amount=latest_quote_row[4],
                out_amount=latest_quote_row[5],
                price_impact_pct=latest_quote_row[6],
                route_labels=json.loads(latest_quote_row[7]),
                fetched_at=latest_quote_row[0],
                metadata=json.loads(latest_quote_row[8]),
            ).to_dict()

        latest_opportunity = None
        if latest_opportunity_row:
            latest_opportunity = OpportunityRecord(
                observed_at=latest_opportunity_row[0],
                base_symbol=latest_opportunity_row[1],
                quote_symbol=latest_opportunity_row[2],
                direction=latest_opportunity_row[3],
                start_amount=latest_opportunity_row[4],
                intermediate_amount=latest_opportunity_row[5],
                end_amount=latest_opportunity_row[6],
                profit_lamports=latest_opportunity_row[7],
                profit_bps=latest_opportunity_row[8],
                buy_venue=latest_opportunity_row[9],
                sell_venue=latest_opportunity_row[10],
                buy_route_labels=json.loads(latest_opportunity_row[11]),
                sell_route_labels=json.loads(latest_opportunity_row[12]),
                buy_price_impact_pct=latest_opportunity_row[13],
                sell_price_impact_pct=latest_opportunity_row[14],
                evaluation_status=latest_opportunity_row[15],
                evaluation_notes=latest_opportunity_row[16],
            ).to_dict()

        return {
            "quote_count_total": quote_count_total,
            "opportunity_count_total": opportunity_count_total,
            "latest_quote": latest_quote,
            "latest_opportunity": latest_opportunity,
            "recent_scans": self.fetch_recent_scans(limit=20),
        }
