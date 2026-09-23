"""수학 코어 검증 테스트.

핵심 원칙: 이 테스트는 '내 구현이 맞다'가 아니라
'내 구현이 공개된 벤치마크 숫자를 재현한다'를 확인한다.

벤치마크 (tft.ninja "Champion Pool Math (Set 18)", 2026-08 확인)
---------------------------------------------------------------
* 4코: 챔피언 1종당 10사본, 14종 -> 등급 전체 140사본
* 레벨 8에서 4코 확률 30%
* 예시: 아리(4코)를 3장 보유, 경쟁자 없음
     남은 사본 7 / 남은 4코 풀 137
     1칸 확률 = 30% * 7/137 = 1.53%
     1상점(5칸) 확률 = 7.4%
     20골드(10상점) 54% / 30골드 69% / 50골드 85% / 60골드 90%
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc import decision, lobby, pool_math, set_data  # noqa: E402
from tftcalc.odds import ShopOdds, UnknownOddsError  # noqa: E402


class TestSetData(unittest.TestCase):
    def test_tier_totals(self):
        self.assertEqual(set_data.TIER_POOLS[4].total_copies, 140)
        self.assertEqual(set_data.TIER_POOLS[3].total_copies, 252)
        self.assertEqual(set_data.STAR_COPY_WEIGHTS[2], 3)
        self.assertEqual(set_data.STAR_COPY_WEIGHTS[3], 9)


class TestBenchmarks(unittest.TestCase):
    def setUp(self):
        self.odds = ShopOdds.builtin()
        self.remaining_target = pool_math.remaining_target_copies(4, 3)  # 7
        self.remaining_tier = pool_math.remaining_tier_copies(4, 3)  # 137
        self.p_slot = pool_math.p_slot_is_target(0.30, self.remaining_target, self.remaining_tier)

    def test_pool_state(self):
        self.assertEqual(self.remaining_target, 7)
        self.assertEqual(self.remaining_tier, 137)

    def test_single_slot_probability(self):
        self.assertAlmostEqual(self.p_slot, 0.015328, places=5)

    def test_per_shop_probability(self):
        self.assertAlmostEqual(pool_math.p_shop_at_least_one(self.p_slot), 0.0743, places=3)

    def test_budget_table(self):
        """20/30/50/60 골드 -> 54/69/85/90% (공개 표 재현)."""
        expected = {20: 0.54, 30: 0.69, 50: 0.85, 60: 0.90}
        for gold, reference in expected.items():
            shops = pool_math.shops_for_gold(gold)
            got = pool_math.p_at_least_one_in_shops(self.p_slot, shops)
            self.assertAlmostEqual(got, reference, delta=0.012, msg=f"{gold}골드")

    def test_ereklo_formula_identity(self):
        """기대 리롤 골드 = 2*(1-(1-X/N)^5)^-1 과 동일해야 한다."""
        x_over_n = self.p_slot
        formula = 2 * (1 - (1 - x_over_n) ** 5) ** -1
        got = pool_math.expected_roll_gold_for_next_copy(self.p_slot)
        self.assertAlmostEqual(got, formula, places=9)

    def test_shops_for_80pct_is_ceiling(self):
        p_shop = pool_math.p_shop_at_least_one(self.p_slot)
        shops = pool_math._shops_for_probability(self.p_slot, 0.8)  # noqa: SLF001
        self.assertEqual(shops, math.ceil(math.log(0.2) / math.log(1 - p_shop)))



class TestOddsTable(unittest.TestCase):
    def test_unknown_cell_raises_instead_of_guessing(self):
        odds = ShopOdds.builtin()
        with self.assertRaises(UnknownOddsError):
            odds.cost_odds(7, 3)

    def test_json_override_and_merge(self):
        payload = {
            "patch": "18.1",
            "odds": {"8": {"4": 32, "3": 30}, "7": {"3": 35}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "odds.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            odds = ShopOdds.from_json(path)
        self.assertAlmostEqual(odds.cost_odds(8, 3), 0.30)
        self.assertAlmostEqual(odds.cost_odds(7, 3), 0.35)
        self.assertAlmostEqual(odds.cost_odds(8, 4), 0.32)  # 파일 값이 우선
        self.assertTrue(odds.knows(10, 5))  # builtin 셀 유지


class TestMonteCarlo(unittest.TestCase):
    def setUp(self):
        self.odds = ShopOdds.builtin()

    def test_matches_analytic_for_single_copy(self):
        """need=1 이면 MC 는 해석해(상점 독립)와 오차 범위 내에서 일치해야 한다."""
        p_slot = pool_math.p_slot_is_target(0.30, 7, 137)
        analytic = pool_math.p_at_least_one_in_shops(p_slot, pool_math.shops_for_gold(60))
        result = pool_math.simulate_roll_down(
            self.odds,
            level=8,
            unit_cost=4,
            remaining_target=7,
            remaining_tier=137,
            need=1,
            budget=60,
            trials=20_000,
            seed=4242,
        )
        self.assertAlmostEqual(result.p_complete, analytic, delta=0.02)

    def test_contest_increases_cost(self):
        """같은 조건에서 남은 사본이 적을수록 기대 골드가 커져야 한다."""
        cheap = pool_math.simulate_roll_down(
            self.odds, level=8, unit_cost=4, remaining_target=8,
            remaining_tier=138, need=2, budget=80, trials=8_000, seed=1,
        )
        contested = pool_math.simulate_roll_down(
            self.odds, level=8, unit_cost=4, remaining_target=2,
            remaining_tier=132, need=2, budget=80, trials=8_000, seed=1,
        )
        self.assertGreater(contested.mean_total_gold, cheap.mean_total_gold)
        self.assertLess(contested.p_complete, cheap.p_complete)

    def test_pool_exhaustion_is_reported(self):
        """풀에 남은 사본 < 필요한 장수 면 예산과 무관하게 '구조적 불가'로 보고된다."""
        result = pool_math.simulate_roll_down(
            self.odds, level=8, unit_cost=4, remaining_target=1,
            remaining_tier=131, need=3, budget=80, trials=4_000, seed=3,
        )
        self.assertTrue(result.impossible)
        self.assertEqual(result.p_complete, 0.0)
        self.assertEqual(result.pool_exhausted_rate, 1.0)

    def test_budget_too_small_is_not_pool_exhaustion(self):
        """사본은 풀에 있지만 골드가 부족한 경우는 풀 고갈과 구분되어야 한다."""
        result = pool_math.simulate_roll_down(
            self.odds, level=8, unit_cost=4, remaining_target=1,
            remaining_tier=131, need=1, budget=2, trials=4_000, seed=11,
        )
        self.assertFalse(result.impossible)
        self.assertLess(result.p_complete, 0.05)
        self.assertLess(result.pool_exhausted_rate, 0.05)

    def test_budget_zero_is_safe(self):
        result = pool_math.simulate_roll_down(
            self.odds, level=8, unit_cost=4, remaining_target=7,
            remaining_tier=137, need=1, budget=0, trials=100, seed=5,
        )
        self.assertEqual(result.p_complete, 0.0)
        self.assertEqual(result.mean_total_gold, 0.0)


class TestLobbySnapshot(unittest.TestCase):
    SNAPSHOT = {
        "players": [
            {"name": "나", "is_me": True, "board": [{"champion": "Ahri", "cost": 4, "star": 1}]},
            {"name": "A", "board": [], "bench": [{"champion": "Ahri", "cost": 4, "star": 2}]},
            {"name": "B", "board": [{"champion": "Ahri", "cost": 4, "star": 1}]},
        ]
    }

    def _snapshot(self) -> "lobby.LobbySnapshot":
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snap.json"
            path.write_text(json.dumps(self.SNAPSHOT), encoding="utf-8")
            return lobby.LobbySnapshot.from_json(path)

    def test_star_weighted_aggregation(self):
        snapshot = self._snapshot()
        # 나 1 + A 3(2성) + B 1 = 5
        self.assertEqual(snapshot.copies_in_play()["Ahri"], 5)
        self.assertEqual(snapshot.my_copies("Ahri"), 1)
        self.assertEqual(snapshot.opponents_copies("Ahri"), 4)

    def test_remaining_and_confidence(self):
        snapshot = self._snapshot()
        remaining = pool_math.remaining_target_copies(4, snapshot.copies_in_play()["Ahri"])
        self.assertEqual(remaining, 5)
        self.assertAlmostEqual(snapshot.confidence(), 2 / 7)
        self.assertIn("2/7", snapshot.confidence_note())

    def test_unknown_star_is_rejected(self):
        with self.assertRaises(ValueError):
            lobby.UnitInPlay(champion="Ahri", cost=4, star=4).copies


class TestDecision(unittest.TestCase):
    def setUp(self):
        self.odds = ShopOdds.builtin()

    def test_unit_report_flags_impossible_line(self):
        report = decision.unit_cost_report(
            self.odds,
            level=8,
            cost=4,
            copies_of_target_in_play=10,
            copies_in_play_of_tier=140,
            own_copies=1,
            target_star=2,
            budget=60,
        )
        self.assertEqual(report["remaining_target"], 0)
        self.assertIn("풀에 사본이 없다", str(report["verdict"]))

    def test_uncontested_line_dominates_contested(self):
        uncontested = decision.RollLine(
            name="Ahri(무경쟁)", level=8, unit_cost=4,
            remaining_target=9, remaining_tier=139, need=2, budget=60,
        )
        contested = decision.RollLine(
            name="Ahri(3명 겹침)", level=8, unit_cost=4,
            remaining_target=1, remaining_tier=131, need=2, budget=60,
        )
        comparison = decision.compare_lines(
            self.odds, uncontested, contested, trials=6_000
        )
        self.assertTrue(comparison.dominated)
        self.assertEqual(comparison.preferred, "Ahri(무경쟁)")
        self.assertGreater(comparison.p_a, comparison.p_b)
        self.assertEqual(comparison.p_b, 0.0)  # 겹침 라인은 풀 부족으로 구조적 불가
        self.assertIn("풀에 남은 사본이 부족해", comparison.reason)

    def test_trade_off_is_reported_not_hidden(self):
        """예산과 확률이 상충하면 결론을 지어내지 않고 트레이드오프로 보고해야 한다."""
        small_budget = decision.RollLine(
            name="30골드만", level=8, unit_cost=4,
            remaining_target=9, remaining_tier=139, need=2, budget=30,
        )
        big_budget = decision.RollLine(
            name="100골드", level=8, unit_cost=4,
            remaining_target=9, remaining_tier=139, need=2, budget=100,
        )
        comparison = decision.compare_lines(
            self.odds, small_budget, big_budget, trials=5_000
        )
        self.assertFalse(comparison.dominated)
        self.assertIsNone(comparison.preferred)
        self.assertIn("트레이드오프", comparison.reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
