"""표 출력/형식 헬퍼.

왜 cli.py 에서 분리했나(L6): 이들은 **순수 문자열 변환**이다 — argparse 도, 파일
입출력도, 시뮬레이션도 모른다. cli.py 안에 두면 1,600 줄짜리 god file 을 키우고,
여기에 모아 두면 표시 정책("정직성 규칙")을 한곳에서 볼 수 있다.

정직성 규칙
-----------
1. **100% / 0% 라벨은 실제 경계값에만 쓴다.** 반올림이 경계에 붙으면 자릿수를 늘려
   "거의 확실"을 "확실"로, "거의 없음"을 "불가"로 부르지 않는다(낙관 편향 방지).
2. **모르는 값은 확률로 위장하지 않는다.** 부품 입력이 없으면 확률 대신 개수를 준다.
3. **정렬은 표시 폭 기준.** f-string 의 ``{:<22}`` 는 글자 수만 세는데 한글은 2칸이라,
   한글이 섞이는 순간 열이 어긋난다.
"""

from __future__ import annotations

import unicodedata

from . import items


def pct(value: float) -> str:
    """간단한 확률 표시(정렬 없음)."""
    return f"{value * 100:.1f}%"


def pct_fmt(value: float, width: int = 7) -> str:
    """확률 표시(오른쪽 정렬). ``value`` 는 0~1.

    자릿수는 값 크기와 **반올림 결과**에 따라 늘린다.

    * ``>= 0.05`` : 소수 첫째 자리(50.0%)
    * ``< 0.05``  : 소수 둘째 자리(4.90%) — 0.0% 로 뭉개져 '불가' 로 읽히지 않게
    * 반올림이 100% 또는 0.00% 에 붙으면 다음 자리까지(최대 4자리)

    Regression: 예전엔 ``value >= 0.995`` 면 무조건 "100%" 라 해서 **99.51% 가
    100% 로 표시**됐다. '거의 확실'이 '확실'로 보이면 결론이 몰아간다.
    """
    if value <= 0.0:
        return "0%".rjust(width)
    if value >= 1.0:
        return "100%".rjust(width)
    places = 1 if value >= 0.05 else 2
    while places < 4:
        text = f"{value * 100:.{places}f}%"
        shown = float(text[:-1])
        if 0.0 < shown < 100.0:
            return text.rjust(width)
        places += 1
    return f"{value * 100:.4f}%".rjust(width)


def gold_fmt(value: object, width: int = 12) -> str:
    """기대 골드 표시(오른쪽 정렬). ``None`` 은 '-', 무한대는 '불가'.

    Regression: 예전엔 ``value in (None,)`` (``is None`` 과 같지만 이상한 표기)였고
    ``float('inf')`` 를 그대로 ``"infg"`` 로 찍었다(풀이 완전히 비어 있을 때 가능).
    """
    if value is None:
        return "-".rjust(width)
    number = float(value)
    if number in (float("inf"), float("-inf")):
        # '불가' 는 한글이라 rjust(글자 수) 를 쓰면 표시 폭이 어긋난다.
        return pad("불가", width, ">")
    return f"{number:.1f}g".rjust(width)


def gold(value: float) -> str:
    """기대 골드(정렬 없음)."""
    return "불가(∞)" if value == float("inf") else f"{value:.1f}골드"


def item_cells(
    readiness: "items.ItemReadiness | None",
    *,
    p_complete: float,
    has_input: bool,
    width: int = 8,
) -> tuple[str, str]:
    """아이템/결합 두 열의 텍스트(명령들 간 표시 일관용).

    부품 입력이 없으면 ``p_ready`` 는 0 이 되지만, 그건 "아이템을 못 맞춘다" 가 아니라
    "앞으로 받을 부품을 하나도 입력하지 않았다" 뜻이다. 0% 로 표시하면 결합
    (유닛 x 아이템)까지 0% 로 덮어씌워 유닛 확률을 지워버린다. 모르는 값은 확률로
    표시하지 않고 필요한 부품 개수만 보여준다.
    """
    if readiness is None:
        return "-".rjust(width), "-".rjust(width)
    if not has_input:
        # 'n부품' 은 한글이 섞여 rjust(글자 수) 로는 표시 폭이 어긋난다.
        return pad(f"{sum(readiness.required.values())}부품", width, ">"), "-".rjust(width)
    return (
        pct_fmt(readiness.p_ready, width),
        pct_fmt(p_complete * readiness.p_ready, width),
    )


# --------------------------------------------------------------------------
# 한글 폭 — 표시 폭 기준 정렬
# --------------------------------------------------------------------------
def _wide(ch: str) -> int:
    """한 글자의 표시 폭(한글/전각 문자는 2칸)."""
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def disp_len(text: str) -> int:
    """표시 폭.

    f-string 의 ``{:<22}`` 은 글자 수만 세므로 ``'컴프':<22`` 는 표시상 44칸이 되어
    숫자 열과 정렬이 어긋난다. 한글 헤더/데이터가 섞이는 표는 이 함수로 세야 한다.
    """
    return sum(_wide(ch) for ch in text)


def pad(text: str, width: int, align: str = "<") -> str:
    """표시 폭 기준 패딩. ``align`` 은 '<'(왼쪽, 기본), '>'(오른쪽), '^'(가운데)."""
    fill = max(0, width - disp_len(text))
    if align == ">":
        return " " * fill + text
    if align == "^":
        left = fill // 2
        return " " * left + text + " " * (fill - left)
    return text + " " * fill


def trunc(text: str, width: int) -> str:
    """표시 폭 기준 자르기(자를 때 끝에 '..' 를 붙여 잘렸다는 걸 알린다)."""
    if disp_len(text) <= width:
        return text
    budget = max(0, width - 2)
    out: list[str] = []
    used = 0
    for ch in text:
        step = _wide(ch)
        if used + step > budget:
            break
        out.append(ch)
        used += step
    return "".join(out) + ".."
