"""FMP financial-reports-json 映射测试。"""
import json
import unittest
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fmp" / "mu_2025_q3.json"


@unittest.skipUnless(FIXTURE.is_file(), "缺少 MU FMP JSON fixture")
class FmpReportMapperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_maps_mu_q3_to_calendar_period(self):
        from app.services.fmp_report_mapper import parse_fmp_report_json

        result = parse_fmp_report_json(
            self.data,
            ticker="MU",
            fmp_year=2025,
            fmp_period="Q3",
        )
        self.assertEqual(result["suggested_fiscal_period"], "2025-Q2")
        meta = result["filing_meta"]
        self.assertEqual(meta["source"], "sec_fmp")
        self.assertEqual(meta["form_type"], "10-Q")
        self.assertEqual(meta["fmp_period"], "Q3")
        self.assertEqual(meta["filing_fq"], 3)
        self.assertEqual(meta["cash_flow_scope"], "ytd")

        income = result["extracted"]["income_statement"]["2025-Q2"]
        self.assertAlmostEqual(income["revenue"], 9301.0)
        self.assertAlmostEqual(income["net_income"], 1885.0)
        self.assertEqual(result["extracted"].get("cash_flow"), {})

    def test_extract_cover_meta(self):
        from app.services.fmp_report_mapper import extract_cover_meta

        meta = extract_cover_meta(self.data)
        self.assertEqual(meta["form_type"], "10-Q")
        self.assertEqual(meta["period_end"], "2025-05-29")
        self.assertEqual(meta["company_name"], "Micron Technology, Inc.")


if __name__ == "__main__":
    unittest.main()
