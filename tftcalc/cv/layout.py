"""TFT UI 좌표 (1920x1080 기준, 비율로 정의).

설계
----
* 좌표는 **비율(0~1)** 로 정의한다. 해상도가 다르면 비율에 곱해 환산하므로
  1280x720/2560x1440 등에서도 같은 코드가 돈다.
* 값은 사용자가 `data/layout_1920x1080.json` 으로 덮어쓸 수 있다(코드 수정 불필요).
* **중요**: 아래 기본 좌표는 공개된 TFT UI 배치를 바탕으로 넣은 값이며,
  실제 화면에서 `scripts/check_capture.py --out shot.bmp` 로 **확인이 필요**하다.
  (README 3.5 의 '좌표 확인' 절차 / 미검증 항목에도 명시)

UI 구조(1920x1080, 보더리스 기준)
--------------------------------
    상단   : 플레이어 HP 바, 라운드/스테이지
    중앙   : 보드(헥스), 좌측에 플레이어 목록
    하단 위: 벤치 9칸
    하단   : 상점 5칸

여기서는 도구가 실제로 쓰는 **벤치/상점**을 정확히 정의하고, 보드는 대략값으로 둔다.

역할 분담: 좌표 정의와 인식(read_slots)이 여기서 맡고, **스냅샷 dict를 만드는 일은
``cv/scan.py``** 가 맡는다(코스트 조회·성급 지정·상대 보존까지). 예전에 여기 있던
``build_snapshot`` 은 ``cost=None`` 을 만들어 ``LobbySnapshot.from_dict`` 가
``TypeError`` 로 실패했는데, 실제 경로에서 쓰이지 않던 죽은 코드여서 삭제했다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .fingerprint import TemplateSet, classify
from .screen import Image

BASE_WIDTH = 1920
BASE_HEIGHT = 1080

#: (이름, (x, y, w, h) 비율) — 벤치 9칸 (하단 위쪽 줄)
#: ※ 기본값은 공개된 UI 배치를 바탕으로 넣은 값이며 실제 화면에서 확인이 필요하다.
BENCH_SLOTS: list[tuple[str, tuple[float, float, float, float]]] = [
    (f"bench_{index + 1}", (0.2455 + index * 0.0632, 0.800, 0.055, 0.085))
    for index in range(9)
]

#: 상점 5칸(하단 큰 카드) — 벤치와 겹치지 않도록 아래쪽에 둔다.
SHOP_SLOTS: list[tuple[str, tuple[float, float, float, float]]] = [
    (f"shop_{index + 1}", (0.1405 + index * 0.1464, 0.900, 0.132, 0.088))
    for index in range(5)
]

#: 보드 헥스(4열 x 7행 근사) — 위치 조언용. 필요할 때만 사용한다.
BOARD_SLOTS: list[tuple[str, tuple[float, float, float, float]]] = [
    (f"board_{row + 1}_{column + 1}",
     (0.3155 + column * 0.0535 + (0.0268 if row % 2 else 0.0), 0.362 + row * 0.075, 0.045, 0.080))
    for row in range(7)
    for column in range(4)
]

#: 숫자/게이지 영역(골드/레벨/HP 등) — 숫자 템플릿이 준비되면 쓴다.
INFO_REGIONS: dict[str, tuple[float, float, float, float]] = {
    "gold": (0.055, 0.905, 0.075, 0.045),
    "level": (0.055, 0.860, 0.045, 0.035),
    "my_hp": (0.300, 0.030, 0.080, 0.030),
    "stage_round": (0.455, 0.012, 0.090, 0.030),
}

#: ``INFO_REGIONS`` 중 **단일 숫자**로 읽는 영역. 라운드('4-2')는 구분자가 있어 따로 읽는다.
NUMERIC_INFO_KEYS: tuple[str, ...] = ("gold", "level", "my_hp")

#: 슬롯 박스 **안에서** 별(성급)이 찍히는 상대 영역 (x0, y0, x1, y1).
#: 별은 칸마다 같은 위치(하단 띠)에 1~3개가 같은 모양으로 찍히므로, 칸 전체가 아니라
#: 이 띠만 잘라서 개수를 센다. 칸 안 비율이라 해상도가 달라도 그대로 환산된다.
STAR_BAND: tuple[float, float, float, float] = (0.0, 0.76, 1.0, 1.0)


def star_band(
    slot_box: tuple[float, float, float, float],
    *,
    band: tuple[float, float, float, float] = STAR_BAND,
) -> tuple[float, float, float, float]:
    """슬롯 박스(비율 좌표든 픽셀이든) 안에서 별 영역의 하위 박스.

    계산이 선형이라 단위와 무관하다 — 비율 박스를 넣으면 비율 하위 박스가,
    픽셀 박스를 넣으면 픽셀 하위 박스가 나온다(픽셀이면 호출부가 반올림).
    """
    x, y, width, height = (float(value) for value in slot_box)
    x0, y0, x1, y1 = band
    return (x + width * x0, y + height * y0, width * (x1 - x0), height * (y1 - y0))

DEFAULT_LAYOUT_PATH = Path(__file__).resolve().parents[2] / "data" / "layout_1920x1080.json"


def to_pixels(
    box: tuple[float, float, float, float], width: int, height: int
) -> tuple[int, int, int, int]:
    """비율 좌표 -> 픽셀 (x, y, w, h)."""
    x, y, w, h = box
    return (
        int(round(x * width)),
        int(round(y * height)),
        max(1, int(round(w * width))),
        max(1, int(round(h * height))),
    )


AREA_KEYS = {"bench", "shop", "board"}
INFO_KEY = "info"


def load_overrides(path: str | Path | None = None) -> dict[str, Any]:
    """좌표 오버라이드 파일(JSON)을 읽는다. 없으면 빈 dict.

    형식::

        {
          "bench": [[x, y, w, h], ...],   # 칸 수가 기본값과 정확히 일치해야 한다
          "shop":  [[x, y, w, h], ...],
          "board": [[x, y, w, h], ...],
          "info":  {"gold": [x, y, w, h], "level": [x, y, w, h]}
        }

    알 수 없는 키는 조용히 무시하지 않는다 — 오타 하나가 좌표 전체 누락으로
    이어지고, 눈에 띄지 않으면 '인식 실패' 만 보여 원인을 찾지 못하기 때문이다.
    """
    target = Path(path) if path else DEFAULT_LAYOUT_PATH
    if not target.exists():
        return {}
    raw = json.loads(target.read_text(encoding="utf-8"))
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key.startswith("_"):
            continue
        if key in AREA_KEYS:
            if not isinstance(value, list):
                raise ValueError(f"'{key}' 는 좌표 목록([[x, y, w, h], ...])이어야 한다.")
            out[key] = [[float(item) for item in box] for box in value]
        elif key == INFO_KEY:
            if not isinstance(value, dict):
                raise ValueError(f"'{INFO_KEY}' 는 {{이름: [x, y, w, h]}} 형태여야 한다.")
            out[INFO_KEY] = {
                name: [float(item) for item in box] for name, box in value.items()
            }
        else:
            raise ValueError(
                f"좌표 파일에 알 수 없는 키 '{key}' 가 있다. "
                f"가능한 키: {', '.join(sorted(AREA_KEYS | {INFO_KEY}))}"
            )
    return out


def resolve(
    name: str, overrides: dict[str, Any] | None = None
) -> list[tuple[str, tuple[float, float, float, float]]]:
    """이름('bench'|'shop'|'board')에 대한 좌표 목록(오버라이드 반영).

    오버라이드 칸 수가 기본값과 다르면 **조용히 자르지 않고** 오류를 던진다.
    하나라도 빠지면 그 칸이 아예 안 읽히는데, 눈에 띄지 않으면 '인식 실패'로만
    보여 사용자가 좌표 누락이라는 원인을 찾지 못한다.
    """
    defaults = {"bench": BENCH_SLOTS, "shop": SHOP_SLOTS, "board": BOARD_SLOTS}[name]
    if not overrides or name not in overrides:
        return list(defaults)
    boxes = overrides[name]
    if len(boxes) != len(defaults):
        raise ValueError(
            f"'{name}' 좌표는 {len(defaults)}개가 필요한데 {len(boxes)}개다. "
            "칸 수가 맞지 않으면 일부 칸이 조용히 빠진다."
        )
    resolved: list[tuple[str, tuple[float, float, float, float]]] = []
    for index, box in enumerate(boxes):
        if len(box) != 4:
            raise ValueError(
                f"'{name}' 좌표 {index + 1}번은 (x, y, w, h) 4개 값이어야 한다 "
                f"(받은 값 {len(box)}개)."
            )
        resolved.append((defaults[index][0], tuple(box)))  # type: ignore[arg-type]
    return resolved


def read_slots(
    image: Image,
    template_set: TemplateSet,
    *,
    which: tuple[str, ...] = ("bench", "shop"),
    overrides: dict[str, Any] | None = None,
) -> list[dict[str, object]]:
    """지정한 영역들의 분류 결과를 돌려준다(칸별)."""
    results: list[dict[str, object]] = []
    for area in which:
        for slot_name, box in resolve(area, overrides):
            x, y, width, height = to_pixels(box, image.width, image.height)
            region = image.crop(x, y, width, height)
            match = classify(region, template_set)
            results.append(
                {
                    "slot": slot_name,
                    "area": area,
                    "box": [x, y, width, height],
                    **match.as_dict(),
                }
            )
    return results


def resolve_info(
    overrides: dict[str, Any] | None = None,
) -> dict[str, tuple[float, float, float, float]]:
    """숫자/게이지 영역 좌표(골드/레벨/HP/라운드, 오버라이드 반영).

    숫자를 한 자리라도 틀리면 골드 계획이 통째로 틀어지므로 이 영역들이야말로
    캘리브레이션 대상 1순위다. 그런데 예전에는 이들을 ``load_overrides`` 가
    아예 읽지 못해 파일로 보정할 방법이 없었다. 미지정 영역은 기본값을 쓴다.
    """
    merged = dict(INFO_REGIONS)
    if not overrides or INFO_KEY not in overrides:
        return merged
    given = overrides[INFO_KEY]
    for name, box in given.items():
        if name not in INFO_REGIONS:
            raise ValueError(
                f"알 수 없는 숫자 영역 '{name}'. 가능한 것: {', '.join(sorted(INFO_REGIONS))}"
            )
        if len(box) != 4:
            raise ValueError(
                f"'{INFO_KEY}.{name}' 는 (x, y, w, h) 4개 값이어야 한다 "
                f"(받은 값 {len(box)}개)."
            )
        merged[name] = (box[0], box[1], box[2], box[3])
    return merged
