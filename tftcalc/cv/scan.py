"""화면 스캔 -> 로비 스냅샷 (CV 결과를 계산기에 연결).

흐름
----
    캡처(또는 BMP) -> 벤치/상점 칸 분류 -> 챔피언 이름 -> 코스트 조회 -> 스냅샷 dict

정직성 규칙
----------
* **성급은 아이콘만으로 읽을 수 없다** -> 1로 두고 '확인 필요'로 보고한다(``star_overrides`` 로 수정).
* ``unknown``/``확인 필요`` 칸은 스냅샷에 넣지 않고 별도 목록으로 보고한다(추정 금지).
* **상대는 건드리지 않는다.** 기존 스냅샷 파일이 있으면 상대 항목을 그대로 보존하고 내 것만 교체한다.
* 코스트를 모르는 챔피언(TFT 전용 유닛 등)은 스냅샷에 넣지 않고 ``missing_cost`` 로 보고한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import layout
from .fingerprint import TemplateSet
from .screen import Image

DEFAULT_COSTS = Path(__file__).resolve().parents[2] / "data" / "set18_unit_costs.json"


def load_cost_table(path: str | Path = DEFAULT_COSTS) -> dict[str, int]:
    """챔피언 이름 -> 코스트 표(직접 입력한 로비 스냅샷이 쓰는 값과 동일한 출처)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    table: dict[str, int] = {}
    for entry in raw.get("units", {}).values():
        name = str(entry.get("name", "")).strip()
        cost = entry.get("cost")
        if name and isinstance(cost, int):
            table[name] = cost
    return table


@dataclass
class ScanReport:
    snapshot: dict[str, object]
    recognized: list[dict[str, object]] = field(default_factory=list)
    review: list[dict[str, object]] = field(default_factory=list)
    missing_cost: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def summary_lines(self) -> list[str]:
        lines = [
            f"인식 확정 {len(self.recognized)}칸 / 확인 필요 {len(self.review)}칸 "
            f"(신뢰도 {self.confidence * 100:.0f}%)"
        ]
        for item in self.recognized:
            lines.append(
                f"  [확정] {item['slot']:<9} {item['name']:<14} "
                f"{item['cost']}코 (유사도 {float(item['score']) * 100:.1f}%)"
            )
        for item in self.review:
            reason = (
                "빈 칸/미등록"
                if item["name"] == "unknown"
                else f"모호({item['name']} vs {item['runner_up']}, 마진 {float(item['margin']):.3f})"
            )
            lines.append(f"  [확인 필요] {item['slot']:<9} {reason}")
        if self.missing_cost:
            lines.append(
                "  [코스트 미확인] "
                + ", ".join(sorted(set(self.missing_cost)))
                + " (data/set18_unit_costs.json 에 추가하세요)"
            )
        lines.append(
            "  ※ 성급은 1로 기록했습니다(아이콘으로는 못 읽음). "
            "--star 'Ahri=2' 로 지정하거나 스냅샷 파일에서 직접 수정하세요."
        )
        return lines


def scan(
    image: Image,
    template_set: TemplateSet,
    cost_table: dict[str, int],
    *,
    which: tuple[str, ...] = ("bench", "shop"),
    star_overrides: dict[str, int] | None = None,
    default_star: int = 1,
    name: str = "나",
    overrides: dict[str, list[list[float]]] | None = None,
) -> ScanReport:
    """화면 이미지를 스캔해 '내 보드/벤치' 스냅샷을 만든다."""
    stars = {key.lower(): value for key, value in (star_overrides or {}).items()}
    results = layout.read_slots(image, template_set, which=which, overrides=overrides)

    recognized: list[dict[str, object]] = []
    review: list[dict[str, object]] = []
    missing_cost: list[str] = []
    units: list[dict[str, object]] = []

    for item in results:
        champion = str(item["name"])
        if item["needs_review"] or champion == "unknown":
            review.append(item)
            continue
        cost = cost_table.get(champion)
        if cost is None:
            missing_cost.append(champion)
            review.append({**item, "needs_review": True})
            continue
        star = int(stars.get(champion.lower(), default_star))
        recognized.append({**item, "cost": cost, "star": star})
        units.append({"champion": champion, "cost": cost, "star": star})

    total = len(results)
    return ScanReport(
        snapshot={
            "players": [{"name": name, "is_me": True, "board": units, "bench": []}]
        },
        recognized=recognized,
        review=review,
        missing_cost=missing_cost,
        confidence=(len(recognized) / total) if total else 0.0,
    )


def merge_with_opponents(
    snapshot: dict[str, object], existing_path: str | Path | None
) -> dict[str, object]:
    """기존 스냅샷의 상대 항목을 보존하고 '내 것'만 교체한다.

    상대 보드는 화면 스캔으로 얻을 수 없으므로(스카우팅/GEP 영역) 지워서 정확도를
    떨어뜨리지 않도록 한다.
    """
    if existing_path is None:
        return snapshot
    path = Path(existing_path)
    if not path.exists():
        return snapshot
    existing = json.loads(path.read_text(encoding="utf-8"))
    mine = next(
        (player for player in snapshot.get("players", []) if player.get("is_me")),
        None,
    )
    others = [
        player
        for player in existing.get("players", [])
        if not player.get("is_me")
    ]
    players = ([mine] if mine else []) + others
    return {"_comment": "상대는 기존 스냅샷에서 보존, 내 보드/벤치는 화면 스캔 결과", "players": players}


def write_snapshot(snapshot: dict[str, object], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
