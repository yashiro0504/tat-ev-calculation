"""화면 스캔 -> 로비 스냅샷 (CV 결과를 계산기에 연결).

흐름
----
    캡처(또는 BMP) -> 보드/벤치/상점 칸 분류 -> 챔피언 이름 -> 코스트 조회 -> 스냅샷 dict

정직성 규칙
----------
* **성급**은 별 개수를 세어 읽는다(``ocr.count_stars``: 분류가 아니라 밝은 픽셀 면적).
  0개(미검출)면 1성으로 두고 **고지**하며, 개수 판정이 정수 경계에 가까우면(애매) 확정하지
  않고 '확인 필요'로 뺀다 — 성급은 풀 소모를 1/3/9 로 바꾸므로 잘못 넣으면 3배 틀어진다.
  ``--star 'Ahri=2'`` 지정이 항상 우선이고, ``--no-star-ocr`` 로 끌 수 있다.
* **숫자(골드/레벨/HP)** 는 숫자 템플릿(``--digits``)이 있을 때만 읽고, 못 읽으면 ``None`` 이다.
  0 이나 추정값을 넣지 않는다 — 한 자리만 틀려도 골드 계획이 통째로 틀어진다.
* ``unknown``/``확인 필요`` 칸은 스냅샷에 넣지 않고 별도 목록으로 보고한다(추정 금지).
* **상점 칸은 '내 보유'가 아니다.** 상점에 보이는 기물은 아직 사지 않은 것이라 ``shop`` 키로
  따로 담고, 풀 계산(``lobby.LobbySnapshot``)은 ``board``/``bench`` 만 읽는다.
  예전엔 상점 칸을 ``board`` 로 넣어 **아직 안 산 기물을 이미 보유로** 셌고, 그래서 내 보유
  장수가 과대평가되고 남은 풀 사본이 과소평가되어 판정이 **낙관 편향**됐다.
  지금 산다고 가정하려면 ``shop_as_owned=True`` (CLI ``--shop-as-owned``) 로 **명시**한다.
* **상대는 건드리지 않는다.** 기존 스냅샷 파일이 있으면 상대 항목을 그대로 보존하고 내 것만 교체한다.
* 코스트를 모르는 챔피언(TFT 전용 유닛 등)은 스냅샷에 넣지 않고 ``missing_cost`` 로 보고한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import layout, ocr
from .fingerprint import TemplateSet
from .screen import Image

DEFAULT_COSTS = Path(__file__).resolve().parents[2] / "data" / "set18_unit_costs.json"

#: 숫자(0~9) 지문 템플릿 파일. 개인 캘리브레이션 산출물이라 ``.gitignore`` 대상이다
#: (``scripts/check_capture.py`` 로 BMP 를 저장해 숫자 칸을 크롭한 뒤 만든다).
DEFAULT_DIGITS = Path(__file__).resolve().parents[2] / "data" / "digits_1920x1080.json"

#: 스냅샷에 담기는 영역과 순서. ``shop`` 은 보유가 아니므로 계산에서 제외된다.
AREA_ORDER: tuple[str, ...] = ("board", "bench", "shop")

#: 영역 표시 이름(요약 출력용).
AREA_LABELS: dict[str, str] = {"board": "보드", "bench": "벤치", "shop": "상점"}


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
    #: 영역별 확정 유닛(board/bench/shop). ``shop`` 은 '보유'가 아니라 계산에 안 들어간다.
    by_area: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    #: 이 스캔에 적용된 가정(예: --shop-as-owned). 요약에 '[가정]' 으로 출력된다.
    notes: list[str] = field(default_factory=list)
    #: 숫자 OCR 결과(골드/레벨/HP). 못 읽으면 ``None`` — 0 으로 추정하지 않는다.
    info: dict[str, int | None] = field(default_factory=dict)
    #: 라운드 표기 OCR 결과('4-2' -> ``(4, 2)``). 못 읽으면 ``None``.
    stage_round: tuple[int, int] | None = None
    #: 별(성급) 인식을 켰는지. 요약 문구가 이 값에 따라 달라진다.
    star_ocr: bool = True

    def summary_lines(self) -> list[str]:
        lines = [
            f"인식 확정 {len(self.recognized)}칸 / 확인 필요 {len(self.review)}칸 "
            f"(신뢰도 {self.confidence * 100:.0f}%)"
        ]
        for item in self.recognized:
            lines.append(
                f"  [확정] {item['slot']:<9} {item['name']:<14} {item['cost']}코 "
                f"{item.get('star', 1)}성 (유사도 {float(item['score']) * 100:.1f}%)"
            )
        for item in self.review:
            if item.get("reason"):
                reason = str(item["reason"])
            elif item["name"] == "unknown":
                reason = "빈 칸/미등록"
            else:
                reason = f"모호({item['name']} vs {item['runner_up']}, 마진 {float(item['margin']):.3f})"
            lines.append(f"  [확인 필요] {item['slot']:<9} {reason}")
        if self.missing_cost:
            lines.append(
                "  [코스트 미확인] "
                + ", ".join(sorted(set(self.missing_cost)))
                + " (data/set18_unit_costs.json 에 추가하세요)"
            )
        if self.by_area:
            counts = " / ".join(
                f"{AREA_LABELS.get(area, area)} {len(self.by_area.get(area, []))}칸"
                for area in AREA_ORDER
            )
            lines.append(f"  [영역] {counts}")
            shop_units = self.by_area.get("shop", [])
            if shop_units:
                lines.append(
                    "  [상점] "
                    + ", ".join(str(unit["champion"]) for unit in shop_units)
                    + " — 상점 칸은 '보유'가 아니므로 풀 계산에 넣지 않았습니다"
                    "(사면 즉시 보유가 되니 그때 다시 스캔하거나 --shop-as-owned)."
                )
        for note in self.notes:
            lines.append(f"  [가정] {note}")
        if self.info or self.stage_round is not None:
            shown = " / ".join(
                f"{label} {self.info.get(key) if self.info.get(key) is not None else '?'}"
                for key, label in (("gold", "골드"), ("level", "레벨"), ("my_hp", "HP"))
            )
            round_text = (
                f"{self.stage_round[0]}-{self.stage_round[1]}"
                if self.stage_round is not None
                else "?"
            )
            lines.append(
                f"  [정보] {shown} / 라운드 {round_text}  ('?' = 못 읽음 → 손 입력)"
            )
        if self.star_ocr:
            lines.append(
                "  ※ 성급은 별 인식 결과입니다(임계값은 아직 캘리브레이션 전 — 실게임 화면에서 "
                "재확인 필요). 어긋나면 --star 'Ahri=2' 로 지정하세요."
            )
        else:
            lines.append(
                "  ※ 성급은 1로 기록했습니다(별 인식은 기본 꺼짐 — 캘리브레이션 전 안전 기본값). "
                "--star 'Ahri=2' 로 지정하거나 --star-ocr 로 켜세요."
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
    overrides: dict[str, Any] | None = None,
    shop_as_owned: bool = False,
    detect_stars: bool = False,
    digit_templates: TemplateSet | None = None,
) -> ScanReport:
    """화면 이미지를 스캔해 '내 보드/벤치(+상점)' 스냅샷을 만든다.

    * ``shop_as_owned=True`` 면 상점 칸을 '지금 산다'고 가정해 ``bench`` 로 옮긴다.
      기본값 False 는 **사지 않은 것을 보유로 세지 않는다**(낙관 편향 방지).
    * ``detect_stars`` — 별 개수를 세어 성급을 읽는다. **기본 False(꺼짐)** 인 이유:
      별 영역의 밝기 비율은 아이콘 자체의 밝은 픽셀과 섞이기 쉬워, 임계값을 실게임
      화면에 맞추기 전에는 1성을 2성으로 읽는 식의 **조용한 3배 오차**가 날 수 있다.
      켜면 애매/과대 비율은 확정하지 않고 '확인 필요'로 뺀다(``--star-ocr``).
    * ``digit_templates`` 가 있으면 골드/레벨/HP 를 읽어 ``info`` 에, 라운드 표기('4-2')를
      ``stage_round`` 에 담는다. 없으면 전부 ``None`` 이고 '손 입력 필요'가 고지된다.
    """
    stars = {key.lower(): value for key, value in (star_overrides or {}).items()}
    results = layout.read_slots(image, template_set, which=which, overrides=overrides)

    recognized: list[dict[str, object]] = []
    review: list[dict[str, object]] = []
    missing_cost: list[str] = []
    # 영역 키를 항상 만들어 둔다 — 스냅샷 스키마가 파일만 봐도 드러나게.
    by_area: dict[str, list[dict[str, object]]] = {area: [] for area in AREA_ORDER}
    star_unseen = 0

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
        # 성급: 사용자 지정 > 별 인식 > 기본값
        override = stars.get(champion.lower())
        if override is not None:
            star = int(override)
        elif detect_stars:
            slot_box = tuple(float(value) for value in item["box"][:4])
            ratio = ocr.star_ratio(image, layout.star_band(slot_box))
            if ocr.star_is_ambiguous(ratio):
                # 성급은 풀 소모를 1/3/9 로 바꾼다 -> 애매하면 확정하지 않는다
                review.append(
                    {
                        **item,
                        "needs_review": True,
                        "reason": (
                            f"성급 확인 필요(별 비율 {ratio:.3f} 가 경계) — "
                            "--star 로 지정하거나 별 임계값을 캘리브레이션하세요"
                        ),
                    }
                )
                continue
            detected = ocr.stars_from_ratio(ratio)
            if detected >= 1:
                star = detected
            else:
                # 0성은 존재하지 않는다 -> '별을 못 봤다'. 기본값으로 두되 몇 칸인지 고지한다.
                star = default_star
                star_unseen += 1
        else:
            star = default_star

        recognized.append({**item, "cost": cost, "star": star})
        area = str(item["area"])
        if area == "shop" and shop_as_owned:
            area = "bench"  # '사면 즉시 보유' 가정 — notes 로 항상 고지한다
        by_area.setdefault(area, []).append(
            {"champion": champion, "cost": cost, "star": star}
        )

    notes: list[str] = []
    if shop_as_owned:
        notes.append(
            "--shop-as-owned: 상점 칸을 '지금 산다'고 가정해 보유로 셉니다. "
            "실제로 사지 않으면 보유 장수가 과대평가됩니다(낙관 편향)."
        )
    if detect_stars and star_unseen:
        notes.append(
            f"별을 못 본 칸 {star_unseen}개를 기본 {default_star}성으로 두었습니다"
            "(0성은 없음). --star 로 지정할 수 있습니다."
        )

    has_digits = bool(digit_templates and digit_templates.templates)
    info_regions = layout.resolve_info(overrides)
    info: dict[str, int | None] = {key: None for key in layout.NUMERIC_INFO_KEYS}
    stage_round: tuple[int, int] | None = None
    if has_digits:
        for key in layout.NUMERIC_INFO_KEYS:
            info[key] = ocr.read_number(
                ocr.crop_box(
                    image, layout.to_pixels(info_regions[key], image.width, image.height)
                ),
                digit_templates,  # type: ignore[arg-type]
            )
        stage_round = ocr.read_round(
            ocr.crop_box(
                image,
                layout.to_pixels(
                    info_regions["stage_round"], image.width, image.height
                ),
            ),
            digit_templates,  # type: ignore[arg-type]
        )
    digit_hint = "" if has_digits else "(숫자 템플릿이 없습니다: --digits)"
    unread = [key for key in layout.NUMERIC_INFO_KEYS if info.get(key) is None]
    if unread:
        notes.append(
            "숫자(" + ", ".join(unread) + ") 미인식 -> 손 입력 필요" + digit_hint
        )
    if stage_round is None:
        notes.append("라운드 표기('4-2') 미인식 -> 손 입력 필요" + digit_hint)

    mine: dict[str, object] = {"name": name, "is_me": True}
    for area in AREA_ORDER:
        mine[area] = by_area.get(area, [])

    total = len(results)
    return ScanReport(
        snapshot={"players": [mine]},
        recognized=recognized,
        review=review,
        missing_cost=missing_cost,
        confidence=(len(recognized) / total) if total else 0.0,
        by_area=by_area,
        notes=notes,
        info=info,
        stage_round=stage_round,
        star_ocr=detect_stars,
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
    return {
        "_comment": (
            "상대는 기존 스냅샷에서 보존, 내 보드/벤치/상점은 화면 스캔 결과"
            "(상점은 '보유'가 아니므로 계산에서 제외됨)"
        ),
        "players": players,
    }


def write_snapshot(snapshot: dict[str, object], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
