import unittest

from bot import parse_args


class MonitoringCliTest(unittest.TestCase):
    def test_accepts_alert_and_dashboard_flags(self) -> None:
        args = parse_args([
            "--once",
            "--alert-min-bps",
            "120",
            "--dashboard-output",
            "reports/dashboard.html",
        ])

        self.assertEqual(args.alert_min_bps, 120.0)
        self.assertEqual(args.dashboard_output, "reports/dashboard.html")

    def test_accepts_amount_units_override(self) -> None:
        args = parse_args([
            "--once",
            "--amount",
            "100",
            "--amount-units",
            "quote",
        ])

        self.assertEqual(args.amount, 100.0)
        self.assertEqual(args.amount_units, "quote")


if __name__ == "__main__":
    unittest.main()
