"""股票图表涨跌幅计算单元测试。"""
import unittest

from app.services.stock_charts import (
    _calc_daily_change_pct,
    _calc_period_change_pct,
    normalize_stocks_pagination,
    paginate_asset_list,
)


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


class StocksPaginationTest(unittest.TestCase):
    def test_normalize_bounds(self):
        self.assertEqual(normalize_stocks_pagination(0, 99), (1, 24))
        self.assertEqual(normalize_stocks_pagination("2", "6"), (2, 6))

    def test_paginate_slices(self):
        items = [{"ticker": f"T{i}"} for i in range(10)]
        page_items, total_pages, page = paginate_asset_list(items, 2, 4)
        self.assertEqual(total_pages, 3)
        self.assertEqual(page, 2)
        self.assertEqual(len(page_items), 4)
        self.assertEqual(page_items[0]["ticker"], "T4")


if __name__ == "__main__":
    unittest.main()
