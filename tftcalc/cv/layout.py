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
"""

from __future__ import annotations

import json
from pathlib import Path

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


def load_overrides(path: str | Path | None = None) -> dict[str, list[list[float]]]:
    """좌표 오버라이드 파일(JSON)을 읽는다. 없으면 빈 dict."""
    target = Path(path) if path else DEFAULT_LAYOUT_PATH
    if not target.exists():
        return {}
    raw = json.loads(target.read_text(encoding="utf-8"))
    return {
        key: [[float(value) for value in box] for box in boxes]
        for key, boxes in raw.items()
        if isinstance(boxes, list) and key in {"bench", "shop", "board"}
    }


def resolve(
    name: str, overrides: dict[str, list[list[float]]] | None = None
) -> list[tuple[str, tuple[float, float, float, float]]]:
    """이름('bench'|'shop'|'board')에 대한 좌표 목록(오버라이드 반영)."""
    defaults = {"bench": BENCH_SLOTS, "shop": SHOP_SLOTS, "board": BOARD_SLOTS}[name]
    if not overrides or name not in overrides:
        return list(defaults)
    boxes = overrides[name]
    return [
        (defaults[index][0], tuple(box))  # type: ignore[arg-type]
        for index, box in enumerate(boxes[: len(defaults)])
    ]


def read_slots(
    image: Image,
    template_set: TemplateSet,
    *,
    which: tuple[str, ...] = ("bench", "shop"),
    overrides: dict[str, list[list[float]]] | None = None,
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


def build_snapshot(
    read_results: list[dict[str, object]],
    *,
    my_units: list[dict[str, object]] | None = None,
    name: str = "나",
) -> dict[str, object]:
    """인식 결과 -> LobbySnapshot 형식의 dict(내 보드/벤치만).

    주의: 이 도구는 **내 화면만** 읽는다. 상대 보드는 스카우팅(GEP/수동)으로 채운다.
    성급(star)은 아이콘만으로는 알 수 없으므로 기본 1로 두고, 필요하면 사용자가 올린다.
    """
    units = my_units if my_units is not None else []
    if my_units is None:
        for item in read_results:
            if item.get("name") not in (None, "unknown") and not item.get("needs_review"):
                units.append({"champion": item["name"], "cost": None, "star": 1})
    return {"players": [{"name": name, "is_me": True, "board": units, "bench": []}]}
