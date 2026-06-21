"""SEC Excel 财报解析。"""
import unittest
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sec"
MU_10Q = FIXTURE_DIR / "mu_10q.xls"
MU_10K = FIXTURE_DIR / "mu_10k.xls"


@unittest.skipUnless(MU_10Q.is_file(), "缺少 MU 10-Q fixture")
class Sec10QParserTest(unittest.TestCase):
    def setUp(self):
        self.data = MU_10Q.read_bytes()

    def test_revenue_and_filing_meta(self):
        from app.services.sec_filing_parser import parse_sec_filing

        result = parse_sec_filing(self.data, "0000723125-25-000021.xls", ticker="MU")
        extracted = result["extracted"]
        meta = extracted["filing_meta"]
        period = meta["calendar_period"]
        income = extracted["income_statement"][period]
        self.assertEqual(meta["form_type"], "10-Q")
        self.assertEqual(period, "2025-Q2")
        self.assertEqual(meta["filing_fq"], 3)
        self.assertAlmostEqual(income["revenue"], 9301.0, places=1)
        self.assertAlmostEqual(income["net_income"], 1885.0, places=1)

    def test_ytd_cash_not_in_cash_flow(self):
        from app.services.sec_filing_parser import parse_sec_filing

        result = parse_sec_filing(self.data, "0000723125-25-000021.xls", ticker="MU")
        meta = result["extracted"]["filing_meta"]
        self.assertEqual(meta["cash_flow_scope"], "ytd")
        self.assertEqual(result["extracted"]["cash_flow"], {})


@unittest.skipUnless(MU_10K.is_file(), "缺少 MU 10-K fixture")
class Sec10KParserTest(unittest.TestCase):
    def test_annual_revenue(self):
        from app.services.sec_filing_parser import parse_sec_filing

        data = MU_10K.read_bytes()
        result = parse_sec_filing(data, "0000723125-25-000028.xls", ticker="MU")
        extracted = result["extracted"]
        meta = extracted["filing_meta"]
        period = meta["calendar_period"]
        income = extracted["income_statement"][period]
        self.assertEqual(meta["form_type"], "10-K")
        self.assertAlmostEqual(income["revenue"], 37378.0, places=1)
        self.assertIn("operating", extracted["cash_flow"].get(period, {}))


if __name__ == "__main__":
    unittest.main()
