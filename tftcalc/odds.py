"""상점 확률 테이블.

이 모듈의 유일한 책무는 "이 (레벨, 코스트) 확률을 아는가/모르는가"를 정직하게 답하는 것.
모르면 추정하지 않고 UnknownOddsError 를 던진다. 그 예외가 곧 사용자에게 주는
'데이터 갱신 필요' 알림이다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import set_data


class UnknownOddsError(LookupError):
    """해당 (레벨, 코스트) 상점 확률을 알 수 없을 때 발생."""


class InvalidOddsError(ValueError):
    """확률표 값이 검증에 실패했을 때(범위/합계 오류).

    UnknownOddsError 가 "모른다" 면 이것은 "적혔는데 틀렸다" 다.
    둘 다 추정으로 메우지 않고 멈춘다 — 300% 나 총합 105% 를 그대로 받아들이면
    계산기가 정확한 척하는 거짓말을 하게 되기 때문이다.
    """


@dataclass
class ShopOdds:
    """(level, cost) -> 확률 맵."""

    cells: dict[tuple[int, int], float]
    source: str = "builtin"
    patch: str | None = None
    _levels: set[int] = field(default_factory=set)

    # ---- 생성 -------------------------------------------------------------
    @classmethod
    def builtin(cls) -> "ShopOdds":
        return cls(cells=dict(set_data.VERIFIED_SHOP_ODDS), source="builtin(검증 셀)")

    @classmethod
    def from_json(cls, path: str | Path, base: "ShopOdds | None" = None) -> "ShopOdds":
        """JSON 파일을 병합한다. 파일 값이 항상 우선한다.

        JSON 형식::

            {
              "patch": "18.1",
              "source": "인게임 상점 확률 툴팁 / 패치노트",
              "odds": {"8": {"4": 30, "3": 32}, "7": {"3": 35}}
            }

        값은 퍼센트(30 == 30%)로 적는다.
        """
        base = base or cls.builtin()
        source_name = Path(path).name
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cells = dict(base.cells)
        for level_key, row in data.get("odds", {}).items():
            level = int(level_key)
            for cost_key, pct in row.items():
                cost = int(cost_key)
                value = float(pct)
                if not 0.0 <= value <= 100.0:
                    raise InvalidOddsError(
                        f'{source_name}: odds["{level}"]["{cost}"] = {value} 는 0~100 '
                        "범위를 벗어났다. 값은 퍼센트다(30 == 30%)."
                    )
                if 0.0 < value < 1.0:
                    # 소수로 적으면 100배 작아진다(0.30 -> 0.3%). 명백한 실수 신호.
                    raise InvalidOddsError(
                        f'{source_name}: odds["{level}"]["{cost}"] = {value} 는 1% 미만이다. '
                        "값은 퍼센트(30 == 30%)로 적는다 — 0.30 이면 0.3% 가 되므로 "
                        "30 으로 쓸 것."
                    )
                cells[(level, cost)] = value / 100.0

        # 같은 레벨의 코스트 확률 합은 100% 를 넘지 않는다(부분 표는 허용).
        for level in sorted({lvl for lvl, _ in cells}):
            total = sum(p for (lvl, _), p in cells.items() if lvl == level)
            if total > 1.0 + 1e-9:
                raise InvalidOddsError(
                    f"{source_name}: Lv{level} 상점 확률 합계가 {total * 100:.1f}% 로 "
                    "100% 를 넘는다. 같은 레벨의 코스트 확률은 합쳐서 100% 를 넘지 않는다."
                )
        return cls(
            cells=cells,
            source=f"builtin + {source_name}",
            patch=data.get("patch"),
        )

    # ---- 조회 -------------------------------------------------------------
    def cost_odds(self, level: int, cost: int) -> float:
        """레벨에서 해당 코스트가 상점 한 칸에 나올 확률. 모르면 예외."""
        try:
            return self.cells[(level, cost)]
        except KeyError as exc:  # 추정하지 않는다
            raise UnknownOddsError(
                f"{level}레벨 {cost}코 상점 확률을 모릅니다. "
                f"인게임 상점 확률 툴팁/패치노트 값을 data/set18_shop_odds.json 의 "
                f'"odds": {{"{level}": {{"{cost}": <퍼센트>}}}} 에 추가하세요.'
            ) from exc

    def knows(self, level: int, cost: int) -> bool:
        return (level, cost) in self.cells

    def known_levels(self) -> list[int]:
        return sorted({level for level, _ in self.cells})

    def known_costs(self, level: int) -> list[int]:
        return sorted(cost for lvl, cost in self.cells if lvl == level)

    def describe(self) -> str:
        lines = [f"상점 확률 소스: {self.source}"
                 + (f" (패치 {self.patch})" if self.patch else "")]
        for level in self.known_levels():
            row = ", ".join(
                f"{cost}코 {self.cells[(level, cost)] * 100:.1f}%"
                for cost in self.known_costs(level)
            )
            lines.append(f"  Lv{level}: {row}")
        lines.append("  (표에 없는 레벨/코스트는 계산하지 않습니다. 데이터를 채워 넣으세요.)")
        return "\n".join(lines)
