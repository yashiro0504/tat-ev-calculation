"""합성 이미지 테스트 픽스처 (테스트 모듈 아님).

``test_ocr.py`` 와 ``test_scan.py`` 가 함께 쓴다 — 실제 게임 화면을 쓸 수 없으므로
문자 아트/사각형으로 **결정론적 이미지**를 만들어 OCR 경로를 검증한다.

``unittest discover`` 의 수집 패턴(``test*.py``)에 걸리지 않도록 이름을 ``fixtures.py`` 로 둔다.
"""

from __future__ import annotations

from tftcalc.cv import fingerprint, screen

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


def blank(width: int, height: int) -> screen.Image:
    pixels = bytearray(width * height * 4)
    for offset in range(0, len(pixels), 4):
        pixels[offset : offset + 4] = bytes(BLANK)
    return screen.Image(width=width, height=height, pixels=pixels)


def put(image: screen.Image, x: int, y: int, colour: tuple[int, ...]) -> None:
    offset = (y * image.width + x) * 4
    image.pixels[offset : offset + 4] = bytes(colour)


def is_ink(image: screen.Image, x: int, y: int) -> bool:
    return image.pixel(x, y) == (255, 255, 255)


def glyph(name: str, *, scale: int = SCALE) -> screen.Image:
    """문자 아트를 공백 없이(트림해) 그린다.

    트림해 두면 ``split_digits`` 가 조각을 자르는 경계와 **같아져** 템플릿과 분리
    결과가 정확히 일치한다(테스트가 픽스처 특성에 좌우되지 않게).
    """
    rows = [row for row in DIGIT_ART[name] if "1" in row]
    columns = [index for index in range(3) if any(row[index] == "1" for row in rows)]
    width = (columns[-1] - columns[0] + 1) * scale
    height = len(rows) * scale
    image = blank(width, height)
    for row_index, row in enumerate(rows):
        for column in range(columns[0], columns[-1] + 1):
            if row[column] != "1":
                continue
            for y in range(row_index * scale, (row_index + 1) * scale):
                for x in range(
                    (column - columns[0]) * scale, (column - columns[0] + 1) * scale
                ):
                    put(image, x, y, INK)
    return image


def paste(canvas: screen.Image, piece: screen.Image, left: int, top: int = 0) -> None:
    """``piece`` 의 잉크 픽셀을 ``(left, top)`` 기준으로 ``canvas`` 에 찍는다."""
    for y in range(piece.height):
        for x in range(piece.width):
            if is_ink(piece, x, y):
                put(canvas, left + x, top + y, INK)


def number(text: str, *, scale: int = SCALE, gap: int = 2) -> screen.Image:
    """여러 글리프를 ``gap`` 칸 띄워 이어 붙인 숫자 이미지."""
    glyphs = [glyph(character, scale=scale) for character in text]
    width = sum(item.width for item in glyphs) + gap * scale * (len(glyphs) - 1)
    height = max(item.height for item in glyphs)
    canvas = blank(width, height)
    left = 0
    for item in glyphs:
        paste(canvas, item, left)
        left += item.width + gap * scale
    return canvas


def with_separator(left_text: str, right_text: str, *, gap: int = 2) -> screen.Image:
    """'4-2' 처럼 두 글리프 사이에 얇은 구분자 선을 넣은 이미지.

    구분자 양옆에 **빈 열**을 둬야 '4' / '-' / '2' 가 각각 조각으로 나뉜다
    (붙어 있으면 열 투영에서 한 조각으로 합쳐진다).
    """
    left, right = glyph(left_text), glyph(right_text)
    separator = 4 * SCALE
    right_left = left.width + gap + separator + gap
    canvas = blank(right_left + right.width, max(left.height, right.height))
    paste(canvas, left, 0)
    for y in range(2, 4):
        for x in range(left.width + gap, left.width + gap + separator):
            put(canvas, x, y, INK)
    paste(canvas, right, right_left)
    return canvas


def digit_templates(*, scale: int = SCALE) -> fingerprint.TemplateSet:
    """0~9 지문 템플릿(이름이 '0'~'9' — ``read_number`` 가 요구하는 형식)."""
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


def star_image(
    count: int, *, width: int = 100, height: int = 20, side: int = 8
) -> screen.Image:
    """어두운 배경에 흰 사각형(별 대용) ``count`` 개를 그린다."""
    image = blank(width, height)
    for index in range(count):
        left = 4 + index * 30
        for y in range(4, 4 + side):
            for x in range(left, left + side):
                put(image, x, y, INK)
    return image
