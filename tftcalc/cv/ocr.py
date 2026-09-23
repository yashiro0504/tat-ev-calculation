"""숫자/성급 OCR (표준 라이브러리만).

이 모듈이 하는 일
----------------
* ``star_ratio`` / ``stars_from_ratio`` / ``count_stars`` — 칸 하단의 별(성급) 개수를
  **밝은 픽셀 면적 비율**로 센다(분류가 아니라 개수 카운트).
* ``split_digits`` — 숫자 띠를 **열 방향 투영**으로 자릿수별 조각으로 나눈다.
* ``read_number`` — 자릿수 조각을 지문 템플릿으로 분류해 정수로 결합한다.

정직성 규칙 (프로젝트 공통)
--------------------------
* **못 읽으면 ``None``** 이다. 0 이나 추정값을 넣지 않는다 — 골드 한 자리가 틀리면
  계획이 통째로 틀어지므로 '모른다'가 '틀린 값'보다 낫다.
* 애매하면(``fingerprint.classify`` 의 review 문턱, 또는 별이 정수 경계 사이) 확정하지 않는다.
* 숫자 템플릿이 없으면 전부 ``None`` 이고, 호출부가 '손 입력 필요'를 고지한다.

캘리브레이션 필요(정직하게)
--------------------------
별 임계값과 숫자 템플릿은 **실제 게임 화면에서 1회 맞춰야** 한다. 아래 값은 합성
이미지로 정한 출발점이며, ``scripts/check_capture.py`` 로 BMP 를 저장해 확인한다.
"""

from __future__ import annotations

from .fingerprint import TemplateSet, classify
from .screen import Image

#: 별 1개가 칸(별 영역)에서 차지하는 대략적 면적 비율. 실게임 UI 에서 재확인 필요.
STAR_AREA_RATIO = 0.030

#: 이 비율 미만이면 "별 없음"으로 본다(테두리·발광 노이즈 바닥).
STAR_NOISE_RATIO = 0.008

#: 이 정도로 정수 경계에 가까우면(0.5 = 완전 중간) 확정하지 않고 '확인 필요'로 본다.
STAR_AMBIGUOUS_BAND = 0.20

#: 별 픽셀 판정 밝기(그레이스케일 0~255, 이 이상만 '별'로 센다).
STAR_BRIGHTNESS = 185

#: 숫자 잉크 판정 밝기(숫자는 배경보다 밝다).
DIGIT_BRIGHTNESS = 128


def crop_box(image: Image, box: tuple[float, float, float, float]) -> Image:
    """(x, y, w, h) 픽셀 박스로 자른다."""
    x, y, width, height = (int(value) for value in box)
    return image.crop(x, y, max(1, width), max(1, height))


def star_ratio(
    image: Image, box: tuple[float, float, float, float], *, brightness: int = STAR_BRIGHTNESS
) -> float:
    """별 영역에서 밝은 픽셀이 차지하는 비율(판정 근거·캘리브레이션용)."""
    region = crop_box(image, box)
    total = region.width * region.height
    if total <= 0:
        return 0.0
    bright = sum(
        1
        for y in range(region.height)
        for x in range(region.width)
        if region.gray(x, y) >= brightness
    )
    return bright / total


def stars_from_ratio(
    ratio: float,
    *,
    area_ratio: float = STAR_AREA_RATIO,
    noise_ratio: float = STAR_NOISE_RATIO,
    max_stars: int = 3,
) -> int:
    """면적 비율 -> 별 개수(0~``max_stars``). 별 1개 면적을 단위로 나눠 가장 가까운 정수."""
    if ratio < noise_ratio:
        return 0
    stars = int((ratio - noise_ratio) / area_ratio + 0.5)
    return max(0, min(max_stars, stars))


def star_is_ambiguous(
    ratio: float,
    *,
    area_ratio: float = STAR_AREA_RATIO,
    noise_ratio: float = STAR_NOISE_RATIO,
    band: float = STAR_AMBIGUOUS_BAND,
    max_stars: int = 3,
) -> bool:
    """개수 판정이 두 정수 **경계**에 가까운가(±``band``).

    가까우면 호출부가 그 칸을 '확인 필요'로 빼야 한다 — 성급은 풀 소모량을 1/3/9 로
    바꾸므로 잘못 넣으면 계산이 조용히 3배 틀어진다.

    또한 밝은 면적이 ``max_stars`` 범위를 크게 넘으면(예: 아이콘 자체가 별 영역에
    걸친 경우) 애매가 아니라 **별로 볼 수 없는 값**이다. 이때 ``False`` 를 돌려주고
    3성으로 clamp 하면 조용한 3배 오차가 나므로, 여기서도 애매로 처리한다.

    실측: 실제 Data Dragon 아이콘을 칸에 채운 합성 화면에서 이 비율이 별 1개 면적의
    약 12배(``scaled ≈ 11.7``)로 나왔다 — 캘리브레이션 없이 켜면 이 경로로 걸린다.
    """
    scaled = (ratio - noise_ratio) / area_ratio
    if scaled > max_stars + 0.5:
        return True
    return abs(scaled - int(scaled + 0.5)) > (0.5 - band)


def count_stars(
    image: Image, box: tuple[float, float, float, float], **kwargs: float
) -> int:
    """칸의 별(성급) 개수를 센다(0~3). 판정 근거는 ``star_ratio``/``stars_from_ratio``."""
    return stars_from_ratio(star_ratio(image, box), **kwargs)


