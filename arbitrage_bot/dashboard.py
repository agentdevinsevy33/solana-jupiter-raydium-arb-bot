from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from arbitrage_bot.analytics import AnalyticsEngine


@dataclass(slots=True)
class DashboardWriter:
    output_path: Path

    def write(self, engine: AnalyticsEngine, *, limit: int = 250) -> str:
        html = engine.render_html_dashboard(limit=limit)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(html, encoding="utf-8")
        return str(self.output_path)
