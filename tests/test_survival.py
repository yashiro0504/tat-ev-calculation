"""체력/피해(생존) 축 검증.

문서(tft.ninja player-damage-calculation)의 공식과 예시를 그대로 대조한다.
  총 피해 = 스테이지 기본 피해 + 살아남은 상대 유닛 수
  기본 피해: 1=0, 2=2, 3=5, 4=8, 5=10, 6=12, 7+=17
  예시: 3스테이지 5유닛=10, 4스테이지 6유닛=14, 6스테이지 9유닛=21, 7스테이지 9유닛=26
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc import economy, survival  # noqa: E402


class TestDamageFormula(unittest.TestCase):
    def test_base_damage_table(self):
        self.assertEqual(survival.base_damage(1), 0)
        self.assertEqual(survival.base_damage(2), 2)
        self.assertEqual(survival.base_damage(3), 5)
        self.assertEqual(survival.base_damage(4), 8)
        self.assertEqual(survival.base_damage(5), 10)
        self.assertEqual(survival.base_damage(6), 12)
        self.assertEqual(survival.base_damage(7), 17)
        self.assertEqual(survival.base_damage(9), 17)

    def test_documented_worked_examples(self):
        self.assertEqual(survival.round_damage(3, 5), 10)
        self.assertEqual(survival.round_damage(4, 6), 14)
        self.assertEqual(survival.round_damage(6, 9), 21)
        self.assertEqual(survival.round_damage(6, 0), 12)
        self.assertEqual(survival.round_damage(7, 9), 26)

    def test_losses_survivable_matches_documented_rules_of_thumb(self):
        # 문서: 60HP/4스테이지(~15) -> 약 4회
        self.assertEqual(survival.losses_survivable(60, 4, enemy_survivors=7), 4)
        # 문서: 40HP/5스테이지(~18) -> 약 2회
        self.assertEqual(survival.losses_survivable(40, 5, enemy_survivors=8), 2)
        # 문서: 25HP/6스테이지(~20) -> 1회
        self.assertEqual(survival.losses_survivable(25, 6, enemy_survivors=8), 1)
        # 15HP/7스테이지(17+9=26) -> 0회(다음 패배에 끝)
        self.assertEqual(survival.losses_survivable(15, 7, enemy_survivors=9), 0)


class TestSurvivalSimulation(unittest.TestCase):
    def test_always_win_means_never_die(self):
        result = survival.simulate_survival(
            30, (4, 1), rounds=5, win_rate=1.0, trials=2_000, seed=5
        )
        self.assertEqual(result.rounds[-1].p_alive, 1.0)
        self.assertIsNone(result.expected_death_round)

    def test_always_lose_kills_in_expected_round(self):
        """승률 0이면 4-1(기본8+유닛8=16)부터 매 라운드 16씩 잃어 2라운드 뒤 사망."""
        result = survival.simulate_survival(
            30,
            (4, 1),
            rounds=5,
            win_rate=0.0,
            enemy_survivors=8.0,
            survivors_sd=0.0,
            trials=500,
            seed=5,
        )
        # 4-1: 30 -> 14, 4-2: 14 -> 사망(0)
        self.assertEqual(result.rounds[0].p_alive, 1.0)
        self.assertEqual(result.rounds[1].p_alive, 0.0)
        self.assertEqual(result.expected_death_round, "4-2")

    def test_pve_rounds_do_not_damage_by_default(self):
        result = survival.simulate_survival(
            10, (4, 3), rounds=2, win_rate=0.0, enemy_survivors=8.0, trials=200, seed=3
        )
        carousel = result.rounds[1]
        self.assertEqual(carousel.kind, "Carousel")
        self.assertEqual(int(carousel.expected_damage), 0)

    def test_survival_decreases_over_rounds(self):
        result = survival.simulate_survival(
            35, (4, 1), rounds=5, win_rate=0.35, trials=4_000, seed=9
        )
        probabilities = [row.p_alive for row in result.rounds]
        for earlier, later in zip(probabilities, probabilities[1:]):
            self.assertGreaterEqual(earlier + 1e-9, later)

    def test_higher_win_rate_survives_longer(self):
        weak = survival.simulate_survival(
            35, (4, 1), rounds=5, win_rate=0.2, trials=4_000, seed=9
        )
        strong = survival.simulate_survival(
            35, (4, 1), rounds=5, win_rate=0.7, trials=4_000, seed=9
        )
        self.assertLess(weak.rounds[-1].p_alive, strong.rounds[-1].p_alive)

    def test_invalid_win_rate_raises(self):
        with self.assertRaises(ValueError):
            survival.simulate_survival(30, (4, 1), rounds=1, win_rate=1.5)


class TestStrategyComparison(unittest.TestCase):
    def test_dominance_when_both_better(self):
        save = survival.StrategyOutcome(
            name="세이빙", win_rate=0.3, spend_now=0, p_survive=0.4,
            expected_hp=10, gold_at_target=100,
        )
        stabilize = survival.StrategyOutcome(
            name="롤", win_rate=0.6, spend_now=40, p_survive=0.8,
            expected_hp=25, gold_at_target=120,
        )
        comparison = survival.compare_stabilize_vs_save(save=save, stabilize=stabilize)
        self.assertIn("지배", comparison.verdict)
        self.assertIn("롤", comparison.verdict)

    def test_tradeoff_reports_exchange_rate(self):
        save = survival.StrategyOutcome(
            name="세이빙", win_rate=0.35, spend_now=0, p_survive=0.445,
            expected_hp=11.2, gold_at_target=120,
        )
        stabilize = survival.StrategyOutcome(
            name="40골드 롤", win_rate=0.6, spend_now=40, p_survive=0.823,
            expected_hp=18.0, gold_at_target=78,
        )
        comparison = survival.compare_stabilize_vs_save(save=save, stabilize=stabilize)
        self.assertIn("트레이드오프", comparison.verdict)
        # 37.8%p 를 42골드에 사는 셈 -> 1%p 당 약 1.1골드
        self.assertIn("교환비율", comparison.exchange)
        self.assertIn("1.1골드", comparison.exchange)
        self.assertTrue(comparison.missing_inputs)

    def test_save_dominates_when_rolling_gains_nothing(self):
        save = survival.StrategyOutcome(
            name="세이빙", win_rate=0.5, spend_now=0, p_survive=0.6,
            expected_hp=20, gold_at_target=100,
        )
        stabilize = survival.StrategyOutcome(
            name="롤", win_rate=0.5, spend_now=40, p_survive=0.6,
            expected_hp=20, gold_at_target=60,
        )
        comparison = survival.compare_stabilize_vs_save(save=save, stabilize=stabilize)
        self.assertIn("세이빙", comparison.verdict)


class TestSurvivorReporting(unittest.TestCase):
    """표의 값과 note 의 설명이 같은 quantity 를 뜻하는지.

    Regression: ``expected_survivors`` 가 승리(잔존 0)까지 섞어 나눠서,
    note 의 "패배 시 잔존 유닛 평균 8.0" 과 표의 4.04 가 서로 달랐다.
    또한 PvE/캐러셀 행의 ``base`` 는 모델(피해 0)과 반대로 스테이지 기본값을
    보여줬다.
    """

    def test_expected_survivors_is_conditional_on_loss(self):
        result = survival.simulate_survival(
            80, (4, 1), rounds=3, win_rate=0.5,
            enemy_survivors=8.0, survivors_sd=0.0, trials=5_000, seed=7,
        )
        pvp = [row for row in result.rounds if row.kind == economy.PVP]
        self.assertTrue(pvp)
        for row in pvp:
            self.assertAlmostEqual(row.expected_survivors, 8.0, delta=0.01)

    def test_no_losses_reports_assumed_value_not_zero(self):
        """패배가 한 번도 없어도 0 으로 위장하지 않는다(가정값을 그대로)."""
        result = survival.simulate_survival(
            80, (4, 1), rounds=2, win_rate=1.0,
            enemy_survivors=8.0, survivors_sd=0.0, trials=300, seed=1,
        )
        self.assertEqual(result.rounds[0].expected_survivors, 8.0)

    def test_non_pvp_round_reports_applied_base_damage(self):
        """PvE/캐러셀 행의 '기본피해' 는 그 라운드에 실제 적용되는 값이어야 한다."""
        result = survival.simulate_survival(
            60, (4, 3), rounds=2, win_rate=0.5, pve_damage=0, trials=1_000, seed=2,
        )
        self.assertEqual(result.rounds[0].kind, economy.PVP)
        self.assertEqual(result.rounds[0].base, 8)  # 4스테이지 기본(패배 시)
        self.assertEqual(result.rounds[1].kind, economy.CAROUSEL)
        self.assertEqual(result.rounds[1].base, 0)  # 스테이지 기본(8)이 아닌 적용값

    def test_custom_pve_damage_appears_as_base(self):
        result = survival.simulate_survival(
            60, (4, 3), rounds=2, win_rate=0.5, pve_damage=4, trials=500, seed=2,
        )
        self.assertEqual(result.rounds[1].base, 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)