def _column_has_ink(image: Image, brightness: int) -> list[bool]:
    """열마다 잉크(밝은 픽셀)가 하나라도 있는지."""
    ink: list[bool] = []
    for x in range(image.width):
        ink.append(
            any(image.gray(x, y) >= brightness for y in range(image.height))
        )
    return ink


def _ink_span(
    image: Image, left: int, right: int, brightness: int
) -> tuple[int, int] | None:
    """열 구간 ``[left, right)`` 안 잉크의 행 범위 ``(top, bottom_exclusive)``. 없으면 None."""
    top: int | None = None
    bottom = 0
    for x in range(left, right):
        for y in range(image.height):
            if image.gray(x, y) >= brightness:
                if top is None:
                    top = y
                bottom = y
    if top is None:
        return None
    return top, bottom + 1


def split_digits(image: Image, *, brightness: int = DIGIT_BRIGHTNESS) -> list[Image]:
    """숫자 띠를 자릿수별 조각으로 나눈다(열 방향 투영 + 잉크 경계 트림).

    두 단계로 자른다.

    1. **열 방향 투영** — 잉크 없는 열이 이어지는 구간을 경계로 나눈다.
    2. 각 조각을 **잉크의 상하 경계로 트림**한다. 이게 중요하다: 트림하지 않으면 조각의
       높이가 '영역 높이'에 따라 달라져(예: 화면 영역은 49px, 글자는 30px) 가로세로 비가
       템플릿과 어긋나고, ``fingerprint`` 가 다른 지문을 만들어 **엉뚱한 숫자로 분류**된다.
       트림하면 글자 크기(스케일)만 달라지고 지문은 정규화로 흡수된다.

    주의: 자릿수가 붙어 있거나(사이 빈 열이 없음) 구분자('4-2' 의 '-')가 있으면
    조각이 의도와 다르게 나온다. 그 경우 ``read_number`` 가 ``None`` 을 돌려준다
    (추정해서 값을 만들어내지 않는다).
    """
    if image.width <= 0 or image.height <= 0:
        return []
    ink = _column_has_ink(image, brightness)
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for x, has_ink in enumerate(ink):
        if has_ink and start is None:
            start = x
        elif not has_ink and start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, image.width))

    pieces: list[Image] = []
    for left, right in runs:
        span = _ink_span(image, left, right, brightness)
        if span is None:
            continue
        top, bottom = span
        pieces.append(image.crop(left, top, right - left, bottom - top))
    return pieces


def _read_digit(piece: Image, templates: TemplateSet) -> str | None:
    """조각 하나를 숫자 **문자**로 읽는다. 애매하거나 숫자가 아니면 ``None``."""
    match = classify(piece, templates)
    if match.needs_review or len(match.name) != 1 or not match.name.isdigit():
        return None
    return match.name


def read_number(
    image: Image, templates: TemplateSet, *, brightness: int = DIGIT_BRIGHTNESS
) -> int | None:
    """숫자를 읽어 정수로 돌려준다. 하나라도 애매하면 ``None``.

    ``templates`` 의 각 지문 이름은 **'0'~'9'** 여야 한다(다른 이름은 실패로 본다).
    조각이 없거나(빈 영역) 어떤 조각이든 확인 필요면 ``None`` — 부분 인식으로
    그럴듯한 수를 만들지 않는다.
    """
    if not templates.templates:
        return None
    pieces = split_digits(image, brightness=brightness)
    if not pieces:
        return None
    digits: list[str] = []
    for piece in pieces:
        digit = _read_digit(piece, templates)
        if digit is None:
            return None
        digits.append(digit)
    return int("".join(digits))


#: 라운드 표기('4-2')의 유효 범위. 벗어나면 **오독으로 보고** 확정하지 않는다.
#: 라운드가 한 글자만 틀려도 골드 계획 전체가 어긋나므로 '그럴듯한 값'을 만들지 않는다.
MAX_STAGE = 9
MAX_ROUND_IN_STAGE = 7


def read_round(
    image: Image, templates: TemplateSet, *, brightness: int = DIGIT_BRIGHTNESS
) -> tuple[int, int] | None:
    """'4-2' 같은 라운드 표기를 ``(스테이지, 라운드)`` 로 읽는다. 애매하면 ``None``.

    방법: ``split_digits`` 로 나눈 조각이 **정확히 3개이고 가운데가 숫자가 아닐 때만**
    (숫자 · 구분자 · 숫자) 로 본다. 가운데가 숫자로 읽히면 다른 표기이므로 확정하지 않는다.
    범위(스테이지 1~``MAX_STAGE``, 라운드 1~``MAX_ROUND_IN_STAGE``) 밖이면 오독으로 본다.
    """
    if not templates.templates:
        return None
    pieces = split_digits(image, brightness=brightness)
    if len(pieces) != 3:
        return None
    if _read_digit(pieces[1], templates) is not None:
        return None  # 가운데가 숫자면 '4-2' 형태가 아니다
    stage = _read_digit(pieces[0], templates)
    round_ = _read_digit(pieces[2], templates)
    if stage is None or round_ is None:
        return None
    stage_value, round_value = int(stage), int(round_)
    if not 1 <= stage_value <= MAX_STAGE or not 1 <= round_value <= MAX_ROUND_IN_STAGE:
        return None
    return stage_value, round_value
