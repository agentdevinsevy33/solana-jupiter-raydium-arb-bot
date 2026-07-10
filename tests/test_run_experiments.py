import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_experiments import run_experiments


class RunExperimentsTest(unittest.TestCase):
    @patch("scripts.run_experiments.run_once")
    def test_run_experiments_writes_latest_and_timestamped_reports(self, mock_run_once) -> None:
        mock_run_once.side_effect = [
            {
                "scan": {"scanned_at": "2026-07-08T00:00:00+00:00", "quotes": [], "opportunities": []},
                "saved_opportunities": [],
                "learning_summary": {},
                "alerts": [],
                "experiment_metrics": {
                    "left_to_right_profit_bps": 1.5,
                    "right_to_left_profit_bps": -0.5,
                },
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "reports" / "experiments"
            results = run_experiments(
                output_dir=output_dir,
                experiments=[
                    {
                        "base_symbol": "SOL",
                        "quote_symbol": "USDC",
                        "amount": 0.1,
                        "amount_units": "base",
                        "left_venue": "raydium",
                        "right_venue": "jupiter",
                        "slippage_bps": 50,
                    }
                ],
            )

            self.assertEqual(len(results), 1)
            latest = json.loads((output_dir / "latest.json").read_text())
            self.assertEqual(latest[0]["base_symbol"], "SOL")
            files = [path for path in output_dir.iterdir() if path.name != "latest.json"]
            self.assertEqual(len(files), 1)

    @patch("scripts.run_experiments.run_once")
    def test_run_experiments_records_failures_without_aborting(self, mock_run_once) -> None:
        mock_run_once.side_effect = [RuntimeError("boom"), {
            "scan": {"scanned_at": "2026-07-08T00:00:01+00:00", "quotes": [], "opportunities": []},
            "saved_opportunities": [],
            "learning_summary": {},
            "alerts": [],
            "experiment_metrics": {},
        }]

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "reports" / "experiments"
            results = run_experiments(
                output_dir=output_dir,
                experiments=[
                    {
                        "base_symbol": "SOL",
                        "quote_symbol": "USDC",
                        "amount": 0.1,
                        "amount_units": "base",
                        "left_venue": "raydium",
                        "right_venue": "jupiter",
                        "slippage_bps": 50,
                    },
                    {
                        "base_symbol": "SOL",
                        "quote_symbol": "USDT",
                        "amount": 0.1,
                        "amount_units": "base",
                        "left_venue": "orca",
                        "right_venue": "jupiter",
                        "slippage_bps": 50,
                    },
                ],
            )

            self.assertEqual(results[0]["status"], "error")
            self.assertIn("boom", results[0]["error"])
            self.assertEqual(results[1]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
