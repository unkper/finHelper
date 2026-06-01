"""游戏化规则引擎单元测试（不依赖 Flask）。"""
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "financial_game_rules",
    _ROOT / "app" / "services" / "financial_game_rules.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
build_game_rules = _mod.build_game_rules


import unittest


class SnowGameRulesTest(unittest.TestCase):
    def test_snow_like_fy_payload(self):
        self._run_snow_test()

    def _run_snow_test(self):
        payload = {
            "focus_period": "2026-Q4",
            "ticker": "SNOW",
            "unit": "millions",
            "kpis": {
                "2026-Q4": {
                    "revenue": {"value": 4472.3, "yoy_pct": 29},
                    "net_profit": {"value": -1300, "yoy_pct": None},
                    "nrr_pct": 125,
                    "free_cash_flow": 1120.3,
                    "rpo": 9771.5,
                }
            },
            "cash_flow": {"2026-Q4": {"operating": 1221.9}},
            "red_flags": [
                {"code": "aws", "message": "Substantial reliance on AWS for cloud infrastructure"},
            ],
        }
        rules = build_game_rules(payload)
        self.assertIn(rules["run_verdict"], ("winning", "stalemate", "losing"))
        self.assertGreaterEqual(rules["hp_pct"], 5)
        keys = {s["key"] for s in rules["stats"]}
        self.assertIn("revenue", keys)
        self.assertEqual(rules["boss_defaults"][0]["threat"], "high")
        self.assertEqual(rules["boss_defaults"][0]["hp_bars"], 3)


if __name__ == "__main__":
    unittest.main()
