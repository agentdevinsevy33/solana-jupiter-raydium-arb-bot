import unittest

from bot import parse_args


class DashboardCliTest(unittest.TestCase):
    def test_accepts_dashboard_output_flag(self) -> None:
        args = parse_args(["--once", "--dashboard-output", "reports/dashboard.html"])
        self.assertEqual(args.dashboard_output, "reports/dashboard.html")


if __name__ == "__main__":
    unittest.main()
