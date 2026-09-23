"""로비 스냅샷 -> 챔피언별 '남은 사본' 집계.

이 모듈이 '데이터 획득 경계'다. 수동 입력이든, 화면인식(OpenCV)이든,
Overwolf GEP 든 결과는 같은 스냅샷 dict 로 들어온다. 수학 코어는 출처를 모른다.

스냅샷 JSON::

    {
      "players": [
        {"name": "나", "is_me": true, "board": [{"champion": "Karma", "cost": 4, "star": 2}],
         "bench": [{"champion": "Sentry", "cost": 3, "star": 1}]},
        {"name": "A", "board": [], "bench": [{"champion": "Karma", "cost": 4, "star": 1}]}
      ]
    }

핵심 규칙
--------
* 성급은 '풀에서 소모된 사본 수'로 환산한다 (1성=1, 2성=3, 3성=9).
  -> 성급을 모르면 1로 뭉개지 않고 예외를 던진다. 오차가 곧 잘못된 조언이기 때문.
* 스카우트하지 않은 플레이어는 '아무것도 안 들고 있다'와 구분해야 하므로
  confidence() 로 신뢰도를 함께 내보낸다(숨기지 않는다).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import set_data

TOTAL_PLAYERS = 8


@dataclass(frozen=True)
class UnitInPlay:
    """보드/대기석 위의 기물 하나."""

    champion: str
    cost: int
    star: int = 1

    @property
    def copies(self) -> int:
        if self.star not in set_data.STAR_COPY_WEIGHTS:
            raise ValueError(f"{self.champion}: 지원하지 않는 성급 {self.star}")
        return set_data.STAR_COPY_WEIGHTS[self.star]


@dataclass
class PlayerSnapshot:
    name: str
    is_me: bool = False
    units: list[UnitInPlay] = field(default_factory=list)

    @property
    def copies_by_champion(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for unit in self.units:
            out[unit.champion] = out.get(unit.champion, 0) + unit.copies
        return out


@dataclass
class LobbySnapshot:
    players: list[PlayerSnapshot]

    # ---- 생성 -------------------------------------------------------------
    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "LobbySnapshot":
        """스냅샷 dict -> LobbySnapshot (JSON/스캔 결과 공통 경로)."""
        players: list[PlayerSnapshot] = []
        for entry in raw.get("players", []):  # type: ignore[union-attr]
            units = [
                UnitInPlay(
                    champion=unit["champion"],
                    cost=int(unit["cost"]),
                    star=int(unit.get("star", 1)),
                )
                for key in ("board", "bench", "items_held")
                for unit in entry.get(key, [])
            ]
            players.append(
                PlayerSnapshot(
                    name=entry["name"],
                    is_me=bool(entry.get("is_me", False)),
                    units=units,
                )
            )
        return cls(players=players)

    @classmethod
    def from_json(cls, path: str | Path) -> "LobbySnapshot":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # ---- 집계 -------------------------------------------------------------
    def copies_in_play(self) -> dict[str, int]:
        """모든 플레이어 보드+대기석 기준 챔피언별 소모 사본 수."""
        out: dict[str, int] = {}
        for player in self.players:
            for champion, copies in player.copies_by_champion.items():
                out[champion] = out.get(champion, 0) + copies
        return out

    def copies_in_play_of_tier(self, cost: int) -> int:
        """해당 코스트 등급에서 소모된 사본 수(스냅샷이 아는 범위)."""
        return sum(
            copies
            for champion, copies in self.copies_in_play().items()
            if self.cost_of(champion) == cost
        )

    def cost_of(self, champion: str) -> int:
        """스냅샷에 등장한 기물의 코스트를 역추적한다(없으면 예외)."""
        for player in self.players:
            for unit in player.units:
                if unit.champion == champion:
                    return unit.cost
        raise KeyError(f"'{champion}' 의 코스트를 스냅샷에서 알 수 없습니다.")

    def my_copies_map(self) -> dict[str, int]:
        """내가 보유한 챔피언별 사본 수 전체."""
        for player in self.players:
            if player.is_me:
                return dict(player.copies_by_champion)
        raise KeyError("is_me=true 인 플레이어가 스냅샷에 없습니다.")

    def my_copies(self, champion: str) -> int:
        return self.my_copies_map().get(champion, 0)

    def opponents_copies(self, champion: str) -> int:
        total = 0
        for player in self.players:
            if not player.is_me:
                total += player.copies_by_champion.get(champion, 0)
        return total

    # ---- 신뢰도 -----------------------------------------------------------
    def observed_opponents(self) -> int:
        return sum(1 for player in self.players if not player.is_me)

    def confidence(self) -> float:
        """관측한 상대 수 / 7. 1.0 이면 전부 스카우트한 상태."""
        return min(1.0, self.observed_opponents() / (TOTAL_PLAYERS - 1))

    def confidence_note(self) -> str:
        value = self.confidence()
        if value >= 1.0:
            return "상대 7명 전부 관측(신뢰도 100%)"
        return (
            f"상대 {self.observed_opponents()}/7명만 관측(신뢰도 {value * 100:.0f}%) "
            f"-> 미관측 플레이어의 보유분이 0으로 잡혀 남은 사본이 과대평가된다"
        )

    def contest_table(self, cost: int | None = None) -> list[dict[str, object]]:
        """(선택) 코스트 필터를 적용한 기물별 소모/남은 사본 표."""
        rows: list[dict[str, object]] = []
        for champion, copies in sorted(self.copies_in_play().items()):
            champion_cost = self.cost_of(champion)
            if cost is not None and champion_cost != cost:
                continue
            tier = set_data.TIER_POOLS[champion_cost]
            remaining = max(0, tier.copies_per_champion - copies)
            rows.append(
                {
                    "champion": champion,
                    "cost": champion_cost,
                    "copies_in_play": copies,
                    "remaining": remaining,
                    "pool_per_champion": tier.copies_per_champion,
                    "impossible": remaining == 0,
                }
            )
        return sorted(rows, key=lambda row: (int(row["remaining"]), str(row["champion"])))
