import unittest
from unittest.mock import patch

from arbitrage_bot.detector import ArbitrageDetector
from arbitrage_bot.models import OpportunityRecord, ScanResult
from arbitrage_bot.runtime import reassess_opportunities


class FakeScanner:
    detector = ArbitrageDetector(min_profit_bps=5.0)

    def __init__(self, opportunities):
        self._opportunities = opportunities

    def scan_once(self):
        return ScanResult(scanned_at="now", quotes=[], opportunities=self._opportunities, errors=[])


class ReassessOpportunitiesTest(unittest.TestCase):
    @patch("arbitrage_bot.clients.time.sleep")
    def test_marks_persisted_when_recheck_is_at_least_as_good(self, _wait) -> None:
        original = OpportunityRecord(
            observed_at="2026-07-03T00:00:00+00:00",
            base_symbol="SOL",
            quote_symbol="ETH",
            direction="raydium_to_jupiter",
            start_amount=1,
            intermediate_amount=2,
            end_amount=110,
            profit_lamports=10,
            profit_bps=1000,
            buy_venue="raydium",
            sell_venue="jupiter",
            buy_route_labels=["Raydium"],
            sell_route_labels=["Orca V2"],
            buy_price_impact_pct=0.0,
            sell_price_impact_pct=0.0,
        )
        refreshed = OpportunityRecord(
            observed_at="2026-07-03T00:00:05+00:00",
            base_symbol="SOL",
            quote_symbol="ETH",
            direction="raydium_to_jupiter",
            start_amount=1,
            intermediate_amount=2,
            end_amount=111,
            profit_lamports=11,
            profit_bps=1100,
            buy_venue="raydium",
            sell_venue="jupiter",
            buy_route_labels=["Raydium"],
            sell_route_labels=["Orca V2"],
            buy_price_impact_pct=0.0,
            sell_price_impact_pct=0.0,
        )

        updated = reassess_opportunities([original], FakeScanner([refreshed]), 1)

        self.assertEqual(updated[0].evaluation_status, "persisted")

    @patch("arbitrage_bot.clients.time.sleep")
    def test_marks_expired_when_recheck_disappears(self, _wait) -> None:
        original = OpportunityRecord(
            observed_at="2026-07-03T00:00:00+00:00",
            base_symbol="SOL",
            quote_symbol="ETH",
            direction="raydium_to_jupiter",
            start_amount=1,
            intermediate_amount=2,
            end_amount=110,
            profit_lamports=10,
            profit_bps=1000,
            buy_venue="raydium",
            sell_venue="jupiter",
            buy_route_labels=["Raydium"],
            sell_route_labels=["Orca V2"],
            buy_price_impact_pct=0.0,
            sell_price_impact_pct=0.0,
        )

        updated = reassess_opportunities([original], FakeScanner([]), 1)

        self.assertEqual(updated[0].evaluation_status, "expired")
        self.assertIn("no profitable quote", updated[0].evaluation_notes)


if __name__ == "__main__":
    unittest.main()
