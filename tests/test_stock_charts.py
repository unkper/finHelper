"""股票图表涨跌幅计算单元测试。"""
import unittest

from app.services.stock_charts import _calc_daily_change_pct, _calc_period_change_pct


class StockChartsChangeTest(unittest.TestCase):
    def _series(self):
        return [
            {"date": "2025-01-01", "close": 100.0},
            {"date": "2025-01-02", "close": 110.0},
            {"date": "2025-01-03", "close": 99.0},
        ]

    def test_daily_change_last_bar(self):
        self.assertEqual(_calc_daily_change_pct(self._series()), -10.0)

    def test_period_change_whole_range(self):
        self.assertEqual(_calc_period_change_pct(self._series(), 0, 2), -1.0)

    def test_period_change_sub_range(self):
        self.assertEqual(_calc_period_change_pct(self._series(), 0, 1), 10.0)


if __name__ == "__main__":
    unittest.main()
