"""라운드 수입 / 롤 타이밍 모델 (시간 축).

목적: "4-2에 63골드로 이 덱이 되나?" 같은 질문에 답한다.
지금까지 만든 것(유닛 확률 + 아이템 부품)은 **공간** 축이고, 이 모듈은 **시간** 축이다.

수치 출처 (tft.ninja economy / stages 가이드)
-------------------------------------------
* 기본 수입: 1-2=2, 1-3=2, 1-4=3, 2-1=4, 2-2 부터 5골드/라운드
* PvP 승리 보너스: +1골드 (스트릭과 독립적으로 중첩)
* 연승/연패 스트릭 골드: 2~4연속 +1, 5연속 +2, 6연속 이상 +3
* 이자: 보유 골드 // 10, 최대 5 (50골드 이상이면 5)
* 라운드 구조(2스테이지부터): X-1~X-3 PvP, X-4 캐러셀, X-5~X-6 PvP, X-7 PvE
* PvE 라운드는 오브에서 골드가 나오지만 수치가 공개되어 있지 않다
  -> ``pve_gold`` 로 사용자가 지정한다(기본 3, 가정임을 출력에 명시).

모델의 가정 (정직하게)
--------------------
* 승리 여부는 모른다 -> ``win_rate`` 로 **기대값**을 쓴다(기본 0.5).
* 스트릭은 유지된다고 가정한다(``streak_behavior="hold"``). "reset" 으로 보수적 계산도 가능.
* 이자는 **그 라운드 소비 후** 남은 골드로 계산한다(게임과 동일).
* 레벨업 비용은 패시브 XP(라운드당 2)를 반영해 계산한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import set_data

#: PvE 라운드 기본 골드(공개 수치가 없어 가정). 출력에 항상 표기한다.
DEFAULT_PVE_GOLD = 3

#: 라운드 유형
PVP, PVE, CAROUSEL = "PvP", "PvE", "Carousel"


def parse_round(value: str) -> tuple[int, int]:
    """'4-2' -> (4, 2)"""
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", value)
    if not match:
        raise ValueError(f"라운드 형식이 잘못되었습니다: '{value}' (예: 4-2)")
    return int(match.group(1)), int(match.group(2))


def format_round(stage: int, rnd: int) -> str:
    return f"{stage}-{rnd}"


def round_type(stage: int, rnd: int) -> str:
    """스테이지 2부터의 표준 구조. 스테이지 1은 전부 PvE."""
    if stage <= 1:
        return PVE
    if rnd == 4:
        return CAROUSEL
    if rnd == 7:
        return PVE
    return PVP


#: 스테이지별 라운드 수. 스테이지 1 은 1-1~1-4 (4라운드), 2 부터는 7라운드.
STAGE_LENGTHS: dict[int, int] = {1: 4}
DEFAULT_STAGE_LENGTH = 7


def stage_length(stage: int) -> int:
    """그 스테이지의 라운드 수(스테이지 1 = 4, 나머지 = 7)."""
    return STAGE_LENGTHS.get(stage, DEFAULT_STAGE_LENGTH)


def round_sequence(start: tuple[int, int], count: int) -> list[tuple[int, int]]:
    """(stage, round) 를 count 개 나열한다.

    스테이지 1 은 4라운드(1-1~1-4)로 끝나고 2 부터는 7라운드다.

    Regression: 예전엔 전 스테이지를 7라운드로 봐서 ``(1,5)(1,6)(1,7)`` 같은
    존재하지 않는 라운드를 만들었고, ``base_income`` 은 ``base_income(1,5)=5`` 처럼
    그 라운드에도 기본 수입을 줬다.
    """
    stage, rnd = start
    out: list[tuple[int, int]] = []
    while len(out) < count:
        out.append((stage, rnd))
        rnd += 1
        if rnd > stage_length(stage):
            rnd = 1
            stage += 1
    return out


#: 전망/판정이 목표 라운드를 담을 수 있게 하는 최대 라운드 수. 초과하면 오류로 알린다.
#: (예전엔 이 검색 상한이 한 군데는 30, 다른 한 군데는 40으로 두 곳에 하드코딩돼 있었다.)
MAX_HORIZON = 40


def rounds_between(
    start: tuple[int, int], target: tuple[int, int], *, max_rounds: int = MAX_HORIZON
) -> int:
    """start -> target 까지의 라운드 수. 범위 밖(또는 과거)이면 ValueError.

    예전에는 못 찾으면 ``fallback`` 으로 조용히 대체했는데, 그 결과
    ``--target-round 11-1`` 로 지정해도 4-1~4-6 전망을 보고 판정을 읽는 오류가
    났다. 모르는 값은 모르다고 말하는 이 프로젝트의 원칙에 따라 오류로 바꿨다.
    """
    for index, item in enumerate(round_sequence(start, max_rounds), start=1):
        if item == target:
            return index
    raise ValueError(
        f"목표 라운드 {format_round(*target)} 가 현재 {format_round(*start)} 부터 "
        f"{max_rounds}라운드 안에 들어오지 않는다(범위 밖이거나 과거 라운드). "
        "--rounds 를 늘리거나 목표를 다시 확인하세요."
    )


def projection_horizon(
    start: tuple[int, int],
    target: tuple[int, int],
    rounds: int,
    *,
    max_rounds: int = MAX_HORIZON,
) -> int:
    """전망 길이: ``--rounds`` 와 목표 도달에 필요한 길이 중 큰 값.

    목표가 가까워도 ``--rounds`` 만큼은 보여주고, 멀면 목표까지 늘린다. 덕분에
    목표 기준 지표(생존확률·목표 시점 골드)가 항상 목표를 담는다.
    """
    return max(rounds, rounds_between(start, target, max_rounds=max_rounds))


class UnknownIncomeError(LookupError):
    """라운드 기본 수입을 출처에서 확인하지 못했다(추정 금지).

    ``odds.UnknownOddsError`` 와 같은 원칙: 모르는 값은 넣지 않고 예외로 멈춘다.
    1-1 에 기본 수입 5 를 넣어 둔 채 놔두면 1-1 부터 시작하는 전망이 과대 계산된다.
    """


def base_income(stage: int, rnd: int) -> int:
    """라운드 기본 수입(초반 램프업 포함).

    출처(tft.ninja economy)가 주는 값은 1-2 부터다. 그 앞인 1-1 은 문서에 없으므로
    **추정하지 않고** 예외를 던진다.
    """
    ramp = {(1, 2): 2, (1, 3): 2, (1, 4): 3, (2, 1): 4}
    if (stage, rnd) in ramp:
        return ramp[(stage, rnd)]
    if stage == 1:
        raise UnknownIncomeError(
            f"{format_round(stage, rnd)} 기본 수입을 출처(tft.ninja economy)에서 확인하지 "
            "못했다(출처는 1-2 부터다). 1-2 이후 라운드로 시작하거나, 확인한 값을 "
            "economy.base_income 의 ramp 에 추가하세요."
        )
    return 5


def streak_bonus(streak: int) -> int:
    """연승/연패 스트릭 골드. streak 는 절대값 기준(음수=연패)."""
    length = abs(streak)
    if length >= 6:
        return 3
    if length == 5:
        return 2
    if length >= 2:
        return 1
    return 0


def interest(gold: int, cap: int = 5) -> int:
    """이자: 10골드당 1, 최대 cap."""
    return min(cap, max(0, gold) // 10)


@dataclass
class LevelPlan:
    """'4-1에 7레벨' 같은 계획 한 줄."""

    round: tuple[int, int]
    target_level: int


def parse_level_plan(spec: str) -> list[LevelPlan]:
    """'4-1:7,4-5:8' -> [LevelPlan((4,1),7), LevelPlan((4,5),8)]"""
    plans: list[LevelPlan] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        round_text, _, level_text = chunk.partition(":")
        if not level_text:
            raise ValueError(f"레벨업 계획 형식 오류: '{chunk}' (예: 4-1:7)")
        plans.append(LevelPlan(parse_round(round_text), int(level_text)))
    return sorted(plans, key=lambda plan: plan.round)


@dataclass
class EconomyState:
    gold: int
    level: int
    streak: int = 0  # 양수=연승, 음수=연패
    stage: int = 3
    round: int = 5


@dataclass
class RoundProjection:
    stage: int
    round: int
    kind: str
    base: int
    interest_gold: int
    streak_gold: int
    win_gold: float
    pve_gold: int
    levelup_spend: int
    target_level: int
    gold_start: int
    gold_end: int

    @property
    def income(self) -> float:
        return (
            self.base
            + self.interest_gold
            + self.streak_gold
            + self.win_gold
            + self.pve_gold
        )

    @property
    def roll_budget(self) -> int:
        """이 라운드에서 롤/구매에 쓸 수 있는 골드(레벨업 비용 제외)."""
        return self.gold_start + int(self.income) - self.levelup_spend

    def as_dict(self) -> dict[str, object]:
        return {
            "round": format_round(self.stage, self.round),
            "type": self.kind,
            "base": self.base,
            "interest": self.interest_gold,
            "streak": self.streak_gold,
            "win_gold": round(self.win_gold, 2),
            "pve": self.pve_gold,
            "income": round(self.income, 2),
            "levelup_spend": self.levelup_spend,
            "level": self.target_level,
            "gold_start": self.gold_start,
            "gold_end": self.gold_end,
            "roll_budget": self.roll_budget,
        }


def levelup_cost(
    current_level: int,
    target_level: int,
    rounds_until: int,
    *,
    count_passive_xp: bool = True,
) -> int:
    """라운드가 흐르는 동안 쌓이는 패시브 XP를 반영한 레벨업 골드.

    XP 1 = 골드 1(set_data.GOLD_PER_XP), 라운드당 패시브 2 XP.
    """
    return set_data.level_up_gold(
        current_level,
        target_level,
        count_passive_xp=count_passive_xp,
        rounds=max(0, rounds_until),
    )


@dataclass
class Projection:
    rounds: list[RoundProjection] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def at(self, stage: int, rnd: int) -> RoundProjection | None:
        for row in self.rounds:
            if row.stage == stage and row.round == rnd:
                return row
        return None

    def summary(self) -> dict[str, object]:
        last = self.rounds[-1]
        return {
            "start": format_round(self.rounds[0].stage, self.rounds[0].round),
            "end": format_round(last.stage, last.round),
            "gold_end": last.gold_end,
            "level_end": last.target_level,
            "total_income": round(
                sum(row.income for row in self.rounds), 2
            ),
            "total_spend": sum(row.levelup_spend for row in self.rounds),
        }


def project(
    state: EconomyState,
    *,
    rounds: int,
    level_plans: list[LevelPlan] | None = None,
    extra_spends: dict[tuple[int, int], int] | None = None,
    win_rate: float = 0.5,
    pve_gold: int = DEFAULT_PVE_GOLD,
    streak_behavior: str = "hold",
) -> Projection:
    """앞으로 ``rounds`` 라운드의 골드/레벨/롤 예산을 계산한다.

    extra_spends : 특정 라운드에 레벨업 외로 쓰는 골드(예: ``{(4,1): 40}`` = 4-1에 40골드 롤다운).
        레벨업과 마찬가지로 **이자 계산 전에** 차감한다.

    streak_behavior
    * "hold": 스트릭 유지 가정(기본)
    * "reset": 매 라운드 스트릭 0(보수적)
    """
    plans = {plan.round: plan.target_level for plan in (level_plans or [])}
    spends = dict(extra_spends or {})
    sequence = round_sequence((state.stage, state.round), rounds)
    level = state.level
    gold = state.gold
    streak = state.streak
    win_carry = 0.0  # 승리 보너스 기대값의 소수 이월분(반올림 편향 방지)
    rows: list[RoundProjection] = []
    notes: list[str] = []

    if streak_behavior not in {"hold", "reset"}:
        raise ValueError("streak_behavior 는 'hold' 또는 'reset' 이어야 합니다.")
    if streak_behavior == "reset":
        notes.append("스트릭을 매 라운드 0으로 가정(보수적)")
    else:
        notes.append(f"스트릭 {streak:+d} 유지 가정")
    notes.append(
        f"승리 보너스는 기대값(승률 {win_rate:.0%} x 1골드). 실제로는 이기면 +1, 지면 +0"
        " — 라운드마다 반올림하면 편향이 생기므로 소수를 이월(carry)해 정수분만 지급한다"
    )
    notes.append(f"PvE 라운드 골드 {pve_gold} 가정(공개 수치 아님)")

    for index, (stage, rnd) in enumerate(sequence):
        kind = round_type(stage, rnd)
        gold_start = gold
        target_level = plans.get((stage, rnd), level)
        spend = 0
        if target_level > level:
            # 이 라운드까지 흐른 라운드 수로 패시브 XP 반영
            spend = levelup_cost(level, target_level, index, count_passive_xp=True)
            gold = max(0, gold - spend)
            level = target_level
        extra = int(spends.get((stage, rnd), 0))
        if extra:
            gold = max(0, gold - extra)

        gained_base = base_income(stage, rnd)
        gold_before_interest = gold + gained_base
        interest_gold = interest(gold_before_interest)
        streak_gold = streak_bonus(streak) if streak_behavior == "hold" else 0
        win_expected = win_rate if kind == PVP else 0.0
        # round(0.5) 는 은행원 반올림이라 0 이 된다. 그래서 기본 승률 50% 에서
        # 승리 보너스가 통째로 사라졌다. 기대값의 소수를 이월해 정수분만 지급한다.
        # 이렇게 하면 income(프로퍼티)과 gold_end 가 어긋나지 않는다.
        win_carry += win_expected
        win_gold = float(int(win_carry))
        win_carry -= win_gold
        # 캐러셀 라운드는 승리 보너스 없음, PvE 는 오브에서 골드
        pve_round_gold = pve_gold if kind == PVE else 0
        gold_end = int(
            gold_before_interest + interest_gold + streak_gold + win_gold + pve_round_gold
        )
        rows.append(
            RoundProjection(
                stage=stage,
                round=rnd,
                kind=kind,
                base=gained_base,
                interest_gold=interest_gold,
                streak_gold=streak_gold,
                win_gold=win_gold,
                pve_gold=pve_round_gold,
                levelup_spend=spend,
                target_level=level,
                gold_start=gold_start,
                gold_end=gold_end,
            )
        )
        gold = gold_end
        if streak_behavior == "hold" and kind == PVP:
            streak = streak + 1 if streak > 0 else streak - 1 if streak < 0 else 1

    return Projection(rounds=rows, notes=notes)
