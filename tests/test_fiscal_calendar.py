"""财年日历映射。"""
import unittest
from datetime import date

from flask import Flask

from app.services.fiscal_calendar import (
    build_period_context,
    calendar_period_from_date,
    infer_filing_fy_fq,
)


class FiscalCalendarTest(unittest.TestCase):
    def test_calendar_period_may_2025(self):
        self.assertEqual(calendar_period_from_date(date(2025, 5, 29)), "2025-Q2")

    def test_mu_fy_q3(self):
        fy, fq = infer_filing_fy_fq(date(2025, 5, 29), 8)
        self.assertEqual(fy, 2025)
        self.assertEqual(fq, 3)

    def test_build_period_context(self):
        ctx = build_period_context("2025-05-29", ticker="MU", fy_end_month=8)
        self.assertEqual(ctx["calendar_period"], "2025-Q2")
        self.assertEqual(ctx["filing_fy"], 2025)
        self.assertEqual(ctx["filing_fq"], 3)


class ResolveFyEndMonthTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["FMP_API_KEY"] = ""
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def test_ticker_fallback_mu(self):
        from app.services.fiscal_calendar import resolve_fy_end_month

        self.assertEqual(resolve_fy_end_month("MU"), 8)


if __name__ == "__main__":
    unittest.main()
