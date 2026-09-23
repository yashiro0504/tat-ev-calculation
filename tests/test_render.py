"""표 출력/형식 헬퍼 검증 (L1 · L4 · L6 · L9).

핵심은 "정직성 규칙"이 코드로 지켜지는지다:

* 100% / 0% 라벨은 **실제 경계값**에만 쓴다(반올림으로 몰아붙이지 않는다).
* 모르는 값은 확률로 위장하지 않는다(개수나 '-' 로 보여준다).
* 정렬은 **표시 폭**(한글 2칸) 기준이다.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc import items, render  # noqa: E402


class TestPctFormat(unittest.TestCase):
    def test_exact_boundaries_keep_their_labels(self):
        self.assertEqual(render.pct_fmt(0.0, 6).strip(), "0%")
        self.assertEqual(render.pct_fmt(1.0, 6).strip(), "100%")

    def test_near_certain_is_not_relabelled_as_100(self):
        """Regression: 예전엔 >=0.995 를 무조건 '100%' 라 해서 99.51% 가 100% 로 보였다."""
        self.assertEqual(render.pct_fmt(0.9951, 8).strip(), "99.5%")
        self.assertEqual(render.pct_fmt(0.9999, 8).strip(), "99.99%")

    def test_near_zero_is_not_collapsed_to_0_00(self):
        self.assertEqual(render.pct_fmt(0.0049, 8).strip(), "0.49%")
        self.assertNotEqual(render.pct_fmt(0.0001, 8).strip(), "0.00%")

    def test_common_values_use_one_decimal(self):
        self.assertEqual(render.pct_fmt(0.5, 8).strip(), "50.0%")
        self.assertEqual(render.pct_fmt(0.0743, 8).strip(), "7.4%")

    def test_aligned_to_requested_width(self):
        for value in (0.0, 0.03, 0.5, 0.9951, 1.0):
            self.assertEqual(len(render.pct_fmt(value, 10)), 10)


class TestGoldFormat(unittest.TestCase):
    def test_none_is_dash(self):
        self.assertEqual(render.gold_fmt(None, 6).strip(), "-")

    def test_infinity_is_not_printed_as_infg(self):
        """Regression: float('inf') 가 'infg' 로 찍혔다."""
        self.assertEqual(render.gold_fmt(float("inf"), 6).strip(), "불가")
        self.assertEqual(render.gold(float("inf")), "불가(∞)")

    def test_value_and_display_width(self):
        self.assertEqual(render.gold_fmt(60.0, 8).strip(), "60.0g")
        self.assertEqual(render.disp_len(render.gold_fmt(float("inf"), 8)), 8)


class TestItemCells(unittest.TestCase):
    def test_without_input_shows_component_count_not_zero(self):
        book = items.RecipeBook.load()
        readiness = items.analyze_items(book, {"Jeweled Gauntlet": 1}, have={})
        item_text, joint_text = render.item_cells(
            readiness, p_complete=0.5, has_input=False
        )
        self.assertIn("부품", item_text)
        self.assertNotIn("%", item_text)  # 확률로 위장하지 않는다
        self.assertEqual(joint_text.strip(), "-")
        self.assertEqual(render.disp_len(item_text), 8)

    def test_with_input_shows_probability(self):
        book = items.RecipeBook.load()
        have = {"Needlessly Large Rod": 1, "Sparring Gloves": 1}
        readiness = items.analyze_items(book, {"Jeweled Gauntlet": 1}, have=have)
        item_text, joint_text = render.item_cells(
            readiness, p_complete=0.5, has_input=True
        )
        self.assertEqual(item_text.strip(), "100%")
        self.assertEqual(joint_text.strip(), "50.0%")

    def test_missing_readiness_is_dash(self):
        self.assertEqual(
            render.item_cells(None, p_complete=0.5, has_input=True),
            ("-".rjust(8), "-".rjust(8)),
        )


class TestDisplayWidth(unittest.TestCase):
    def test_korean_counts_two_columns(self):
        self.assertEqual(render.disp_len("컴프"), 4)
        self.assertEqual(render.disp_len("Ahri"), 4)
        self.assertEqual(render.disp_len("아리Ahri"), 8)  # 한글 2칸 x2 + ASCII x4

    def test_pad_uses_display_width(self):
        """Regression: f-string `{'컴프':<22}` 는 22 '글자' 라 표시상 42칸이었다."""
        for text in ("컴프", "아리 모르가나", "Ahri", "엄호대 카시오페아"):
            with self.subTest(text=text):
                self.assertEqual(render.disp_len(render.pad(text, 22)), 22)
                self.assertEqual(render.disp_len(render.pad(text, 22, ">")), 22)

    def test_pad_center(self):
        self.assertEqual(render.disp_len(render.pad("아리", 10, "^")), 10)
        self.assertEqual(render.disp_len(render.pad("아리", 2, "^")), 4)  # 넘치면 원문

    def test_trunc_by_display_width_and_marks_cut(self):
        long_korean = "엄호대 카시오페아 (3코 리롤)"
        cut = render.trunc(long_korean, 22)
        self.assertLessEqual(render.disp_len(cut), 22)
        self.assertTrue(cut.endswith(".."))
        self.assertEqual(render.trunc("아리 모르가나", 22), "아리 모르가나")

    def test_trunc_never_exceeds_width(self):
        long_korean = "엄호대 카시오페아 (3코 리롤)"
        for width in (4, 6, 10, 22):
            with self.subTest(width=width):
                self.assertLessEqual(render.disp_len(render.trunc(long_korean, width)), width)


class TestOddsGrid(unittest.TestCase):
    """상점 확률표 채움 격자(값 / 미채움 ? / 격자 밖 .)."""

    LEVELS = [7, 8]
    COSTS = [1, 4, 5]

    def _grid(self, **overrides):
        kwargs = dict(
            levels=self.LEVELS,
            costs=self.COSTS,
            values={(8, 4): 0.30},
            declared={(7, 1), (7, 4), (8, 4), (8, 5)},
        )
        kwargs.update(overrides)
        return render.odds_grid(**kwargs)

    def _row(self, lines, level: int) -> str:
        return next(line for line in lines if line.lstrip().startswith(f"{level} |"))

    def test_header_lists_costs(self):
        lines = self._grid()
        for cost in self.COSTS:
            self.assertIn(f"{cost}코", lines[0])

    def test_marks_value_pending_and_out_of_grid(self):
        lines = self._grid()
        level8 = self._row(lines, 8)
        self.assertIn("30.0%", level8)  # 값이 있는 셀
        self.assertIn("?", level8)      # (8,5) 선언됐지만 미채움
        self.assertIn(".", level8)      # (8,1) 격자 밖
        level7 = self._row(lines, 7)
        self.assertIn("?", level7)      # (7,1),(7,4) 미채움
        self.assertIn(".", level7)      # (7,5) 선언 안 됨
        self.assertNotIn("30.0%", level7)

    def test_rows_and_separator_have_equal_display_width(self):
        lines = self._grid()
        width = render.disp_len(lines[0])
        self.assertEqual(len(lines[1]), width)  # 구분선
        for line in lines[2:]:
            self.assertEqual(render.disp_len(line), width)

    def test_empty_grid_returns_nothing(self):
        self.assertEqual(self._grid(levels=[]), [])
        self.assertEqual(self._grid(costs=[]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
