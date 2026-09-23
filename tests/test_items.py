"""아이템 부품 수급 모델 검증 (C단계).

검증 대상(불변식):
1. 조합식이 맞다: 알려진 조합(예: Jeweled Gauntlet = 장갑 + 큰 지팡이)과 일치.
2. 부품 요구량 = 조합식 합계.
3. 부품이 충분하면 확률 1.0, 하나도 없으면 낮다.
4. '선택 부품'(캐러셀)이 많을수록 확률이 올라간다.
5. 조합식을 모르면 추정하지 않고 예외.
6. 컴프 코어 아이템 우선순위 자르기(limit) 동작.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc import comp, items  # noqa: E402


class TestRecipeBook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = items.RecipeBook.load()

    def test_known_recipes_match(self):
        """공개된 조합식과 일치해야 한다(파서 검증)."""
        expected = {
            "Jeweled Gauntlet": ["Needlessly Large Rod", "Sparring Gloves"],
            "Blue Buff": ["Tear of the Goddess", "Tear of the Goddess"],
            "Deathblade": ["B.F. Sword", "B.F. Sword"],
            "Infinity Edge": ["B.F. Sword", "Sparring Gloves"],
            "Guinsoo's Rageblade": ["Needlessly Large Rod", "Recurve Bow"],
            "Warmog's Armor": ["Giant's Belt", "Giant's Belt"],
        }
        for item, components in expected.items():
            self.assertEqual(sorted(self.book.recipe(item)), sorted(components), item)

    def test_unknown_recipe_raises(self):
        with self.assertRaises(items.UnknownRecipeError):
            self.book.recipe("Not A Real Item")

    def test_required_components_are_summed(self):
        required = items.components_required(
            self.book, {"Jeweled Gauntlet": 1, "Blue Buff": 1}
        )
        self.assertEqual(required["Needlessly Large Rod"], 1)
        self.assertEqual(required["Sparring Gloves"], 1)
        self.assertEqual(required["Tear of the Goddess"], 2)


class TestComponentSpec(unittest.TestCase):
    def test_parse_counts(self):
        counts = items.parse_component_spec("sword:2,bow,rod:1")
        self.assertEqual(counts["B.F. Sword"], 2)
        self.assertEqual(counts["Recurve Bow"], 1)
        self.assertEqual(counts["Needlessly Large Rod"], 1)

    def test_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            items.parse_component_spec("banana")


class TestReadiness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = items.RecipeBook.load()

    CORE = {"Jeweled Gauntlet": 1, "Blue Buff": 1}  # rod+gloves, tear+tear

    def test_complete_when_components_held(self):
        have = {
            "Needlessly Large Rod": 1,
            "Sparring Gloves": 1,
            "Tear of the Goddess": 2,
        }
        readiness = items.analyze_items(self.book, self.CORE, have=have)
        self.assertEqual(readiness.p_ready, 1.0)
        self.assertEqual(readiness.missing_now, {})

    def test_missing_is_reported_and_priority_sorted(self):
        readiness = items.analyze_items(self.book, self.CORE, have={})
        self.assertEqual(readiness.missing_now["Tear of the Goddess"], 2)
        self.assertEqual(readiness.priority[0], ("Tear of the Goddess", 2))

    def test_future_components_raise_probability(self):
        low = items.analyze_items(
            self.book, self.CORE, have={}, future_components=0
        )
        mid = items.analyze_items(
            self.book, self.CORE, have={}, future_components=4, trials=8_000
        )
        high = items.analyze_items(
            self.book, self.CORE, have={}, future_components=20, trials=8_000
        )
        self.assertLess(low.p_ready, mid.p_ready)
        self.assertLess(mid.p_ready, high.p_ready)

    def test_choice_components_are_wildcards(self):
        random_only = items.analyze_items(
            self.book, self.CORE, have={}, future_components=4, trials=8_000, seed=3
        )
        with_choice = items.analyze_items(
            self.book,
            self.CORE,
            have={},
            future_components=4,
            choice_components=4,
            trials=8_000,
            seed=3,
        )
        self.assertLess(random_only.p_ready, with_choice.p_ready)
        self.assertEqual(with_choice.p_ready, 1.0)  # 부품 4개를 골라 받으면 4개만 필요

    def test_expected_shortfall_decreases(self):
        few = items.analyze_items(self.book, self.CORE, have={}, future_components=1)
        many = items.analyze_items(self.book, self.CORE, have={}, future_components=8)
        self.assertGreater(few.expected_shortfall_after, many.expected_shortfall_after)


class TestCompIntegration(unittest.TestCase):
    def test_comp_core_items_from_json(self):
        comps = comp.load_comps(ROOT / "data" / "comps_set18.json")
        self.assertGreaterEqual(len(comps), 4)
        ahri = next(item for item in comps if item.name == "아리 모르가나")
        self.assertGreater(ahri.item_count(), 0)
        self.assertIn("Jeweled Gauntlet", ahri.core_items)

    def test_limit_trims_in_priority_order(self):
        core = {"A": 1, "B": 1, "C": 1, "D": 1}
        trimmed = items.comp_core_items(core, limit=2)
        self.assertEqual(list(trimmed), ["A", "B"])

    def test_limit_zero_means_all(self):
        core = {"A": 1, "B": 2}
        self.assertEqual(items.comp_core_items(core, limit=0), core)


if __name__ == "__main__":
    unittest.main(verbosity=2)