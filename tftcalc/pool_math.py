"""풀 고갈을 반영한 확률/기대 골드 계산 (검증 가능한 수학 파트).

표준 TFT 상점 모델
------------------
1. 상점은 5칸, 각 칸은 독립적으로 굴린다.
2. 한 칸: 먼저 레벨별 확률로 코스트 등급이 결정되고, 그 등급의 '남은 사본'에서 균등 추출.
3. 따라서 특정 기물 1칸 확률 =:

       p_slot = cost_odds(level, cost) * (남은_대상_사본 / 해당_코스트_등급_남은_사본_총합)

4. 상점 1회 = 2골드.

명시된 한계 (README 에도 동일하게 기재)
--------------------------------------
* 다른 플레이어가 내가 롤링하는 동안 사본을 가져가는 효과는 반영하지 않는다.
* 라운드마다 주어지는 무료 상점은 제외한 보수적 계산이다.
* 같은 상점 안에 동일 기물이 중복 등장하는 것은 허용한다(실제 게임과 동일).
* 해석해는 '다음 한 장' 근사이고, 구매로 인한 풀 감소는 몬테카를로가 반영한다.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from . import set_data
from .odds import ShopOdds
from .trials import HEAVY, STANDARD


# --------------------------------------------------------------------------
# 풀 상태
# --------------------------------------------------------------------------
def remaining_tier_copies(cost: int, copies_in_play_in_tier: int) -> int:
    """코스트 등급의 남은 사본 총합."""
    tier = set_data.TIER_POOLS[cost]
    return max(0, tier.total_copies - copies_in_play_in_tier)


def remaining_target_copies(cost: int, copies_of_target_in_play: int) -> int:
    """대상 기물 1종의 남은 사본 수."""
    tier = set_data.TIER_POOLS[cost]
    return max(0, tier.copies_per_champion - copies_of_target_in_play)


# --------------------------------------------------------------------------
# 확률 (해석해)
# --------------------------------------------------------------------------
def p_slot_is_target(cost_odds: float, remaining_target: int, remaining_tier: int) -> float:
    """상점 한 칸이 특정 기물일 확률."""
    if remaining_target <= 0 or remaining_tier <= 0:
        return 0.0
    return cost_odds * (remaining_target / remaining_tier)


def p_shop_at_least_one(p_slot: float) -> float:
    """상점 1회(5칸)에서 최소 한 장 볼 확률."""
    return 1.0 - (1.0 - p_slot) ** set_data.SHOP_SLOTS


def p_at_least_one_in_shops(p_slot: float, shops: int) -> float:
    """상점 `shops` 회에서 최소 한 장 볼 확률 (상점 간 독립 가정)."""
    if shops <= 0:
        return 0.0
    return 1.0 - (1.0 - p_shop_at_least_one(p_slot)) ** shops


def shops_for_gold(gold: int) -> int:
    """골드로 돌릴 수 있는 상점 횟수."""
    return max(0, gold // set_data.ROLL_COST_GOLD)


def gold_for_shops(shops: int) -> int:
    return shops * set_data.ROLL_COST_GOLD


def expected_roll_gold_for_next_copy(p_slot: float) -> float:
    """다음 한 장을 보기까지의 기대 리롤 비용(골드).

    상점 성공확률 p 에 대해 기하분포 기대 시행 횟수 1/p, 상점 1회 2골드.
    (공개된 'ereklo 표'의 2*(1-(1-X/N)^5)^-1 과 같은 식이다.)
    """
    p_shop = p_shop_at_least_one(p_slot)
    if p_shop <= 0.0:
        return float("inf")
    return set_data.ROLL_COST_GOLD / p_shop


def expected_gold_first_copy(
    odds: ShopOdds,
    *,
    level: int,
    cost: int,
    remaining_target: int,
    remaining_tier: int,
) -> dict[str, float]:
    """(해석해) 대상 한 장을 처음 보기까지 필요한 기대 리롤 골드."""
    cost_odds = odds.cost_odds(level, cost)
    p_slot = p_slot_is_target(cost_odds, remaining_target, remaining_tier)
    return {
        "p_slot": p_slot,
        "p_shop": p_shop_at_least_one(p_slot),
        "expected_roll_gold": expected_roll_gold_for_next_copy(p_slot),
        "shops_for_80pct": _shops_for_probability(p_slot, 0.8),
    }


def _shops_for_probability(p_slot: float, target: float) -> int:
    """상점 간 독립 가정으로 목표 확률 도달에 필요한 상점 횟수(해석해)."""
    p_shop = p_shop_at_least_one(p_slot)
    if p_shop <= 0.0:
        return -1
    if p_shop >= 1.0:
        return 1
    return int(math.ceil(math.log(1.0 - target) / math.log(1.0 - p_shop)))


# --------------------------------------------------------------------------
# 몬테카를로: 실제 롤다운 (구매로 인한 풀 감소 + 골드 한계 반영)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class RollDownResult:
    trials: int
    level: int
    unit_cost: int
    need: int
    budget: int
    p_complete: float
    mean_total_gold: float
    mean_roll_gold: float
    mean_purchase_gold: float
    mean_shops: float
    mean_gold_on_success: float | None
    pool_exhausted_rate: float
    impossible: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "level": self.level,
            "unit_cost": self.unit_cost,
            "need": self.need,
            "budget": self.budget,
            "p_complete": round(self.p_complete, 4),
            "mean_total_gold": round(self.mean_total_gold, 2),
            "mean_roll_gold": round(self.mean_roll_gold, 2),
            "mean_purchase_gold": round(self.mean_purchase_gold, 2),
            "mean_shops": round(self.mean_shops, 2),
            "mean_gold_on_success": (
                round(self.mean_gold_on_success, 2)
                if self.mean_gold_on_success is not None
                else None
            ),
            "pool_exhausted_rate": round(self.pool_exhausted_rate, 4),
            "impossible": self.impossible,
        }


def _draw_hits(rng: random.Random, p_slot: float) -> int:
    """상점 5칸 중 대상이 뜬 칸 수 (이항분포 샘플)."""
    if p_slot <= 0.0:
        return 0
    if p_slot >= 1.0:
        return set_data.SHOP_SLOTS
    if hasattr(rng, "binomialvariate"):  # Python 3.12+
        return int(rng.binomialvariate(set_data.SHOP_SLOTS, p_slot))
    return sum(
        1 for _ in range(set_data.SHOP_SLOTS) if rng.random() < p_slot
    )


def simulate_roll_down(
    odds: ShopOdds,
    *,
    level: int,
    unit_cost: int,
    remaining_target: int,
    remaining_tier: int,
    need: int,
    budget: int,
    trials: int = HEAVY,
    seed: int = 1234,
) -> RollDownResult:
    """`budget` 골드로 `need` 장을 모을 확률과 기대 소모 골드를 시뮬레이션한다.

    need : 더 모아야 하는 사본 수 (2성까지 3장 중 1장 보유면 2).
    budget : 리롤 + 구매에 쓸 수 있는 총 골드.
    """
    if need <= 0:
        raise ValueError("need 는 1 이상이어야 합니다.")
    if budget < 0 or remaining_target < 0 or remaining_tier < 0:
        raise ValueError("budget/remaining_* 는 음수일 수 없습니다.")

    if remaining_target < need:
        # 풀에 남은 사본이 필요한 장수보다 적다: 예산과 무관하게 '구조적으로' 불가.
        # (상대가 팔거나 탈락해 풀에 반환되면 그때 다시 계산해야 한다.)
        return RollDownResult(
            trials=trials,
            level=level,
            unit_cost=unit_cost,
            need=need,
            budget=budget,
            p_complete=0.0,
            mean_total_gold=0.0,
            mean_roll_gold=0.0,
            mean_purchase_gold=0.0,
            mean_shops=0.0,
            mean_gold_on_success=None,
            pool_exhausted_rate=1.0,
            impossible=True,
        )

    cost_odds = odds.cost_odds(level, unit_cost)

    successes = 0
    sum_total = sum_roll = sum_buy = sum_shops = sum_on_success = 0.0
    pool_exhausted = 0
    rng = random.Random(seed)

    for _ in range(trials):
        copies_left = remaining_target
        tier_left = remaining_tier
        bought = spent = roll_spent = buy_spent = shops = 0

        while (
            bought < need
            and copies_left > 0
            and spent + set_data.ROLL_COST_GOLD <= budget
        ):
            spent += set_data.ROLL_COST_GOLD
            roll_spent += set_data.ROLL_COST_GOLD
            shops += 1

            p_slot = cost_odds * (copies_left / tier_left) if tier_left > 0 else 0.0
            hits = _draw_hits(rng, p_slot)
            if hits > 0:
                hits = min(hits, need - bought, copies_left)
                affordable = (budget - spent) // unit_cost
                take = min(hits, affordable)
                if take > 0:
                    spent += take * unit_cost
                    buy_spent += take * unit_cost
                    bought += take
                    copies_left -= take
                    tier_left -= take

        if bought >= need:
            successes += 1
            sum_on_success += spent
        elif copies_left == 0:
            pool_exhausted += 1

        sum_total += spent
        sum_roll += roll_spent
        sum_buy += buy_spent
        sum_shops += shops

    return RollDownResult(
        trials=trials,
        level=level,
        unit_cost=unit_cost,
        need=need,
        budget=budget,
        p_complete=successes / trials,
        mean_total_gold=sum_total / trials,
        mean_roll_gold=sum_roll / trials,
        mean_purchase_gold=sum_buy / trials,
        mean_shops=sum_shops / trials,
        mean_gold_on_success=(sum_on_success / successes if successes else None),
        pool_exhausted_rate=pool_exhausted / trials,
    )


def gold_needed_for_probability(
    odds: ShopOdds,
    *,
    level: int,
    unit_cost: int,
    remaining_target: int,
    remaining_tier: int,
    need: int,
    target_probability: float = 0.8,
    max_budget: int = 200,
    trials: int = STANDARD,
    seed: int = 99,
) -> tuple[int, float]:
    """목표 확률을 처음 넘기는 최소 골드 예산을 찾는다.

    선형 스캔(0..max_budget = 201회 평가) 대신 **이진 탐색**으로 약 8회만 평가한다.

    전제: ``p_complete`` 은 예산에 대해 단조(비내림). 같은 seed 로 예산 0~200 을
    5골드 간격(41표본)으로 실측한 결과 **비단조 지점은 0건**이었다(2026-09-23).
    그래도 전제가 깨지는 경우를 막기 위해, 이진 탐색이 찾은 경계에서 왼쪽으로 한 칸씩
    되짚어 진짜 첫 교차점을 확정한다(정상적이면 0회, 최악이면 선형과 같음).

    Returns
    -------
    (gold, probability) : 예산과 그 때의 실제 확률. 도달 못하면 (max_budget, 마지막 확률).
    """
    cache: dict[int, float] = {}

    def evaluate(gold: int) -> float:
        if gold not in cache:
            cache[gold] = simulate_roll_down(
                odds,
                level=level,
                unit_cost=unit_cost,
                remaining_target=remaining_target,
                remaining_tier=remaining_tier,
                need=need,
                budget=gold,
                trials=trials,
                seed=seed,
            ).p_complete
        return cache[gold]

    top = evaluate(max_budget)
    if top < target_probability:
        return max_budget, top

    low, high = 0, max_budget
    while low < high:
        mid = (low + high) // 2
        if evaluate(mid) >= target_probability:
            high = mid
        else:
            low = mid + 1
    # 단조 가정이 깨져도 진짜 첫 교차점을 찾도록 왼쪽을 재확인한다.
    while low > 0 and evaluate(low - 1) >= target_probability:
        low -= 1
    return low, evaluate(low)

