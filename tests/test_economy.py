"""라운드 수입/롤 타이밍 모델 검증 (시간 축).

검증하는 수치(출처: tft.ninja economy/stages 가이드):
* 기본 수입: 1-2=2, 1-3=2, 1-4=3, 2-1=4, 2-2부터 5
* 이자: 10골드당 1, 최대 5
* 스트릭: 2~4연속 +1, 5연속 +2, 6+연속 +3
* 승리 보너스 +1 (기대값으로 처리)
* 라운드 구조: X-1~X-3 PvP, X-4 캐러셀, X-5~X-6 PvP, X-7 PvE
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc import economy  # noqa: E402


class TestRoundHelpers(unittest.TestCase):
    def test_parse_and_format(self):
        self.assertEqual(economy.parse_round("4-2"), (4, 2))
        self.assertEqual(economy.format_round(4, 2), "4-2")
        with self.assertRaises(ValueError):
            economy.parse_round("42")

    def test_round_types(self):
        self.assertEqual(economy.round_type(1, 3), economy.PVE)
        self.assertEqual(economy.round_type(2, 4), economy.CAROUSEL)
        self.assertEqual(economy.round_type(2, 7), economy.PVE)
        self.assertEqual(economy.round_type(4, 2), economy.PVP)
        self.assertEqual(economy.round_type(4, 4), economy.CAROUSEL)

    def test_sequence_crosses_stage_boundary(self):
        self.assertEqual(
            economy.round_sequence((2, 6), 3), [(2, 6), (2, 7), (3, 1)]
        )

    def test_base_income_ramp(self):
        self.assertEqual(economy.base_income(1, 2), 2)
        self.assertEqual(economy.base_income(1, 4), 3)
        self.assertEqual(economy.base_income(2, 1), 4)
        self.assertEqual(economy.base_income(2, 2), 5)
        self.assertEqual(economy.base_income(5, 3), 5)


class TestIncomeRules(unittest.TestCase):
    def test_interest_thresholds_and_cap(self):
        self.assertEqual(economy.interest(9), 0)
        self.assertEqual(economy.interest(10), 1)
        self.assertEqual(economy.interest(49), 4)
        self.assertEqual(economy.interest(50), 5)
        self.assertEqual(economy.interest(120), 5)  # 최대 5

    def test_streak_bonus_table(self):
        self.assertEqual(economy.streak_bonus(0), 0)
        self.assertEqual(economy.streak_bonus(1), 0)
        self.assertEqual(economy.streak_bonus(2), 1)
        self.assertEqual(economy.streak_bonus(4), 1)
        self.assertEqual(economy.streak_bonus(5), 2)
        self.assertEqual(economy.streak_bonus(6), 3)
        self.assertEqual(economy.streak_bonus(12), 3)
        # 연패도 동일
        self.assertEqual(economy.streak_bonus(-6), 3)

    def test_levelup_cost_counts_passive_xp(self):
        # 6 -> 8 레벨: 누적 XP 38 -> 134 = 96 XP. 4라운드 패시브 8 XP 차감.
        self.assertEqual(economy.levelup_cost(6, 8, 4), 88)
        self.assertEqual(economy.levelup_cost(6, 8, 0), 96)
        self.assertEqual(economy.levelup_cost(7, 7, 3), 0)


class TestProjection(unittest.TestCase):
    def test_deterministic_two_rounds(self):
        """승률 0, PvE 골드 0 으로 두면 손으로 계산한 값과 일치해야 한다."""
        state = economy.EconomyState(gold=50, level=6, streak=3, stage=3, round=5)
        projection = economy.project(
            state, rounds=2, win_rate=0.0, pve_gold=0, streak_behavior="hold"
        )
        first, second = projection.rounds
        # 3-5: 50 + 기본5 = 55 -> 이자 5 + 스트릭 1 = 61
        self.assertEqual(first.base, 5)
        self.assertEqual(first.interest_gold, 5)
        self.assertEqual(first.streak_gold, 1)
        self.assertEqual(first.gold_end, 61)
        # 3-6: 61 + 5 = 66 -> 이자 5 + 스트릭 1 = 72
        self.assertEqual(second.gold_end, 72)

    def test_levelup_spend_reduces_interest(self):
        """레벨업 지출은 그 라운드 이자 계산 전에 빠진다."""
        state = economy.EconomyState(gold=60, level=6, streak=0, stage=4, round=1)
        plans = [economy.LevelPlan((4, 1), 7)]
        projection = economy.project(
            state, rounds=1, level_plans=plans, win_rate=0.0, pve_gold=0
        )
        row = projection.rounds[0]
        self.assertGreater(row.levelup_spend, 0)
        self.assertEqual(row.target_level, 7)
        # 지출 후 골드가 낮아져 이자도 낮아진다(원래 60이면 이자 5)
        self.assertLess(row.interest_gold, 5)
        self.assertLess(row.gold_end, 60 + 5 + 5)

    def test_target_round_lookup(self):
        state = economy.EconomyState(gold=40, level=6, streak=0, stage=3, round=5)
        projection = economy.project(state, rounds=4, win_rate=0.5, pve_gold=3)
        row = projection.at(4, 1)
        self.assertIsNotNone(row)
        self.assertEqual(row.kind, economy.PVP)
        self.assertIsNone(projection.at(9, 9))

    def test_streak_reset_is_conservative(self):
        state = economy.EconomyState(gold=50, level=6, streak=6, stage=3, round=5)
        holding = economy.project(
            state, rounds=3, win_rate=0.0, pve_gold=0, streak_behavior="hold"
        )
        reset = economy.project(
            state, rounds=3, win_rate=0.0, pve_gold=0, streak_behavior="reset"
        )
        self.assertGreater(holding.summary()["gold_end"], reset.summary()["gold_end"])
        self.assertEqual(reset.rounds[0].streak_gold, 0)

    def test_pve_round_adds_gold(self):
        state = economy.EconomyState(gold=10, level=6, streak=0, stage=3, round=6)
        projection = economy.project(state, rounds=2, win_rate=0.0, pve_gold=4)
        pve_row = projection.at(3, 7)
        self.assertIsNotNone(pve_row)
        self.assertEqual(pve_row.pve_gold, 4)

    def test_roll_budget_excludes_levelup(self):
        state = economy.EconomyState(gold=100, level=6, streak=0, stage=4, round=1)
        plans = [economy.LevelPlan((4, 1), 7)]
        projection = economy.project(state, rounds=1, level_plans=plans, win_rate=0.0)
        row = projection.rounds[0]
        self.assertEqual(row.roll_budget, row.gold_start + int(row.income) - row.levelup_spend)

    def test_parse_level_plan_sorted(self):
        plans = economy.parse_level_plan("4-5:8,4-1:7")
        self.assertEqual(
            [(plan.round, plan.target_level) for plan in plans], [((4, 1), 7), ((4, 5), 8)]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)