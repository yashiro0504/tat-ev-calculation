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


class TestWinBonusExpectation(unittest.TestCase):
    """승리 보너스 기대값이 사라지지 않는지(은행원 반올림 회귀 방지).

    Regression: ``round(win_gold)`` 는 ``round(0.5) == 0`` 이라서 기본 승률 50%
    에서 보너스가 통째로 없어졌고, ``income`` 프로퍼티와 ``gold_end`` 가 어긋났다.
    기존 테스트가 전부 ``win_rate=0.0`` 을 써서 이 경로를 전혀 지나지 않았다.
    """

    def _project(self, win_rate: float, rounds: int = 10):
        state = economy.EconomyState(gold=0, level=7, streak=0, stage=3, round=1)
        return economy.project(
            state, rounds=rounds, win_rate=win_rate, pve_gold=0,
            streak_behavior="reset",
        )

    def test_default_half_win_rate_is_not_rounded_away(self):
        projection = self._project(0.5)
        pvp_rounds = [row for row in projection.rounds if row.kind == economy.PVP]
        credited = sum(row.win_gold for row in projection.rounds)
        self.assertGreater(len(pvp_rounds), 0)
        # 이월이라 기대값을 잃지 않는다(반올림이면 0 이 된다).
        self.assertAlmostEqual(credited, len(pvp_rounds) * 0.5, delta=0.5)
        self.assertNotEqual(credited, 0)

    def test_expectation_preserved_for_other_rates(self):
        for win_rate in (0.35, 0.6):
            with self.subTest(win_rate=win_rate):
                projection = self._project(win_rate)
                pvp_rounds = [r for r in projection.rounds if r.kind == economy.PVP]
                credited = sum(r.win_gold for r in projection.rounds)
                self.assertAlmostEqual(
                    credited, len(pvp_rounds) * win_rate, delta=1.0
                )

    def test_income_reproduces_gold_change(self):
        """income(합)으로 실제 골드 증가를 재현할 수 있어야 한다."""
        for win_rate in (0.35, 0.5, 0.6):
            with self.subTest(win_rate=win_rate):
                for row in self._project(win_rate).rounds:
                    self.assertEqual(
                        row.gold_end,
                        row.gold_start - row.levelup_spend + int(row.income),
                        f"win_rate={win_rate} {row.stage}-{row.round}",
                    )

    def test_roll_budget_matches_gold_end(self):
        """roll_budget 이 종료골드와 다르면 예산 계획이 실제 보유와 어긋난다."""
        for win_rate in (0.35, 0.5, 0.6):
            with self.subTest(win_rate=win_rate):
                for row in self._project(win_rate).rounds:
                    self.assertEqual(row.roll_budget, row.gold_end)

    def test_zero_win_rate_still_grants_nothing(self):
        """win_rate=0 이면 기존 테스트와 동일하게 보너스가 없어야 한다."""
        projection = self._project(0.0)
        self.assertTrue(all(row.win_gold == 0.0 for row in projection.rounds))


class TestRoundSequenceAndIncome(unittest.TestCase):
    """스테이지 1 은 4라운드, 1-1 수입은 출처에 없다(L3)."""

    def test_stage_one_has_four_rounds(self):
        self.assertEqual(economy.stage_length(1), 4)
        self.assertEqual(economy.stage_length(2), 7)
        self.assertEqual(economy.stage_length(9), 7)

    def test_sequence_does_not_invent_stage_one_rounds(self):
        """Regression: 예전엔 (1,5)(1,6)(1,7) 같은 없는 라운드를 만들었다."""
        sequence = economy.round_sequence((1, 1), 10)
        self.assertNotIn((1, 5), sequence)
        self.assertNotIn((1, 7), sequence)
        self.assertEqual(
            sequence[:5], [(1, 1), (1, 2), (1, 3), (1, 4), (2, 1)]
        )

    def test_documented_stage_one_incomes_unchanged(self):
        self.assertEqual(economy.base_income(1, 2), 2)
        self.assertEqual(economy.base_income(1, 3), 2)
        self.assertEqual(economy.base_income(1, 4), 3)

    def test_undocumented_stage_one_round_one_raises(self):
        """출처가 1-2 부터 주므로 1-1 을 추정하지 않는다(예전엔 5 를 돌려줬다)."""
        with self.assertRaises(economy.UnknownIncomeError):
            economy.base_income(1, 1)


class TestProjectionHorizon(unittest.TestCase):
    """목표 라운드를 담는 전망 길이 계산(M5/L6: 30·40 하드코딩을 한곳으로)."""

    def test_rounds_between_is_inclusive(self):
        self.assertEqual(economy.rounds_between((4, 1), (4, 1)), 1)
        self.assertEqual(economy.rounds_between((4, 1), (4, 5)), 5)
        self.assertEqual(economy.rounds_between((4, 1), (5, 1)), 8)  # 4스테이지 7라운드 + 1

    def test_out_of_range_target_raises_instead_of_falling_back(self):
        """Regression: 예전엔 못 찾으면 --rounds 로 조용히 대체해 잘못된 판정을 읽었다."""
        with self.assertRaises(ValueError):
            economy.rounds_between((4, 1), (11, 1))
        with self.assertRaises(ValueError):
            economy.rounds_between((4, 5), (4, 1))  # 과거 라운드

    def test_projection_horizon_keeps_requested_length(self):
        """--rounds 가 목표보다 크면 그대로, 작으면 목표까지 늘린다."""
        self.assertEqual(economy.projection_horizon((4, 1), (4, 5), 6), 6)
        self.assertEqual(economy.projection_horizon((4, 1), (4, 5), 2), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)