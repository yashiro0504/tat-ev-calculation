"""몬테카를로 시행 수 기본값이 한곳(trials.py)에서 오는지 검증 (L7).

예전엔 같은 "시행 수"가 CLI 기본값(1_500/4_000/20_000)과 라이브러리 함수
기본값(3_000/4_000/20_000)에 서로 다르게 하드코딩돼 있었다. 하드코딩으로
되돌아가면 이 테스트가 깨진다.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc import cli, comp, decision, items, pool_math, survival, trials  # noqa: E402

REQUIRED_ARGS = {
    "unit": ["--level", "8", "--cost", "4", "--own", "1"],
    "lobby": ["--snapshot", str(ROOT / "data" / "example_snapshot.json"),
              "--champion", "Ahri", "--level", "8"],
    "plan": ["--round", "4-1", "--gold", "10", "--level", "7"],
    "survive": ["--round", "4-1", "--hp", "40"],
    "report": ["--round", "4-1", "--gold", "10", "--level", "7", "--hp", "40"],
    "robustness": ["--level", "8", "--cost", "4", "--own", "1", "--others", "2"],
    "sensitivity": ["--level", "8", "--cost", "4", "--own", "1",
                    "--tier-in-play", "5", "--cost-odds", "0.3"],
}


class TestLibraryDefaults(unittest.TestCase):
    CASES = (
        (pool_math.simulate_roll_down, trials.HEAVY),
        (pool_math.gold_needed_for_probability, trials.STANDARD),
        (decision.unit_cost_report, trials.STANDARD),
        (decision.compare_lines, trials.STANDARD),
        (decision.robustness_scan, trials.REPEATED),
        (comp.unit_outlook, trials.REPEATED),
        (comp.simulate_comp, trials.REPEATED),
        (comp.rank_comps, trials.REPEATED),
        (items.p_ready_after, trials.HEAVY),
        (items.analyze_items, trials.HEAVY),
        (survival.simulate_survival, trials.HEAVY),
    )

    def test_function_defaults_are_the_named_constants(self):
        for func, expected in self.CASES:
            with self.subTest(func=f"{func.__module__}.{func.__name__}"):
                default = inspect.signature(func).parameters["trials"].default
                self.assertEqual(default, expected)

    def test_constants_are_ordered_by_cost(self):
        """시행 수 크기 순서가 이름의 의미(FAST < ... < HEAVY)와 맞는지."""
        self.assertLess(trials.FAST, trials.REPEATED)
        self.assertLess(trials.REPEATED, trials.STANDARD)
        self.assertLess(trials.STANDARD, trials.HEAVY)


class TestCliDefaults(unittest.TestCase):
    """CLI 아규먼트 기본값도 같은 상수를 쓰는지(build_parser 로 직접 검사)."""

    @classmethod
    def setUpClass(cls):
        cls.parser = cli.build_parser()

    def _trials_default(self, command: str) -> int:
        namespace = self.parser.parse_args([command, *REQUIRED_ARGS[command]])
        return namespace.trials

    def test_trials_defaults(self):
        expected = {
            "unit": trials.STANDARD,
            "lobby": trials.STANDARD,
            "robustness": trials.STANDARD,
            "sensitivity": trials.STANDARD,
            "plan": trials.FAST,
            "report": trials.FAST,
            "survive": trials.HEAVY,
        }
        for command, value in expected.items():
            with self.subTest(command=command):
                self.assertEqual(self._trials_default(command), value)

    def test_selftest_takes_no_trials(self):
        """selftest 는 벤치마크 고정값만 쓰므로 --trials 가 없어야 한다."""
        namespace = self.parser.parse_args(["selftest"])
        self.assertFalse(hasattr(namespace, "trials"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
