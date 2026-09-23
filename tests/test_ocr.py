"""숫자/성급 OCR 검증 (``cv/ocr.py``).

실제 게임 화면을 쓸 수 없으므로 **합성 이미지**로 검증한다(픽스처는 ``tests/fixtures.py``).

* 별: 흰 사각형 0~3개 -> 개수 정확히. 경계/과대 비율은 '확인 필요'로 거부.
* 숫자: 0~9 지문 템플릿으로 7/42/105 를 읽고, 애매하거나 빈 영역이면 ``None``.
* 라운드: '4-2' 형태만 읽고, '42'/'422'/'9-8' 은 거부(라운드가 틀리면 계획이 통째로 틀어진다).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc.cv import fingerprint, ocr  # noqa: E402
from tests.fixtures import (  # noqa: E402
    blank,
    digit_templates,
    glyph,
    number,
    star_image,
    with_separator,
)


class TestCountStars(unittest.TestCase):
    BOX = (0.0, 0.0, 100.0, 20.0)

    def test_counts_zero_to_three(self):
        for count in range(4):
            with self.subTest(count=count):
                image = star_image(count)
                ratio = ocr.star_ratio(image, self.BOX)
                self.assertEqual(ocr.stars_from_ratio(ratio), count)
                self.assertEqual(ocr.count_stars(image, self.BOX), count)
                self.assertFalse(ocr.star_is_ambiguous(ratio))

    def test_blank_is_zero_not_ambiguous(self):
        ratio = ocr.star_ratio(star_image(0), self.BOX)
        self.assertEqual(ratio, 0.0)
        self.assertEqual(ocr.count_stars(star_image(0), self.BOX), 0)
        self.assertFalse(ocr.star_is_ambiguous(ratio))

    def test_midpoint_ratio_is_ambiguous(self):
        """1개와 2개 사이(가장 가까운 정수에서 0.5 떨어진) 비율은 확정하지 않는다."""
        midpoint = ocr.STAR_NOISE_RATIO + ocr.STAR_AREA_RATIO * 1.5
        self.assertTrue(ocr.star_is_ambiguous(midpoint))
        self.assertFalse(
            ocr.star_is_ambiguous(ocr.STAR_NOISE_RATIO + ocr.STAR_AREA_RATIO * 2.0)
        )

    def test_caps_at_three(self):
        self.assertEqual(ocr.stars_from_ratio(0.5), 3)

    def test_out_of_range_ratio_is_ambiguous(self):
        """별 1개 면적을 크게 넘는 밝기는 '별 개수'로 확정하지 않는다.

        Regression: 실제 아이콘이 별 영역을 덮으면 비율이 별 1개의 약 12배가 되는데,
        그걸 clamp 해서 3성으로 쓰면 풀 소모가 9장으로 잡혀 3배 오차가 난다.
        """
        self.assertTrue(
            ocr.star_is_ambiguous(ocr.STAR_NOISE_RATIO + ocr.STAR_AREA_RATIO * 11.7)
        )
        self.assertTrue(
            ocr.star_is_ambiguous(ocr.STAR_NOISE_RATIO + ocr.STAR_AREA_RATIO * 4.0)
        )

    def test_dark_region_is_zero(self):
        """밝은 픽셀이 없으면 0 개다 — 어두운 화면을 별로 세지 않는다."""
        self.assertEqual(ocr.count_stars(blank(100, 20), self.BOX), 0)

    def test_empty_box_is_zero(self):
        self.assertEqual(ocr.count_stars(blank(10, 10), (0.0, 0.0, 0.0, 0.0)), 0)


class TestSplitDigits(unittest.TestCase):
    def test_splits_separated_glyphs(self):
        pieces = ocr.split_digits(number("42"))
        self.assertEqual(len(pieces), 2)
        self.assertEqual(
            [fingerprint.fingerprint(piece) for piece in pieces],
            [fingerprint.fingerprint(glyph("4")), fingerprint.fingerprint(glyph("2"))],
        )

    def test_single_glyph_is_one_piece(self):
        self.assertEqual(len(ocr.split_digits(number("7"))), 1)

    def test_blank_returns_nothing(self):
        self.assertEqual(ocr.split_digits(blank(40, 20)), [])

    def test_empty_image_returns_nothing(self):
        self.assertEqual(ocr.split_digits(blank(0, 0)), [])

    def test_separator_becomes_its_own_piece(self):
        """구분자가 있으면 조각이 3개 -> read_number 가 None 으로 막는다(추정 금지)."""
        joined = with_separator("4", "2")
        self.assertEqual(len(ocr.split_digits(joined)), 3)
        self.assertIsNone(ocr.read_number(joined, digit_templates()))


class TestReadNumber(unittest.TestCase):
    def setUp(self):
        self.templates = digit_templates()

    def test_reads_single_and_multi_digit(self):
        for text in ("0", "7", "9", "42", "105", "100"):
            with self.subTest(text=text):
                self.assertEqual(ocr.read_number(number(text), self.templates), int(text))

    def test_without_templates_is_none(self):
        empty = fingerprint.TemplateSet(grid=8, templates=[], source="빈")
        self.assertIsNone(ocr.read_number(number("7"), empty))

    def test_blank_is_none_not_zero(self):
        """빈 영역을 0 으로 추정하지 않는다 — 그게 골드 계획을 망치는 방식이다."""
        self.assertIsNone(ocr.read_number(blank(40, 20), self.templates))

    def test_non_digit_template_name_is_none(self):
        """지문 이름이 '0'~'9' 가 아니면 확정하지 않는다(잘못된 템플릿 방어)."""
        bad = fingerprint.TemplateSet(
            grid=8,
            source="합성",
            templates=[
                fingerprint.Template(
                    name="seven", values=fingerprint.fingerprint(glyph("7"))
                )
            ],
        )
        self.assertIsNone(ocr.read_number(number("7"), bad))

    def test_glyph_outside_templates_is_none(self):
        """템플릿에 없는 숫자는 '확인 필요' -> None(그럴듯한 수를 만들지 않는다)."""
        partial = fingerprint.TemplateSet(
            grid=8,
            source="합성",
            templates=[
                fingerprint.Template(
                    name=name, values=fingerprint.fingerprint(glyph(name))
                )
                for name in ("0", "1", "2", "3", "4")
            ],
        )
        self.assertIsNone(ocr.read_number(number("7"), partial))


class TestReadRound(unittest.TestCase):
    """라운드 표기('4-2') 파싱 — 형태와 범위를 **모두** 만족할 때만 확정한다."""

    def setUp(self):
        self.templates = digit_templates()

    def test_reads_stage_and_round(self):
        for stage, round_ in (("4", "2"), ("7", "7"), ("2", "1"), ("9", "7")):
            with self.subTest(pair=f"{stage}-{round_}"):
                self.assertEqual(
                    ocr.read_round(with_separator(stage, round_), self.templates),
                    (int(stage), int(round_)),
                )

    def test_plain_number_is_rejected(self):
        """'42' 는 라운드 표기가 아니다(조각 2개)."""
        self.assertIsNone(ocr.read_round(number("42"), self.templates))

    def test_digit_in_the_middle_is_rejected(self):
        """가운데가 숫자로 읽히면 '4-2' 형태가 아니다 -> 확정하지 않는다."""
        self.assertIsNone(ocr.read_round(number("422"), self.templates))

    def test_out_of_range_is_rejected(self):
        """범위 밖(라운드 8, 스테이지 0)은 오독으로 본다 — 라운드가 틀리면 계획이 틀어진다."""
        self.assertIsNone(ocr.read_round(with_separator("9", "8"), self.templates))
        self.assertIsNone(ocr.read_round(with_separator("0", "2"), self.templates))

    def test_blank_and_single_glyph_are_none(self):
        self.assertIsNone(ocr.read_round(blank(40, 20), self.templates))
        self.assertIsNone(ocr.read_round(number("4"), self.templates))

    def test_without_templates_is_none(self):
        empty = fingerprint.TemplateSet(grid=8, templates=[], source="빈")
        self.assertIsNone(ocr.read_round(with_separator("4", "2"), empty))

    def test_range_constants_are_exposed(self):
        """범위가 상수로 노출돼 있다(캘리브레이션·문서에서 참조)."""
        self.assertGreaterEqual(ocr.MAX_STAGE, 9)
        self.assertEqual(ocr.MAX_ROUND_IN_STAGE, 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
