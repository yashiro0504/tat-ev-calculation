"""아이콘 지문(fingerprint) 기반 인식.

왜 슬라이딩 템플릿 매칭이 아니라 '칸 분류'인가
--------------------------------------------
TFT UI 는 좌표가 고정이다(벤치 9칸, 상점 5칸, 보드 헥스). 그래서 화면 전체를 훑는
탐색(슬라이딩 윈도우)이 필요 없다. 칸 영역을 잘라 **NxN 그레이스케일 지문**으로 줄이고
후보 템플릿과 거리를 비교하면, 순수 파이썬으로도 칸당 수십 마이크로초 수준이다.

정직성 규칙(README 3.5 와 동일)
------------------------------
* 1등과 2등의 점수 차(margin)가 작으면 ``needs_review=True`` 로 표시하고 자동 확정하지 않는다.
* 최고 유사도가 기준 미만이면 ``name="unknown"`` 으로 남긴다(추정 금지).
* 지문은 평균/표준편차로 정규화해 밝기 변화(테마, 밝기 설정)에 강하게 만든다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .screen import Image

DEFAULT_GRID = 8
DEFAULT_INSET = 0.18  # 칸 영역에서 테두리/발광을 피하려고 중앙부만 사용


def fingerprint(image: Image, grid: int = DEFAULT_GRID, inset: float = DEFAULT_INSET) -> list[float]:
    """영역 -> 정규화된 NxN 그레이스케일 지문(평균 0, 표준편차 1)."""
    if image.width <= 0 or image.height <= 0:
        raise ValueError("빈 영역은 지문을 만들 수 없습니다.")
    margin_x = int(image.width * inset)
    margin_y = int(image.height * inset)
    left, top = margin_x, margin_y
    right, bottom = max(left + 1, image.width - margin_x), max(top + 1, image.height - margin_y)
    cell_width = (right - left) / grid
    cell_height = (bottom - top) / grid

    values: list[float] = []
    for row in range(grid):
        for column in range(grid):
            x0 = int(left + column * cell_width)
            x1 = max(x0 + 1, int(left + (column + 1) * cell_width))
            y0 = int(top + row * cell_height)
            y1 = max(y0 + 1, int(top + (row + 1) * cell_height))
            total = 0.0
            count = 0
            for y in range(y0, min(y1, image.height)):
                for x in range(x0, min(x1, image.width)):
                    total += image.gray(x, y)
                    count += 1
            values.append(total / count if count else 0.0)

    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    deviation = math.sqrt(variance)
    if deviation < 1e-6:
        return [0.0] * len(values)
    return [(value - mean) / deviation for value in values]


def distance(first: list[float], second: list[float]) -> float:
    """정규화 지문 간 평균 L1 거리(0 = 동일, 2 = 완전 반대)."""
    if len(first) != len(second):
        raise ValueError("지문 크기가 다릅니다.")
    return sum(abs(a - b) for a, b in zip(first, second)) / len(first)


def similarity(first: list[float], second: list[float]) -> float:
    """거리를 0~1 유사도로 환산(1 = 동일)."""
    return max(0.0, 1.0 - distance(first, second) / 2.0)


@dataclass
class Match:
    name: str
    score: float          # 최고 유사도(0~1)
    margin: float         # 1등 - 2등
    needs_review: bool
    runner_up: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "score": round(self.score, 4),
            "margin": round(self.margin, 4),
            "runner_up": self.runner_up,
            "needs_review": self.needs_review,
        }


@dataclass
class Template:
    name: str
    values: list[float]

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "values": [round(v, 4) for v in self.values]}


@dataclass
class TemplateSet:
    grid: int
    templates: list[Template]
    source: str = "?"
    meta: dict[str, object] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "TemplateSet":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            grid=int(raw.get("grid", DEFAULT_GRID)),
            templates=[
                Template(name=str(item["name"]), values=[float(v) for v in item["values"]])
                for item in raw.get("templates", [])
            ],
            source=str(raw.get("source", str(path))),
            meta=dict(raw.get("meta", {})),
        )

    def save(self, path: str | Path) -> None:
        payload = {
            "_readme": [
                "scripts/build_templates.py 가 생성하거나, 사용자가 캡처해서 만든 아이콘 지문.",
                "values 는 평균0/표준편차1 로 정규화된 grid x grid 그레이스케일이다.",
            ],
            "grid": self.grid,
            "source": self.source,
            "meta": self.meta,
            "templates": [template.as_dict() for template in self.templates],
        }
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def names(self) -> list[str]:
        return [template.name for template in self.templates]


def classify(
    image: Image,
    template_set: TemplateSet,
    *,
    inset: float = DEFAULT_INSET,
    review_margin: float = 0.05,
    min_score: float = 0.5,
) -> Match:
    """영역을 템플릿 중 하나로 분류한다. 애매하면 needs_review=True."""
    query = fingerprint(image, grid=template_set.grid, inset=inset)
    if not template_set.templates:
        return Match(name="unknown", score=0.0, margin=0.0, needs_review=True)
    if not any(query):
        # 단색(빈 칸/가림) 영역은 정보가 없다 -> 추정하지 않고 unknown.
        return Match(name="unknown", score=0.0, margin=0.0, needs_review=True)

    scored = sorted(
        (
            (similarity(query, template.values), template.name)
            for template in template_set.templates
        ),
        reverse=True,
    )
    best_score, best_name = scored[0]
    if len(scored) > 1:
        second_score, second_name = scored[1]
        margin = best_score - second_score
    else:
        second_name, margin = None, 1.0

    if best_score < min_score or margin < review_margin:
        return Match(
            name="unknown" if best_score < min_score else best_name,
            score=best_score,
            margin=margin,
            needs_review=True,
            runner_up=second_name if isinstance(second_name, str) else None,
        )
    return Match(
        name=best_name,
        score=best_score,
        margin=margin,
        needs_review=False,
        runner_up=second_name if isinstance(second_name, str) else None,
    )
