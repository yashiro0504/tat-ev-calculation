"""숫자/성급 OCR 검증 (``cv/ocr.py``).

검증 전략: 실제 게임 화면을 쓸 수 없으므로 **합성 이미지**로 검증한다.

* 별: 어두운 배경에 흰 사각형 0~3개를 그려 개수를 정확히 세는지.
* 숫자: 3x5 문자 아트로 0~9 를 그려 지문 템플릿을 만들고 조합 숫자(7/42/105)를 읽는지.
* 미인식: 템플릿 없음 / 빈 영역 / 애매한 비율 -> ``None`` 또는 ``확인 필요``(추정 금지).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc.cv import fingerprint, ocr, screen  # noqa: E402

#: 3x5 문자 아트('1'=잉크). 각 행/열에 잉크가 있어 트림 후에도 모든 글리프가 3x5 다.
DIGIT_ART: dict[str, list[str]] = {
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "001", "001", "001"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
}

SCALE = 6
BLANK = (0, 0, 0, 255)
INK = (255, 255, 255, 255)


def _blank(width: int, height: int) -> screen.Image:
    pixels = bytearray(width * height * 4)
    for offset in range(0, len(pixels), 4):
        pixels[offset : offset + 4] = bytes(BLANK)
    return screen.Image(width=width, height=height, pixels=pixels)


def _put(image: screen.Image, x: int, y: int, colour: tuple[int, ...]) -> None:
    offset = (y * image.width + x) * 4
    image.pixels[offset : offset + 4] = bytes(colour)


def glyph(name: str, *, scale: int = SCALE) -> screen.Image:
    """문자 아트를 공백 없이(트림해) 그린다.

    트림해 두면 ``split_digits`` 가 조각을 자르는 경계와 **같아져** 템플릿과 분리
    결과가 정확히 일치한다(테스트가 픽스처 특성에 좌우되지 않게).
    """
    rows = [row for row in DIGIT_ART[name] if "1" in row]
    columns = [index for index in range(3) if any(row[index] == "1" for row in rows)]
    width = (columns[-1] - columns[0] + 1) * scale
    height = len(rows) * scale
    image = _blank(width, height)
    for row_index, row in enumerate(rows):
        for column in range(columns[0], columns[-1] + 1):
            if row[column] != "1":
                continue
            for y in range(row_index * scale, (row_index + 1) * scale):
                for x in range(
                    (column - columns[0]) * scale, (column - columns[0] + 1) * scale
                ):
                    _put(image, x, y, INK)
    return image


def _is_ink(image: screen.Image, x: int, y: int) -> bool:
    return image.pixel(x, y) == (255, 255, 255)


def number(text: str, *, scale: int = SCALE, gap: int = 2) -> screen.Image:
    """여러 글리프를 ``gap`` 칸 띄워 이어 붙인 숫자 이미지."""
    glyphs = [glyph(character, scale=scale) for character in text]
    width = sum(item.width for item in glyphs) + gap * scale * (len(glyphs) - 1)
    height = max(item.height for item in glyphs)
    canvas = _blank(width, height)
    left = 0
    for item in glyphs:
        for y in range(item.height):
            for x in range(item.width):
                if _is_ink(item, x, y):
                    _put(canvas, left + x, y, INK)
        left += item.width + gap * scale
    return canvas


def digit_templates(*, scale: int = SCALE) -> fingerprint.TemplateSet:
    return fingerprint.TemplateSet(
        grid=8,
        source="합성",
        templates=[
            fingerprint.Template(
                name=name, values=fingerprint.fingerprint(glyph(name, scale=scale))
            )
            for name in DIGIT_ART
        ],
    )


def star_image(count: int, *, width: int = 100, height: int = 20, side: int = 8) -> screen.Image:
    """어두운 배경에 흰 사각형(별 대용) ``count`` 개를 그린다."""
    image = _blank(width, height)
    for index in range(count):
        left = 4 + index * 30
        for y in range(4, 4 + side):
            for x in range(left, left + side):
                _put(image, x, y, INK)
    return image


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
        self.assertEqual(ocr.count_stars(_blank(100, 20), self.BOX), 0)

    def test_empty_box_is_zero(self):
        self.assertEqual(ocr.count_stars(_blank(10, 10), (0.0, 0.0, 0.0, 0.0)), 0)


def _paste(canvas: screen.Image, piece: screen.Image, left: int) -> None:
    for y in range(piece.height):
        for x in range(piece.width):
            if _is_ink(piece, x, y):
                _put(canvas, left + x, y, INK)


def _with_separator(left_text: str, right_text: str) -> screen.Image:
    """'4-2' 처럼 두 글리프 사이에 얇은 구분자 선을 넣은 이미지.

    구분자 양옆에 **빈 열**을 둬야 '4' / '-' / '2' 가 각각 조각으로 나뉜다
    (붙어 있으면 열 투영에서 한 조각으로 합쳐진다).
    """
    left, right = glyph(left_text), glyph(right_text)
    gap = 2
    separator = 4 * SCALE
    right_left = left.width + gap + separator + gap
    canvas = _blank(right_left + right.width, max(left.height, right.height))
    _paste(canvas, left, 0)
    for y in range(2, 4):
        for x in range(left.width + gap, left.width + gap + separator):
            _put(canvas, x, y, INK)
    _paste(canvas, right, right_left)
    return canvas


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
        self.assertEqual(ocr.split_digits(_blank(40, 20)), [])

    def test_empty_image_returns_nothing(self):
        self.assertEqual(ocr.split_digits(_blank(0, 0)), [])

    def test_separator_becomes_its_own_piece(self):
        """구분자가 있으면 조각이 3개 -> read_number 가 None 으로 막는다(추정 금지)."""
        joined = _with_separator("4", "2")
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
        self.assertIsNone(ocr.read_number(_blank(40, 20), self.templates))

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
                fingerprint.Template(name=name, values=fingerprint.fingerprint(glyph(name)))
                for name in ("0", "1", "2", "3", "4")
            ],
        )
        self.assertIsNone(ocr.read_number(number("7"), partial))


if __name__ == "__main__":
    unittest.main(verbosity=2)

