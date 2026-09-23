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
from tftcalc.odds import InvalidOddsError, ShopOdds, UnknownOddsError  # noqa: E402


class TestSetData(unittest.TestCase):
    def test_tier_totals(self):
        self.assertEqual(set_data.TIER_POOLS[4].total_copies, 140)
        self.assertEqual(set_data.TIER_POOLS[3].total_copies, 252)
        self.assertEqual(set_data.STAR_COPY_WEIGHTS[2], 3)
        self.assertEqual(set_data.STAR_COPY_WEIGHTS[3], 9)

    def test_level_11_cost_is_unknown_not_zero(self):
        """레벨 11 XP 비용은 모른다. 0 을 돌려주면 레벨업 예산이 과대 계산된다.

        Regression: 예전엔 레벨을 10 으로 클램프해 ``level_up_gold(10, 11)`` 이
        0 을 반환했다. MAX_LEVEL=11 로 선언해 놓고 비용은0 으로 나오는 상태였다.
        """
        with self.assertRaises(set_data.UnknownLevelError):
            set_data.level_up_gold(10, 11)
        with self.assertRaises(set_data.UnknownLevelError):
            set_data.level_up_gold(9, 11)
        self.assertEqual(set_data.level_up_gold(9, 10), 68)  # 정상 경로는 그대로
        self.assertEqual(set_data.level_up_gold(11, 11), 0)  # 이미 그 레벨

    def test_level_below_one_rejected(self):
        with self.assertRaises(ValueError):
            set_data.level_up_gold(0, 5)


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

    # ---- 검증(추정 금지) --------------------------------------------------
    def _odds_file(self, payload: dict) -> "ShopOdds":
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "odds.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return ShopOdds.from_json(path)

    def test_json_rejects_out_of_range_percent(self):
        """300% 를 그대로 받으면 계산기가 틀린 숫자를 정확한 척한다."""
        with self.assertRaises(InvalidOddsError):
            self._odds_file({"odds": {"8": {"4": 300}}})

    def test_json_rejects_fraction_written_as_percent(self):
        """0.30 이면 0.3% 가 된다. 소수 표기 실수를 조용히 허용하지 않는다."""
        with self.assertRaises(InvalidOddsError):
            self._odds_file({"odds": {"7": {"3": 0.30}}})

    def test_json_rejects_level_row_over_100_percent(self):
        """같은 레벨의 코스트 확률 합이 100% 를 넘을 수 없다."""
        with self.assertRaises(InvalidOddsError):
            self._odds_file({"odds": {"8": {"3": 70, "4": 60}}})

    def test_json_accepts_valid_percent_values(self):
        odds = self._odds_file({"odds": {"7": {"3": 35, "4": 20}}})
        self.assertAlmostEqual(odds.cost_odds(7, 3), 0.35)
        self.assertAlmostEqual(odds.cost_odds(7, 4), 0.20)

    def test_shipped_assumed_file_sums_to_100_percent(self):
        """배포된 가정값 파일이 자기가 주장하는 '합계 100%' 를 지키는지 검사한다.

        Regression: 레벨 8 행이 105% 였다(20+25+25+30+5).
        """
        path = ROOT / "data" / "set18_shop_odds_assumed.json"
        if not path.exists():
            self.skipTest("set18_shop_odds_assumed.json 없음")
        odds = ShopOdds.from_json(path)  # InvalidOddsError 면 여기서 실패
        rows: dict[int, float] = {}
        for (level, _cost), value in odds.cells.items():
            rows[level] = rows.get(level, 0.0) + value
        self.assertTrue(rows, "읽은 확률표가 비어 있다")
        for level, total in rows.items():
            self.assertLessEqual(total, 1.0 + 1e-9, f"Lv{level} 합계 {total * 100:.1f}%")

    # ---- 스켈레톤 채우기 지원(null = 미채움) -------------------------------
    def test_null_cell_is_unknown_not_zero(self):
        """null 은 '미채움'이다. 0% 로 추정하면 계산기가 조용히 틀린 값을 낸다."""
        odds = self._odds_file({"odds": {"8": {"3": None, "4": 30}}})
        self.assertNotIn((8, 3), odds.cells)
        self.assertIn((8, 3), odds.declared)
        self.assertEqual(odds.pending(), [(8, 3)])
        with self.assertRaises(UnknownOddsError):
            odds.cost_odds(8, 3)
        self.assertAlmostEqual(odds.cost_odds(8, 4), 0.30)

    def test_builtin_cells_are_not_counted_as_pending(self):
        """builtin 으로 이미 아는 셀은 null 로 선언돼 있어도 '미채움'이 아니다."""
        odds = self._odds_file({"odds": {"8": {"4": None}}})
        self.assertIn((8, 4), odds.declared)  # 파일이 선언은 했다
        self.assertEqual(odds.pending(), [])  # 값은 builtin 으로 안다
        self.assertTrue(odds.knows(8, 4))

    def test_pending_lists_only_unknown_declared_cells(self):
        odds = self._odds_file(
            {"odds": {"7": {"3": None, "4": 20}, "8": {"4": None, "5": None}}}
        )
        self.assertEqual(odds.pending(), [(7, 3), (8, 5)])

    def test_json_rejects_out_of_range_level(self):
        with self.assertRaises(InvalidOddsError):
            self._odds_file({"odds": {"12": {"4": 30}}})

    def test_json_rejects_out_of_range_cost(self):
        with self.assertRaises(InvalidOddsError):
            self._odds_file({"odds": {"8": {"6": 30}}})

    def test_source_chain_is_preserved(self):
        """base.source 를 이어붙여 어느 파일들이 겹쳐졌는지 알 수 있어야 한다."""
        odds = self._odds_file({"odds": {"7": {"3": 35}}})
        self.assertIn("builtin", odds.source)
        self.assertIn("odds.json", odds.source)

    def test_shipped_skeleton_covers_the_full_grid(self):
        """실전 스켈레톤이 격자 전체를 선언하는지(빠진 레벨/코스트가 조용히 생기지 않게).

        값이 전부 비어 있어도(null) 된다 — 그게 스켈레톤의 목적이다.
        """
        path = ROOT / "data" / "set18_shop_odds.json"
        if not path.exists():
            self.skipTest("set18_shop_odds.json 없음")
        odds = ShopOdds.from_json(path)
        expected = {
            (level, cost)
            for level in set_data.SHOP_ODDS_LEVELS
            for cost in set_data.SHOP_ODDS_COSTS
        }
        self.assertEqual(odds.declared, expected)
        self.assertEqual(
            len(expected),
            len(set_data.SHOP_ODDS_LEVELS) * len(set_data.SHOP_ODDS_COSTS),
        )
        # 검증된 앵커 3개는 스켈레톤이 미리 채워 둔다(사람이 덮어쓰지 않도록).
        self.assertAlmostEqual(odds.cost_odds(8, 4), 0.30)
        self.assertAlmostEqual(odds.cost_odds(10, 5), 0.25)
        self.assertAlmostEqual(odds.cost_odds(11, 5), 0.35)
        # 값이 있는 셀은 유효 범위, 레벨별 합계는 100% 이하(부분 표 허용).
        for value in odds.cells.values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
        for level in set_data.SHOP_ODDS_LEVELS:
            total = sum(v for (lvl, _), v in odds.cells.items() if lvl == level)
            self.assertLessEqual(total, 1.0 + 1e-9, f"Lv{level} 합계 {total}")


