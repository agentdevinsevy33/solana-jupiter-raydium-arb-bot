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


if __name__ == "__main__":
    unittest.main()
