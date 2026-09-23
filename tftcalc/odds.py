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
    """확률표 값이 검증에 실패했을 때(범위/합계/키 오류).

    UnknownOddsError 가 "모른다" 면 이것은 "적혔는데 틀렸다" 다.
    둘 다 추정으로 메우지 않고 멈춘다 — 300% 나 총합 105% 를 그대로 받아들이면
    계산기가 정확한 척하는 거짓말을 하게 되기 때문이다.
    """


#: 실전 상점 확률표(사람이 채워 넣는 파일). 다른 ``data/*.json`` 과 같이 **있으면 자동으로**
#: 기본 표 위에 얹힌다. ``odds`` 명령이 채움 진행률과 격자를 보여준다.
DEFAULT_ODDS_FILE = Path(__file__).resolve().parents[1] / "data" / "set18_shop_odds.json"


@dataclass
class ShopOdds:
    """(level, cost) -> 확률 맵."""

    cells: dict[tuple[int, int], float]
    source: str = "builtin"
    patch: str | None = None
    #: 지금까지 겹쳐진 **모든 파일이 선언한 셀의 합집합**(= 미채움 후보). 값이 null 이면
    #: 아직 모르는 셀이고 격자에 '?' 로 남는다. 어느 파일이 선언했든 숨기지 않기 위해
    #: 합집합으로 모은다 — 그래서 ``--odds-file`` 로 일부만 덮어써도 실전 파일의
    #: 미채움 셀이 격자에서 사라지지 않는다. (예전의 미사용 필드 ``_levels`` 를 대체.)
    declared: set[tuple[int, int]] = field(default_factory=set)

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
              "odds": {"8": {"4": 30, "3": 32}, "7": {"3": null}}
            }

        값 표기 규칙
        ------------
        * 값은 **퍼센트**로 적는다(``30 == 30%``). ``0.30`` 이라고 쓰면 0.3% 가 되므로 거부한다.
        * ``null`` 은 **미채움(모름)** 이다. 셀을 넣지 않으므로 그 셀을 쓰는 계산은 추정 대신
          ``UnknownOddsError`` 로 멈춘다. 덕분에 **스켈레톤을 커밋해 두고 하나씩 채울 수 있다**
          (``odds`` 명령이 진행률과 격자를 보여준다).
        * 같은 레벨의 코스트 합은 100% 를 넘을 수 없다(부분 표는 허용).
        * 레벨/코스트가 격자 범위(``set_data.SHOP_ODDS_LEVELS``/``_COSTS``)를 벗어나면
          키 오타로 보고 거부한다.
        """
        base = base or cls.builtin()
        source_name = Path(path).name
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cells = dict(base.cells)
        # 선언은 합집합으로 모은다 — 어느 파일이 선언했든 '아직 모르는 셀'은
        # 격자에 '?' 로 남아야 한다(정보를 숨기지 않는다).
        declared: set[tuple[int, int]] = set(base.declared)

        for level_key, row in data.get("odds", {}).items():
            level = int(level_key)
            if level not in set_data.SHOP_ODDS_LEVELS:
                raise InvalidOddsError(
                    f"{source_name}: 레벨 {level} 은 상점 확률표 범위 밖이다"
                    f"(1~{set_data.MAX_LEVEL}). 키 오타인지 확인하세요."
                )
            for cost_key, pct in row.items():
                cost = int(cost_key)
                if cost not in set_data.SHOP_ODDS_COSTS:
                    raise InvalidOddsError(
                        f"{source_name}: 코스트 {cost} 는 없다"
                        f"(1~{max(set_data.SHOP_ODDS_COSTS)}). 키 오타인지 확인하세요."
                    )
                declared.add((level, cost))
                if pct is None:
                    continue  # 미채움 — 0 으로도 다른 값으로도 추정하지 않는다
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
            # base.source 를 이어붙여 체인을 보존한다(예: builtin + A.json + B.json).
            source=f"{base.source} + {source_name}",
            patch=data.get("patch"),
            declared=declared,
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

    def pending(self) -> list[tuple[int, int]]:
        """파일에 **선언은 됐지만 값이 없는(null)** 셀 — 즉 아직 모르는 셀.

        진행률 표시용이다. builtin(검증 셀)으로 아는 셀은 여기에 안 들어간다.
        """
        return sorted(set(self.declared) - set(self.cells))

    def known_levels(self) -> list[int]:
        return sorted({level for level, _ in self.cells})

    def known_costs(self, level: int) -> list[int]:
        return sorted(cost for lvl, cost in self.cells if lvl == level)

    def describe_source(self) -> str:
        """소스/패치 한 줄(격자와 함께 쓸 때)."""
        return f"상점 확률 소스: {self.source}" + (
            f" (패치 {self.patch})" if self.patch else ""
        )

    def describe(self) -> str:
        lines = [self.describe_source()]
        for level in self.known_levels():
            row = ", ".join(
                f"{cost}코 {self.cells[(level, cost)] * 100:.1f}%"
                for cost in self.known_costs(level)
            )
            lines.append(f"  Lv{level}: {row}")
        lines.append("  (표에 없는 레벨/코스트는 계산하지 않습니다. 데이터를 채워 넣으세요.)")
        return "\n".join(lines)
