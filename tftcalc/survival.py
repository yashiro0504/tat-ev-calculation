"""체력/피해(생존) 축.

목적: "지금 세이빙을 N라운드 더 하면 죽을 확률이 얼마인가?" 를 계산해서
**리롤 vs 전환**을 체력 리스크까지 포함해 판단할 수 있게 한다.

피해 공식 (출처: tft.ninja player-damage-calculation, 패치 18.1)
--------------------------------------------------------------
    총 피해 = 스테이지 기본 피해 + 살아남은 상대 유닛 수

* 살아남은 유닛은 성급/코스트와 무관하게 **1개당 1 피해**
* 스테이지 기본 피해: 1=0, 2=2, 3=5, 4=8, 5=10, 6=12, 7+=17
* 시작 체력 100, 일반적으로 회복 수단 없음
* 문서 예시: 3스테이지 5유닛=10, 4스테이지 6유닛=14, 6스테이지 9유닛=21, 7스테이지 9유닛=26

가정 (명시)
----------
* PvE/캐러셀 라운드는 체력 피해가 없다고 본다(``pve_damage`` 기본 0).
* 패배 시 남는 상대 유닛 수는 평균 ``enemy_survivors`` 의 정규분포로 흉내낸다.
* 승률 ``win_rate`` 는 사용자가 준다(보드 강함/약함에 따라 달라지는 값).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import economy

STARTING_HP = 100

#: 스테이지별 기본 피해 (패치 18.1)
DAMAGE_BASE_BY_STAGE: dict[int, int] = {1: 0, 2: 2, 3: 5, 4: 8, 5: 10, 6: 12}
MAX_STAGE_DAMAGE = 17  # 7스테이지 이상


def base_damage(stage: int) -> int:
    """스테이지 기본 피해."""
    if stage >= 7:
        return MAX_STAGE_DAMAGE
    return DAMAGE_BASE_BY_STAGE.get(stage, 0)


def round_damage(stage: int, surviving_units: int) -> int:
    """총 피해 = 기본 + 살아남은 상대 유닛 수."""
    return base_damage(stage) + max(0, int(surviving_units))


def losses_survivable(hp: int, stage: int, *, enemy_survivors: int) -> int:
    """지금 체력으로 '몇 번 더 질 수 있는가'(결정론적 근사).

    문서의 경험칙과 같은 계산(내림): 60HP/4스테이지(15피해) -> 4회,
    40HP/5스테이지(18피해) -> 2회, 25HP/6스테이지(20피해) -> 1회.
    체력이 정확히 0이 되는 횟수도 포함해 세는 근사임에 유의.
    """
    per_loss = round_damage(stage, enemy_survivors)
    if per_loss <= 0:
        return 10**6
    return max(0, hp // per_loss)


@dataclass
class RoundSurvival:
    stage: int
    round: int
    kind: str
    base: int
    expected_survivors: float
    expected_damage: float
    expected_hp: float
    p_alive: float
    deaths_this_round: float

    def as_dict(self) -> dict[str, object]:
        return {
            "round": economy.format_round(self.stage, self.round),
            "type": self.kind,
            "base_damage": self.base,
            "expected_survivors": round(self.expected_survivors, 2),
            "expected_damage": round(self.expected_damage, 2),
            "expected_hp": round(self.expected_hp, 2),
            "p_alive": round(self.p_alive, 4),
            "deaths_this_round": round(self.deaths_this_round, 4),
        }


@dataclass
class SurvivalResult:
    hp: int
    rounds: list[RoundSurvival] = field(default_factory=list)
    trials: int = 0
    expected_death_round: str | None = None
    notes: list[str] = field(default_factory=list)

    def p_alive_at(self, stage: int, rnd: int) -> float | None:
        for row in self.rounds:
            if row.stage == stage and row.round == rnd:
                return row.p_alive
        return None

    def summary(self) -> dict[str, object]:
        last = self.rounds[-1]
        return {
            "start_hp": self.hp,
            "end_round": economy.format_round(last.stage, last.round),
            "p_alive_end": round(last.p_alive, 4),
            "expected_hp_end": round(last.expected_hp, 2),
            "expected_death_round": self.expected_death_round,
            "trials": self.trials,
        }


def simulate_survival(
    hp: int,
    start: tuple[int, int],
    *,
    rounds: int,
    win_rate: float,
    enemy_survivors: float = 8.0,
    survivors_sd: float = 2.0,
    pve_damage: int = 0,
    trials: int = 20_000,
    seed: int = 11,
) -> SurvivalResult:
    """앞으로 ``rounds`` 라운드 동안의 생존 확률/기대 체력을 시뮬레이션한다."""
    if not 0.0 <= win_rate <= 1.0:
        raise ValueError("win_rate 는 0~1 이어야 합니다.")
    sequence = economy.round_sequence(start, rounds)
    rng = random.Random(seed)
    alive = [True] * trials
    current_hp = [float(hp)] * trials
    death_index: list[int | None] = [None] * trials
    rows: list[RoundSurvival] = []

    for index, (stage, rnd) in enumerate(sequence):
        kind = economy.round_type(stage, rnd)
        base = base_damage(stage)
        damage_sum = 0.0
        survivors_sum = 0.0
        deaths_here = 0
        alive_at_start = 0
        hp_sum = 0.0
        for trial in range(trials):
            if not alive[trial]:
                continue
            alive_at_start += 1
            damage = 0.0
            survivors = 0.0
            if kind == economy.PVP:
                if rng.random() >= win_rate:  # 패배
                    survivors = max(0.0, rng.gauss(enemy_survivors, survivors_sd))
                    damage = base + survivors
            else:
                damage = float(pve_damage)
            current_hp[trial] = max(0.0, current_hp[trial] - damage)
            damage_sum += damage
            survivors_sum += survivors
            if current_hp[trial] <= 0:
                alive[trial] = False
                death_index[trial] = index
                deaths_here += 1
            else:
                hp_sum += current_hp[trial]

        alive_count = sum(1 for flag in alive if flag)
        rows.append(
            RoundSurvival(
                stage=stage,
                round=rnd,
                kind=kind,
                base=base,
                expected_survivors=(
                    survivors_sum / alive_at_start if alive_at_start else 0.0
                ),
                expected_damage=(damage_sum / alive_at_start if alive_at_start else 0.0),
                expected_hp=(hp_sum / alive_count if alive_count else 0.0),
                p_alive=alive_count / trials,
                deaths_this_round=deaths_here / trials,
            )
        )

    deaths = [index for index in death_index if index is not None]
    expected_death_round = None
    if deaths:
        average = sum(deaths) / len(deaths)
        stage, rnd = sequence[min(len(sequence) - 1, int(round(average)))]
        expected_death_round = economy.format_round(stage, rnd)

    notes = [
        "피해 공식: 스테이지 기본 피해 + 살아남은 상대 유닛 수(1개=1, 성급 무관)",
        f"패배 시 상대 잔존 유닛 평균 {enemy_survivors:.1f}(표준편차 {survivors_sd:.1f}) 가정",
        f"승률 {win_rate:.0%} 가정(PvP 라운드만 피해)",
        f"PvE/캐러셀 라운드 피해 {pve_damage} 가정",
    ]
    return SurvivalResult(
        hp=hp,
        rounds=rows,
        trials=trials,
        expected_death_round=expected_death_round,
        notes=notes,
    )


@dataclass
class StrategyOutcome:
    """전략 하나의 결과: (생존 확률, 목표 라운드 골드)."""

    name: str
    win_rate: float
    spend_now: int
    p_survive: float
    expected_hp: float
    gold_at_target: int
    note: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "win_rate": self.win_rate,
            "spend_now": self.spend_now,
            "p_survive": round(self.p_survive, 4),
            "expected_hp": round(self.expected_hp, 2),
            "gold_at_target": self.gold_at_target,
            "note": self.note,
        }


@dataclass
class StrategyComparison:
    outcomes: list[StrategyOutcome]
    verdict: str
    exchange: str
    missing_inputs: list[str] = field(default_factory=list)


def compare_stabilize_vs_save(
    *,
    save: StrategyOutcome,
    stabilize: StrategyOutcome,
) -> StrategyComparison:
    """세이빙 vs 지금 안정화(롤) 두 전략을 (생존확률, 골드) 두 축으로 비교한다.

    원칙: 한쪽이 **두 축 모두** 우세할 때만 결론을 낸다(확률적 지배).
    아니면 트레이드오프와 교환비율을 사실대로 제시한다.
    """
    better_survival = stabilize.p_survive - save.p_survive
    gold_cost = save.gold_at_target - stabilize.gold_at_target
    if better_survival > 0 and gold_cost <= 0:
        verdict = f"{stabilize.name}: 생존확률이 더 높고 골드도 더 많다(지배)."
    elif better_survival <= 0 and gold_cost >= 0:
        verdict = f"{save.name}: 생존확률이 더 높거나 같고 골드도 더 많다(지배)."
    else:
        verdict = (
            f"트레이드오프: {stabilize.name} 는 생존확률 {better_survival * 100:+.1f}%p, "
            f"대신 목표 라운드 골드가 {gold_cost:.0f}골드 적다."
        )
    if gold_cost > 0 and better_survival > 0:
        exchange = (
            f"교환비율: 생존확률 1%p 당 {gold_cost / (better_survival * 100):.1f}골드"
        )
    elif gold_cost <= 0:
        exchange = "골드 비용 없음"
    else:
        exchange = "생존확률 이득 없음(골드만 소비)"
    return StrategyComparison(
        outcomes=[save, stabilize],
        verdict=verdict,
        exchange=exchange,
        missing_inputs=[
            "롤 후 실제 승률 변화(경험치 필요: 롤 전/후 승률 기록)",
            "남은 상대 보드 강도(스카우팅 정확도)",
            "증강/수호령으로 인한 추가 골드·체력 효과",
        ],
    )

