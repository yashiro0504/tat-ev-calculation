"""커밋(리롤) vs 전환(밸류) 판정.

설계 원칙
--------
'리롤 유지 확률 28% / 전환 확률 72%' 같은 단일 숫자를 만들지 않는다.
그 숫자는 (a) 이기종 단위(피통 + 골드 - 기회비용)를 더한 차원 오류에서 나오고,
(b) 실측 캘리브레이션이 없으면 과학이 아니라 연출이다. 그리고 Riot 정책은
'게임 결정을 제거하는' 제품을 문제 삼는다.

대신 두 가지를 낸다.
1) unit_cost_report(): 기물 하나를 2성/3성까지 올리는 비용을 확률로 계산 (검증된 수학).
2) compare_lines(): 두 라인의 (완성 확률, 기대 골드) 비교.
   - 한쪽이 '확률 높고 기대 골드 낮음'이면 지배 관계 -> 그 근거만으로 결론.
   - 아니면 트레이드오프가 있다고 말하고, 판단에 필요한 누락 정보를 나열한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import pool_math, set_data
from .lobby import LobbySnapshot
from .odds import ShopOdds

HEURISTIC_DISCLAIMER = (
    "보드 파워/증강 상성/메타는 이 모듈이 계산하지 않는다. "
    "그 값들은 실측 캘리브레이션이 필요하며, 없는 척하면 도구가 거짓말을 하게 된다."
)


@dataclass(frozen=True)
class RollLine:
    """롤다운 라인 하나의 입력 조건."""

    name: str
    level: int
    unit_cost: int
    remaining_target: int
    remaining_tier: int
    need: int
    budget: int


def unit_cost_report(
    odds: ShopOdds,
    *,
    level: int,
    cost: int,
    copies_of_target_in_play: int,
    copies_in_play_of_tier: int,
    own_copies: int,
    target_star: int = 2,
    budget: int = 60,
    trials: int = 4_000,
    seed: int = 1234,
) -> dict[str, object]:
    """기물 1종을 목표 성급까지 올리는 비용 리포트 (파트 1 의 핵심 출력)."""
    required = set_data.STAR_COPY_WEIGHTS[target_star]
    need = max(0, required - own_copies)
    remaining_target = pool_math.remaining_target_copies(cost, copies_of_target_in_play)
    remaining_tier = pool_math.remaining_tier_copies(cost, copies_in_play_of_tier)
    analytic = pool_math.expected_gold_first_copy(
        odds,
        level=level,
        cost=cost,
        remaining_target=remaining_target,
        remaining_tier=remaining_tier,
    )

    report: dict[str, object] = {
        "level": level,
        "cost": cost,
        "target_star": target_star,
        "own_copies": own_copies,
        "need": need,
        "pool_per_champion": set_data.TIER_POOLS[cost].copies_per_champion,
        "remaining_target": remaining_target,
        "remaining_tier": remaining_tier,
        "impossible": remaining_target < need,
        "p_slot": analytic["p_slot"],
        "p_shop": analytic["p_shop"],
        "expected_roll_gold_next_copy": analytic["expected_roll_gold"],
        "shops_for_80pct_one_copy": analytic["shops_for_80pct"],
    }

    if need == 0:
        report["verdict"] = "이미 목표 성급 완성"
        return report
    if remaining_target == 0:
        report["verdict"] = "풀에 사본이 없다. 확률 0%. 즉시 라인 전환 검토."
        return report
    if remaining_target < need:
        report["verdict"] = (
            f"풀에 남은 사본({remaining_target})이 필요한 장수({need})보다 적다. "
            "지금 상태로는 수학적으로 완성 불가. "
            "상대가 팔거나 탈락해 풀에 반환될 때 확률이 다시 열린다."
        )
        return report

    simulation = pool_math.simulate_roll_down(
        odds,
        level=level,
        unit_cost=cost,
        remaining_target=remaining_target,
        remaining_tier=remaining_tier,
        need=need,
        budget=budget,
        trials=trials,
        seed=seed,
    )
    report["roll_down"] = simulation.as_dict()
    report["gold_for_80pct"] = pool_math.gold_needed_for_probability(
        odds,
        level=level,
        unit_cost=cost,
        remaining_target=remaining_target,
        remaining_tier=remaining_tier,
        need=need,
        target_probability=0.8,
        max_budget=budget,
        trials=max(600, trials // 5),
        seed=seed,
    )[0]
    return report


@dataclass(frozen=True)
class Comparison:
    """두 라인 비교 결과."""

    line_a: str
    line_b: str
    p_a: float
    p_b: float
    gold_a: float
    gold_b: float
    dominated: bool
    preferred: str | None
    reason: str
    missing_inputs: list[str]


def compare_lines(
    odds: ShopOdds,
    a: RollLine,
    b: RollLine,
    *,
    trials: int = 4_000,
    seed: int = 7,
) -> Comparison:
    """두 라인을 (완성 확률, 기대 골드)로 비교한다.

    확률적 지배(한쪽이 확률도 높고 기대 골드도 낮음)일 때만 결론을 낸다.
    그 외에는 트레이드오프를 보고하고, 결론에 필요한 정보를 나열한다.
    """
    result_a = pool_math.simulate_roll_down(
        odds,
        level=a.level,
        unit_cost=a.unit_cost,
        remaining_target=a.remaining_target,
        remaining_tier=a.remaining_tier,
        need=a.need,
        budget=a.budget,
        trials=trials,
        seed=seed,
    )
    result_b = pool_math.simulate_roll_down(
        odds,
        level=b.level,
        unit_cost=b.unit_cost,
        remaining_target=b.remaining_target,
        remaining_tier=b.remaining_tier,
        need=b.need,
        budget=b.budget,
        trials=trials,
        seed=seed + 1,
    )

    a_prob_at_least = result_a.p_complete >= result_b.p_complete
    a_gold_at_most = result_a.mean_total_gold <= result_b.mean_total_gold
    identical = (result_a.p_complete == result_b.p_complete) and (
        result_a.mean_total_gold == result_b.mean_total_gold
    )

    if result_a.impossible and result_b.impossible:
        dominated, preferred = False, None
        reason = "두 라인 모두 풀에 사본이 부족하다(구조적 불가). 라인 자체를 다시 짜야 한다."
    elif result_a.impossible:
        dominated, preferred = True, b.name
        reason = f"{a.name}: 풀에 남은 사본이 부족해 완성 불가. {b.name} 만 유효하다."
    elif result_b.impossible:
        dominated, preferred = True, a.name
        reason = f"{b.name}: 풀에 남은 사본이 부족해 완성 불가. {a.name} 만 유효하다."
    elif identical:
        dominated, preferred = False, None
        reason = "완성 확률과 기대 골드가 동률이다. 판단에는 보드 파워 축이 더 필요하다."
    elif result_a.p_complete == result_b.p_complete:
        dominated = True
        preferred = a.name if a_gold_at_most else b.name
        reason = f"완성 확률은 동률이다. 기대 골드가 낮은 {preferred} 가 유리하다."
    elif result_a.mean_total_gold == result_b.mean_total_gold:
        dominated = True
        preferred = a.name if a_prob_at_least else b.name
        reason = f"기대 골드는 동률이다. 완성 확률이 높은 {preferred} 가 유리하다."
    elif a_prob_at_least and a_gold_at_most:
        dominated, preferred = True, a.name
        reason = f"{a.name}: 완성 확률이 더 높고 기대 골드는 더 낮다(확률적 지배)."
    elif (not a_prob_at_least) and (not a_gold_at_most):
        dominated, preferred = True, b.name
        reason = f"{b.name}: 완성 확률이 더 높고 기대 골드는 더 낮다(확률적 지배)."
    else:
        dominated, preferred = False, None
        higher = a.name if a_prob_at_least else b.name
        cheaper = a.name if a_gold_at_most else b.name
        reason = (
            f"{higher} 는 완성 확률이 앞서고 {cheaper} 는 기대 골드가 낮다. "
            "확률/골드 트레이드오프이므로 '골드 1당 보드 전투력' 환산이 있어야 결론이 난다."
        )

    if not dominated:
        reason = (
            reason
            + " "
            + f"(확률 {result_a.p_complete * 100:.1f}% vs {result_b.p_complete * 100:.1f}%, "
            f"기대 골드 {result_a.mean_total_gold:.1f} vs {result_b.mean_total_gold:.1f})"
        )

    return Comparison(
        line_a=a.name,
        line_b=b.name,
        p_a=result_a.p_complete,
        p_b=result_b.p_complete,
        gold_a=result_a.mean_total_gold,
        gold_b=result_b.mean_total_gold,
        dominated=dominated,
        preferred=preferred,
        reason=reason,
        missing_inputs=[
            "완성 시점 이후의 보드 전투력 차이(실측 필요)",
            "상대 증강/템포 정보(정책상 표시 제약 확인 필요)",
            "남은 라운드 수(HP 손실 기대값)",
        ],
    )


def robustness_scan(
    odds: ShopOdds,
    *,
    level: int,
    unit_cost: int,
    own_copies: int,
    others_copies: int,
    tolerance: int = 1,
    target_star: int = 2,
    budget: int = 60,
    commit_threshold: float = 0.5,
    trials: int = 3_000,
    seed: int = 17,
) -> dict[str, object]:
    """상대 보유 카운트의 오차(±tolerance장)가 결론을 뒤집는지 검사한다.

    왜 필요한가: 인식(CV/GEP)이든 수동 입력이든 **오차는 반드시 존재**한다.
    오차를 없앨 수는 없으므로, 대신 '그 오차가 결론을 바꾸는가'를 계산해서
    바뀌면 사용자에게 추가 확인을 요구한다. 이것이 가짜 정밀도를 막는 장치다.

    commit_threshold 는 **표시 규칙**이다(과학적 상수가 아니다):
    예산 내 완성 확률이 이 값 미만이면 '전환 검토'로 표시한다.
    """
    cost_odds = odds.cost_odds(level, unit_cost)  # 확률표를 모르면 여기서 멈춘다
    need = max(0, set_data.STAR_COPY_WEIGHTS[target_star] - own_copies)
    rows: list[dict[str, object]] = []

    for others in range(
        max(0, others_copies - tolerance), others_copies + tolerance + 1
    ):
        copies_in_play = own_copies + others
        remaining_target = pool_math.remaining_target_copies(unit_cost, copies_in_play)
        remaining_tier = pool_math.remaining_tier_copies(unit_cost, copies_in_play)
        p_slot = pool_math.p_slot_is_target(cost_odds, remaining_target, remaining_tier)
        row: dict[str, object] = {
            "others": others,
            "remaining_target": remaining_target,
            "p_shop": pool_math.p_shop_at_least_one(p_slot),
        }

        if need == 0:
            row.update(p_complete=0.0, mean_total_gold=0.0, verdict="이미 완성")
        elif remaining_target < need:
            row.update(p_complete=0.0, mean_total_gold=0.0, verdict="불가(풀 부족)")
        else:
            result = pool_math.simulate_roll_down(
                odds,
                level=level,
                unit_cost=unit_cost,
                remaining_target=remaining_target,
                remaining_tier=remaining_tier,
                need=need,
                budget=budget,
                trials=trials,
                seed=seed,
            )
            row.update(
                p_complete=result.p_complete,
                mean_total_gold=result.mean_total_gold,
                verdict=(
                    "롤다운"
                    if result.p_complete >= commit_threshold
                    else "전환 검토"
                ),
            )
        rows.append(row)

    verdicts = sorted({str(row["verdict"]) for row in rows})
    return {
        "rows": rows,
        "stable": len(verdicts) == 1,
        "verdicts": verdicts,
        "tolerance": tolerance,
        "commit_threshold": commit_threshold,
    }


def lobby_confidence(snapshot: LobbySnapshot) -> str:
    """스냅샷 신뢰도 문구. 숫자와 함께 항상 사용자에게 노출한다."""
    return snapshot.confidence_note()
