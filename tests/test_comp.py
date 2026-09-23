"""컴프(덱) 엔진 검증 테스트.

핵심 불변식(invariant) 3개를 검증한다.
1. 동시 완성 <= 격리 완성 : 같은 골드를 컴프 전체가 나누므로 유닛별 확률은 내려간다.
2. 유닛이 많은 컴프일수록 동시 완성 확률은 낮다.
3. 풀에 남은 사본 < 필요한 장수 면 '불가'로 보고되고, 추정으로 메우지 않는다.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc import comp, lobby  # noqa: E402
from tftcalc.odds import ShopOdds  # noqa: E402

#: 테스트용 확률표: 8레벨 3코 25%, 4코 30% (4코는 교차 확인된 값)
TEST_ODDS = ShopOdds(cells={(8, 3): 0.25, (8, 4): 0.30}, source="테스트")


class TestUnitOutlook(unittest.TestCase):
    def test_contested_is_worse_than_uncontested(self):
        unit = comp.UnitTarget(champion="Karma", cost=4, target_star=2)
        uncontested = comp.unit_outlook(
            TEST_ODDS,
            unit=unit,
            owned_copies=1,
            copies_in_play={"Karma": 1},
            tier_in_play={4: 1},
            level=8,
            roll_budget=60,
            trials=4_000,
            seed=1,
        )
        contested = comp.unit_outlook(
            TEST_ODDS,
            unit=unit,
            owned_copies=1,
            copies_in_play={"Karma": 7},
            tier_in_play={4: 14},
            level=8,
            roll_budget=60,
            trials=4_000,
            seed=1,
        )
        self.assertGreater(uncontested["p_star2"], contested["p_star2"])
        self.assertLess(
            uncontested["expected_roll_gold_next_copy"],
            contested["expected_roll_gold_next_copy"],
        )

    def test_star3_is_much_harder_than_star2(self):
        unit = comp.UnitTarget(champion="Sentry", cost=3, target_star=3)
        outlook = comp.unit_outlook(
            TEST_ODDS,
            unit=unit,
            owned_copies=2,
            copies_in_play={"Sentry": 4},
            tier_in_play={3: 10},
            level=8,
            roll_budget=100,
            trials=4_000,
            seed=2,
        )
        self.assertGreater(outlook["p_star2"], outlook["p_star3"])
        self.assertLess(outlook["p_star2"], 1.0)

    def test_pool_shortage_reported_per_star(self):
        unit = comp.UnitTarget(champion="Karma", cost=4, target_star=3)
        outlook = comp.unit_outlook(
            TEST_ODDS,
            unit=unit,
            owned_copies=1,
            copies_in_play={"Karma": 7},
            tier_in_play={4: 14},
            level=8,
            roll_budget=80,
            trials=200,
            seed=3,
        )
        self.assertEqual(outlook["p_star3"], 0.0)
        self.assertIsNone(outlook["gold_star3"])
        self.assertIn("풀 부족", str(outlook["note_star3"]))
        # 2성은 여전히 가능해야 한다 (남은 3장 >= 필요 2장)
        self.assertGreater(outlook["p_star2"], 0.0)

    def test_unknown_cost_odds_raises(self):
        unit = comp.UnitTarget(champion="Yunara", cost=5, target_star=2)
        with self.assertRaises(LookupError):
            comp.unit_outlook(
                TEST_ODDS,
                unit=unit,
                owned_copies=0,
                copies_in_play={"Yunara": 1},
                tier_in_play={5: 1},
                level=8,
                roll_budget=60,
                trials=100,
            )


class TestSimulateComp(unittest.TestCase):
    def _comp(self, *units: tuple[str, int, int], name: str = "테스트컴프") -> comp.Comp:
        return comp.Comp(
            name=name,
            units=[
                comp.UnitTarget(champion=champion, cost=cost, target_star=star)
                for champion, cost, star in units
            ],
        )

    def test_shared_budget_lowers_per_unit_odds(self):
        """컴프 동시 완성은 '격리'보다 유닛별 확률이 낮아야 한다(골드 공유)."""
        single = self._comp(("Karma", 4, 2))
        both = self._comp(("Karma", 4, 2), ("Varus", 4, 2))
        copies = {"Karma": 4, "Varus": 4}
        tier = {4: 8}
        owned = {"Karma": 2, "Varus": 1}

        isolated = comp.unit_outlook(
            TEST_ODDS,
            unit=single.units[0],
            owned_copies=owned["Karma"],
            copies_in_play=copies,
            tier_in_play=tier,
            level=8,
            roll_budget=80,
            trials=4_000,
            seed=4,
        )
        together = comp.simulate_comp(
            TEST_ODDS,
            comp=both,
            owned_by_champion=owned,
            copies_in_play=copies,
            tier_in_play=tier,
            level=8,
            roll_budget=80,
            trials=4_000,
            seed=4,
        )
        self.assertLessEqual(
            together["unit_completion"]["Karma"], isolated["p_star2"] + 0.02
        )

    def test_more_units_means_lower_completion(self):
        copies = {"Karma": 0, "Varus": 0, "Sentry": 0, "Leona": 0}
        tier = {4: 0, 3: 0}
        owned = {"Karma": 1, "Varus": 1, "Sentry": 1, "Leona": 1}
        small = comp.simulate_comp(
            TEST_ODDS,
            comp=self._comp(("Karma", 4, 2)),
            owned_by_champion=owned,
            copies_in_play=copies,
            tier_in_play=tier,
            level=8,
            roll_budget=80,
            trials=4_000,
            seed=5,
        )
        large = comp.simulate_comp(
            TEST_ODDS,
            comp=self._comp(
                ("Karma", 4, 2), ("Varus", 4, 2), ("Sentry", 3, 2), ("Leona", 3, 2)
            ),
            owned_by_champion=owned,
            copies_in_play=copies,
            tier_in_play=tier,
            level=8,
            roll_budget=80,
            trials=4_000,
            seed=5,
        )
        self.assertGreater(small["p_complete"], large["p_complete"])

    def test_impossible_unit_blocks_whole_comp(self):
        two_units = self._comp(("Karma", 4, 3), ("Sentry", 3, 2))
        result = comp.simulate_comp(
            TEST_ODDS,
            comp=two_units,
            owned_by_champion={"Karma": 1, "Sentry": 1},
            copies_in_play={"Karma": 8, "Sentry": 2},
            tier_in_play={4: 9, 3: 3},
            level=8,
            roll_budget=80,
            trials=500,
            seed=6,
        )
        self.assertIn("Karma", result["impossible"])
        self.assertEqual(result["p_complete"], 0.0)

    def test_unknown_cost_reported_not_guessed(self):
        result = comp.simulate_comp(
            TEST_ODDS,
            comp=self._comp(("Yunara", 5, 2)),
            owned_by_champion={"Yunara": 0},
            copies_in_play={"Yunara": 1},
            tier_in_play={5: 1},
            level=8,
            roll_budget=60,
            trials=200,
            seed=7,
        )
        self.assertIn("error", result)
        self.assertIsNone(result["p_complete"])

    def test_already_complete_is_one_hundred(self):
        result = comp.simulate_comp(
            TEST_ODDS,
            comp=self._comp(("Karma", 4, 2)),
            owned_by_champion={"Karma": 3},
            copies_in_play={"Karma": 3},
            tier_in_play={4: 3},
            level=8,
            roll_budget=60,
            trials=100,
            seed=8,
        )
        self.assertEqual(result["p_complete"], 1.0)
        self.assertEqual(result["mean_total_gold"], 0.0)


class TestRankComps(unittest.TestCase):
    def test_ranking_sorted_and_errors_last(self):
        comps = [
            comp.Comp(name="소형", units=[comp.UnitTarget("Karma", 4, 2)]),
            comp.Comp(
                name="대형",
                units=[
                    comp.UnitTarget("Karma", 4, 2),
                    comp.UnitTarget("Varus", 4, 2),
                    comp.UnitTarget("Sentry", 3, 2),
                ],
            ),
            comp.Comp(name="데이터부족", units=[comp.UnitTarget("Yunara", 5, 2)]),
        ]
        ranking = comp.rank_comps(
            TEST_ODDS,
            comps=comps,
            owned_by_champion={"Karma": 1, "Varus": 1, "Sentry": 1, "Yunara": 0},
            copies_in_play={"Karma": 2, "Varus": 1, "Sentry": 1, "Yunara": 1},
            tier_in_play={4: 3, 3: 1, 5: 1},
            level=8,
            roll_budget=80,
            trials=2_000,
            seed=9,
        )
        self.assertEqual(ranking[0]["comp"], "소형")
        self.assertEqual(ranking[-1]["comp"], "데이터부족")
        self.assertIn("error", ranking[-1])


class TestSnapshotBridge(unittest.TestCase):
    def test_pool_state_from_snapshot_uses_star_weights(self):
        payload = {
            "players": [
                {
                    "name": "나",
                    "is_me": True,
                    "board": [{"champion": "Karma", "cost": 4, "star": 2}],
                },
                {
                    "name": "상대",
                    "bench": [{"champion": "Karma", "cost": 4, "star": 1}],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snap.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            snapshot = lobby.LobbySnapshot.from_json(path)

        copies, tier = comp.pool_state_from_snapshot(snapshot)
        self.assertEqual(copies["Karma"], 4)  # 2성(3사본) + 1성(1사본)
        self.assertEqual(tier[4], 4)
        self.assertEqual(snapshot.my_copies("Karma"), 3)


class TestCompLevelAndLevelup(unittest.TestCase):
    """A단계 기능: 컴프별 롤 레벨 + 레벨업 골드 정산."""

    LEVEL_ODDS = ShopOdds(
        cells={(6, 3): 0.50, (8, 3): 0.25, (8, 4): 0.30}, source="테스트"
    )

    def test_comp_level_overrides_cli_level(self):
        """컴프가 level 을 지정하면 그 레벨의 상점 확률을 쓴다(3코 리롤 vs fast-8)."""
        reroll_lv6 = comp.Comp(
            name="리롤Lv6", units=[comp.UnitTarget("Sentry", 3, 2)], roll_level=6
        )
        same_lv8 = comp.Comp(
            name="같은유닛Lv8", units=[comp.UnitTarget("Sentry", 3, 2)], roll_level=8
        )
        ranking = comp.rank_comps(
            self.LEVEL_ODDS,
            comps=[reroll_lv6, same_lv8],
            owned_by_champion={"Sentry": 1},
            copies_in_play={"Sentry": 2},
            tier_in_play={3: 2},
            level=8,  # CLI 기본값은 8이지만 컴프가 6을 지정했다
            roll_budget=60,
            trials=3_000,
            seed=11,
        )
        by_name = {row["comp"]: row for row in ranking}
        self.assertEqual(by_name["리롤Lv6"]["level"], 6)
        self.assertEqual(by_name["같은유닛Lv8"]["level"], 8)
        self.assertGreater(
            by_name["리롤Lv6"]["p_complete"], by_name["같은유닛Lv8"]["p_complete"]
        )

    def test_gold_mode_deducts_levelup_before_rolling(self):
        """총 골드 모드: 레벨업 비용을 먼저 떼고 남은 골드로 롤한다."""
        fast8 = comp.Comp(
            name="fast8", units=[comp.UnitTarget("Karma", 4, 2)], roll_level=8
        )
        reroll6 = comp.Comp(
            name="리롤6", units=[comp.UnitTarget("Sentry", 3, 2)], roll_level=6
        )
        ranking = comp.rank_comps(
            self.LEVEL_ODDS,
            comps=[reroll6, fast8],
            owned_by_champion={"Karma": 1, "Sentry": 1},
            copies_in_play={"Karma": 2, "Sentry": 2},
            tier_in_play={4: 2, 3: 2},
            level=8,
            gold_total=100,
            current_level=6,
            trials=2_000,
            seed=12,
        )
        by_name = {row["comp"]: row for row in ranking}
        self.assertEqual(by_name["리롤6"]["levelup_gold"], 0)  # 6 -> 6
        self.assertEqual(by_name["리롤6"]["roll_budget"], 100)
        self.assertEqual(by_name["fast8"]["levelup_gold"], 96)  # 누적 XP 38 -> 134
        self.assertEqual(by_name["fast8"]["roll_budget"], 4)
        self.assertGreaterEqual(by_name["fast8"]["mean_total_gold"], 96)

    def test_target_star_inheritance_and_override(self):
        payload = {
            "comps": [
                {
                    "name": "혼합",
                    "level": 7,
                    "target_star": 3,
                    "units": [
                        {"champion": "Sentry", "cost": 3},
                        {"champion": "Warwick", "cost": 3, "target_star": 2},
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "comps.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            comps = comp.load_comps(path)
        loaded = comps[0]
        self.assertEqual(loaded.roll_level, 7)
        self.assertEqual(loaded.units[0].target_star, 3)  # 컴프 기본값 상속
        self.assertEqual(loaded.units[1].target_star, 2)  # 유닛별 덮어쓰기
        self.assertEqual(loaded.level_for(8), 7)

    def test_requires_gold_or_budget(self):
        with self.assertRaises(ValueError):
            comp.rank_comps(
                self.LEVEL_ODDS,
                comps=[comp.Comp(name="x", units=[comp.UnitTarget("Sentry", 3, 2)])],
                owned_by_champion={},
                copies_in_play={},
                tier_in_play={},
                level=8,
                trials=10,
            )


class TestUnitCompletion(unittest.TestCase):
    """unit_completion / unit_count 가 분해 표와 헤더에 정확히 반영되는지.

    Regression: ``unit_completion`` 이 목표 미달 유닛(targets)만 키로 삼아서,
    이미 2성인 유닛이 "1위 컴프 분해" 표에서 조용히 빠졌다. ``unit_count`` 도
    미달 유닛만 세서 헤더의 "유닛"(컴프 규모)과 의미가 달랐다.
    """

    ODDS = ShopOdds(cells={(8, 4): 0.30}, source="테스트")

    def _comp(self) -> comp.Comp:
        return comp.Comp(
            name="mixed",
            units=[comp.UnitTarget("Done", 4, 2), comp.UnitTarget("Need", 4, 2)],
        )

    def _simulate(self, comp_obj: comp.Comp, owned, in_play, tier) -> dict:
        return comp.simulate_comp(
            self.ODDS,
            comp=comp_obj,
            owned_by_champion=owned,
            copies_in_play=in_play,
            tier_in_play=tier,
            level=8,
            roll_budget=40,
            trials=200,
            seed=1,
        )

    def test_completion_covers_every_unit_including_done(self):
        result = self._simulate(
            self._comp(),
            owned={"Done": 3, "Need": 1},
            in_play={"Done": 3, "Need": 1},
            tier={4: 4},
        )
        self.assertEqual(set(result["unit_completion"]), {"Done", "Need"})
        self.assertEqual(result["unit_completion"]["Done"], 1.0)

    def test_unit_count_is_comp_size_not_pending(self):
        """헤더 '유닛' 은 컴프 규모여야 한다(보유 여부에 따라 달라지면 안 된다)."""
        result = self._simulate(
            self._comp(),
            owned={"Done": 3, "Need": 1},
            in_play={"Done": 3, "Need": 1},
            tier={4: 4},
        )
        self.assertEqual(result["unit_count"], 2)

    def test_impossible_comp_keeps_done_unit_at_one(self):
        """컴프 전체가 '불가'여도 완성된 유닛까지 0.0 으로 치면 안 된다."""
        blocked = comp.Comp(
            name="blocked",
            units=[comp.UnitTarget("Done", 4, 2), comp.UnitTarget("Gone", 4, 3)],
        )
        result = self._simulate(
            blocked,
            owned={"Done": 3, "Gone": 0},
            # Gone 은 3성(9장) 중 9장이 이미 상대 소유 -> 남은 1장 < 필요 9장
            in_play={"Done": 3, "Gone": 9},
            tier={4: 12},
        )
        self.assertEqual(result["impossible"], ["Gone"])
        self.assertEqual(result["unit_completion"]["Done"], 1.0)
        self.assertEqual(result["unit_completion"]["Gone"], 0.0)
        self.assertEqual(result["unit_count"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)