class TestGoldNeededBinarySearch(unittest.TestCase):
    """골드 예산 탐색이 이진 탐색으로 바뀌어도 결과가 선형 스캔과 같은지(L2)."""

    ODDS = ShopOdds(cells={(8, 4): 0.30}, source="테스트")
    KWARGS = dict(level=8, unit_cost=4, remaining_target=7, remaining_tier=137, need=2)

    def _linear(self, target: float, max_budget: int, trials: int) -> tuple[int, float]:
        """개선 전 구현(선형 스캔)을 그대로 재현해 참조값으로 쓴다."""
        last = 0.0
        for gold in range(max_budget + 1):
            last = pool_math.simulate_roll_down(
                self.ODDS, budget=gold, trials=trials, seed=99, **self.KWARGS
            ).p_complete
            if last >= target:
                return gold, last
        return max_budget, last

    def test_matches_linear_scan_reference(self):
        for target in (0.5, 0.8):
            with self.subTest(target=target):
                expected = self._linear(target, 120, 400)
                got = pool_math.gold_needed_for_probability(
                    self.ODDS, target_probability=target, max_budget=120,
                    trials=400, **self.KWARGS,
                )
                self.assertEqual(got, expected)

    def test_unreachable_target_returns_max_budget(self):
        gold, probability = pool_math.gold_needed_for_probability(
            self.ODDS, target_probability=0.999999, max_budget=20,
            trials=200, **self.KWARGS,
        )
        self.assertEqual(gold, 20)
        self.assertLess(probability, 0.999999)

    def test_probability_is_monotone_in_budget(self):
        """이진 탐색의 전제(단조)를 실측으로 고정한다."""
        previous = -1.0
        for budget in range(0, 121, 10):
            current = pool_math.simulate_roll_down(
                self.ODDS, budget=budget, trials=400, seed=99, **self.KWARGS
            ).p_complete
            self.assertGreaterEqual(current + 1e-12, previous)
            previous = current


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

    def test_items_held_is_not_counted_as_champion(self):
        """아이템을 챔피언으로 집계하면 풀 소모량이 오염된다.

        Regression: ``from_dict`` 가 ``items_held`` 도 기물처럼 순회했다.
        아이템 이름이 챔피언으로 분류돼 남은 사본 계산이 틀어졌다.
        """
        raw = {
            "players": [
                {
                    "name": "나",
                    "is_me": True,
                    "board": [{"champion": "Ahri", "cost": 4, "star": 1}],
                    "bench": [],
                    "items_held": [{"name": "Warmog's Armor"}],
                }
            ]
        }
        snapshot = lobby.LobbySnapshot.from_dict(raw)
        self.assertEqual(list(snapshot.copies_in_play()), ["Ahri"])

    def test_shop_key_is_ignored_by_pool_math(self):
        """상점 칸(scan 이 넣는 ``shop`` 키)은 '보유'가 아니므로 집계하지 않는다.

        Regression 방지: 누군가 'shop 도 세면 좋겠다'며 추가하면 안 된다.
        상점에 보이는 기물은 아직 사지 않은 것이고, 세면 낙관 편향이 된다.
        """
        raw = {
            "players": [
                {
                    "name": "나",
                    "is_me": True,
                    "board": [{"champion": "Ahri", "cost": 4, "star": 1}],
                    "bench": [{"champion": "Sett", "cost": 4, "star": 1}],
                    "shop": [
                        {"champion": "Ahri", "cost": 4, "star": 1},
                        {"champion": "Morgana", "cost": 4, "star": 1},
                    ],
                }
            ]
        }
        snapshot = lobby.LobbySnapshot.from_dict(raw)
        self.assertEqual(sorted(snapshot.copies_in_play()), ["Ahri", "Sett"])
        self.assertEqual(snapshot.my_copies("Morgana"), 0)


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
