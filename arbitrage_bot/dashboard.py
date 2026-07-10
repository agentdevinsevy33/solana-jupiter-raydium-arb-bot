from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arbitrage_bot.analytics import AnalyticsEngine


@dataclass(slots=True)
class DashboardWriter:
    output_path: Path
    pair_label: str = "SOL/ETH"

    def write(
        self,
        engine: AnalyticsEngine,
        *,
        limit: int = 250,
        heartbeat: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> str:
        html = engine.render_html_dashboard(
            limit=limit,
            pair_label=self.pair_label,
            heartbeat=heartbeat,
            config=config,
        )
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(html, encoding="utf-8")
        return str(self.output_path)
