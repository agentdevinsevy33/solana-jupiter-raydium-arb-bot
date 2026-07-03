from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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
