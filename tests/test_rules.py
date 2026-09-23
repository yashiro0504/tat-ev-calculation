"""규칙 기반 판정 검증 (L6 분리 + 기존 규칙 동작 고정).

``rules.recommend_action`` 은 "사실들 -> 문자열" 인 순수 함수다. 시뮬레이션을 돌리지
않으므로 시행 수/랜덤에 흔들리지 않고 정확히 검증할 수 있다.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc import rules, survival  # noqa: E402


def _outcome(name: str, p_survive: float, gold_at_target: int, win_rate: float = 0.5):
    return survival.StrategyOutcome(
        name=name,
        win_rate=win_rate,
        spend_now=0,
        p_survive=p_survive,
        expected_hp=20.0,
        gold_at_target=gold_at_target,
    )


def _comparison(save_p: float, roll_p: float):
    return survival.compare_stabilize_vs_save(
        save=_outcome("세이빙", save_p, 100),
        stabilize=_outcome("롤", roll_p, 60, win_rate=0.6),
    )


class TestRecommendAction(unittest.TestCase):
    def test_stabilize_when_rolling_lifts_survival_and_saving_is_risky(self):
        action = rules.recommend_action(
            target_label="4-5", roll_gold=40, need_gold=None, roll_budget=60,
            p_survive_target=0.3, best=None, comparison=_comparison(0.3, 0.8),
        )
        self.assertIn("안정화", action)
        self.assertIn("40골드", action)

    def test_saving_extension_when_gold_short(self):
        action = rules.recommend_action(
            target_label="4-5", roll_gold=0, need_gold=150, roll_budget=60,
            p_survive_target=0.6, best=None, comparison=None,
        )
        self.assertIn("세이빙 연장", action)
        self.assertIn("90골드 부족", action)

    def test_roll_when_top_comp_is_likely(self):
        action = rules.recommend_action(
            target_label="4-5", roll_gold=0, need_gold=None, roll_budget=60,
            p_survive_target=0.6,
            best={"comp": "아리 모르가나", "p_complete": 0.7}, comparison=None,
        )
        self.assertIn("계획대로 리롤", action)
        self.assertIn("아리 모르가나", action)

    def test_health_risk_when_survival_low(self):
        action = rules.recommend_action(
            target_label="4-5", roll_gold=0, need_gold=None, roll_budget=60,
            p_survive_target=0.3,
            best={"comp": "X", "p_complete": 0.1}, comparison=None,
        )
        self.assertIn("체력 리스크", action)

    def test_observe_is_the_fallback(self):
        action = rules.recommend_action(
            target_label="4-5", roll_gold=0, need_gold=None, roll_budget=60,
            p_survive_target=0.6,
            best={"comp": "X", "p_complete": 0.1}, comparison=None,
        )
        self.assertIn("관망", action)

    def test_small_survival_gain_does_not_trigger_stabilize(self):
        """생존 이득이 10%p 이하면 규칙 1 이 발동하지 않는다(표시 규칙 경계)."""
        action = rules.recommend_action(
            target_label="4-5", roll_gold=40, need_gold=None, roll_budget=60,
            p_survive_target=0.3, best=None, comparison=_comparison(0.30, 0.35),
        )
        self.assertNotIn("안정화(롤", action)


class TestBuildBasis(unittest.TestCase):
    def test_basis_lists_facts_only(self):
        basis = rules.build_basis(
            target_label="4-5", roll_budget=60, target_level=8,
            p_survive_target=0.462, best=None, need_gold=None, comparison=None,
        )
        self.assertEqual(len(basis), 2)
        self.assertIn("예산 60골드", basis[0])
        self.assertIn("46.2%", basis[1])

    def test_basis_includes_optional_facts(self):
        basis = rules.build_basis(
            target_label="4-5", roll_budget=60, target_level=8,
            p_survive_target=0.4,
            best={"comp": "아리", "p_complete": 0.55},
            need_gold=150, comparison=_comparison(0.3, 0.8),
        )
        joined = "\n".join(basis)
        self.assertIn("1순위 컴프 아리", joined)
        self.assertIn("필요 골드 150", joined)
        self.assertIn("세이빙 생존", joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
