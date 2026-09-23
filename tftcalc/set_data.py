"""정적 게임 데이터 (Set 18 "Enchanted Wilds" 기준, 2026-08 확인).

출처
----
* 풀 사이즈: tft.ninja "Champion Pool Math (Set 18)" 및 "The Shop" / "Champion Pool"
  - 1코 30 / 2코 25 / 3코 18 / 4코 10 / 5코 9 (챔피언 1종당 사본 수)
  - 3코는 같은 자료에서 "21 -> 18로 감소" 언급이 있어 패치마다 재확인 필요
* 리롤 2골드, 상점 5칸: tft.ninja "The Shop"
* 레벨 8에서 4코 확률 30% (Set 17에서 22% -> 30% 상향, Set 18 유지): tft.ninja "Champion Pool Math (Set 18)"
* 레벨 10에서 5코 25%, 레벨 11에서 5코 35%: tft.ninja "The Shop"

왜 '전체 확률표'를 하드코딩하지 않는가
-------------------------------------
레벨별 상점 확률표는 패치마다 바뀌며, 위 출처들도 전체 표를 텍스트로 안정적으로
제공하지 않는다. 없는 값을 그럴듯하게 채우면 계산기가 '정확한 척하는 거짓말'이 된다.
따라서 이 모듈은 **문서로 인용 가능한 셀만** VERIFIED_SHOP_ODDS 에 넣고,
나머지는 data/set18_shop_odds.json 으로 주입받는다(odds.ShopOdds.cost_odds 가
모르는 셀에서 UnknownOddsError 를 던진다).
"""

from __future__ import annotations

from dataclasses import dataclass

SET_NAME = "Set 18 (Enchanted Wilds)"
DATA_VERIFIED_ON = "2026-08"


@dataclass(frozen=True)
class TierPool:
    """코스트 등급 하나의 풀 정보."""

    cost: int
    copies_per_champion: int
    champions_in_tier: int

    @property
    def total_copies(self) -> int:
        """해당 코스트 등급 전체 사본 수 (모든 챔피언 합)."""
        return self.copies_per_champion * self.champions_in_tier


TIER_POOLS: dict[int, TierPool] = {
    1: TierPool(cost=1, copies_per_champion=30, champions_in_tier=14),
    2: TierPool(cost=2, copies_per_champion=25, champions_in_tier=13),
    3: TierPool(cost=3, copies_per_champion=18, champions_in_tier=14),
    4: TierPool(cost=4, copies_per_champion=10, champions_in_tier=14),
    5: TierPool(cost=5, copies_per_champion=9, champions_in_tier=10),
}

ROLL_COST_GOLD = 2
SHOP_SLOTS = 5

#: 성급별로 풀에서 소모된 사본 수 (2성=3사본, 3성=9사본)
STAR_COPY_WEIGHTS: dict[int, int] = {1: 1, 2: 3, 3: 9}

#: 3성 완성에 필요한 총 사본 수
COPIES_FOR_THREE_STAR = 9

#: 문서로 인용 가능한 (레벨, 코스트) -> 확률(0~1) 셀만 담는다.
VERIFIED_SHOP_ODDS: dict[tuple[int, int], float] = {
    (8, 4): 0.30,
    (10, 5): 0.25,
    (11, 5): 0.35,
}

#: 레벨 1~11 (XP 트랙은 10까지, 11은 보너스 레벨 효과로만 도달)
MAX_LEVEL = 11

#: 골드(XP 구매)로 도달 가능한 최대 레벨. 그 이상의 레벨업 비용은 모른다.
MAX_BUYABLE_LEVEL = 10


class UnknownLevelError(LookupError):
    """레벨업 비용을 계산할 수 없을 때(검증 안 된 레벨).

    조용히 0 을 돌려주면 레벨업 예산이 과대 계산된다. 모르면 모른다고 말한다.
    """

#: 레벨 도달 누적 XP (레벨 3 = 2 XP 기준 누적). 출처: tft.ninja "Leveling and XP"
#:  - L3:2, L4:8, L5:18, L6:38, L7:74, L8:134, L9:202, L10:270
#:  - 레벨당 필요 XP: 2/6/10/20/36/60/68/68
CUMULATIVE_XP_BY_LEVEL: dict[int, int] = {
    1: 0,
    2: 0,
    3: 2,
    4: 8,
    5: 18,
    6: 38,
    7: 74,
    8: 134,
    9: 202,
    10: 270,
}

#: XP 구매 환율: 4골드 -> 4 XP (즉 1골드 = 1 XP)
GOLD_PER_XP = 1.0

#: 라운드당 무료(패시브) XP. 실제 비용은 이만큼 줄어든다(보수적 계산에서는 0으로 둔다).
PASSIVE_XP_PER_ROUND = 2


def level_up_gold(current_level: int, target_level: int, *, count_passive_xp: bool = False,
                  rounds: int = 0) -> int:
    """`current_level` 에서 `target_level` 로 올리는 데 필요한 골드.

    count_passive_xp=True 이면 `rounds` 라운드 동안 쌓이는 패시브 XP(라운드당 2)를
    비용에서 제외한다. 기본값은 False(보수적 = 비싸게 계산).

    Raises
    ------
    UnknownLevelError
        XP 트랙에 없는 레벨(11)로의 레벨업 비용은 **모른다**. 예전에는 레벨을
        10 으로 클램프해 `level_up_gold(10, 11)` 이 0 을 돌려주었고, 그 결과
        레벨업 예산이 과대 계산되었다.
    ValueError
        레벨이 범위 밖이다.
    """
    if current_level < 1:
        raise ValueError(f"레벨은 1 이상이어야 한다: {current_level}")
    if target_level <= current_level:
        return 0
    if target_level > MAX_BUYABLE_LEVEL:
        raise UnknownLevelError(
            f"레벨 {target_level} 도달 XP 비용을 모른다(XP 트랙은 {MAX_BUYABLE_LEVEL} 까지이고, "
            f"{MAX_LEVEL} 은 보너스 레벨 효과로만 도달한다). "
            f"레벨업 계획을 {MAX_BUYABLE_LEVEL} 이하로 지정하거나 "
            "set_data.CUMULATIVE_XP_BY_LEVEL 에 실제 값을 추가하세요."
        )
    # 여기까지 오면 current < target <= 10 이므로 표의 키가 반드시 존재한다.
    xp_needed = CUMULATIVE_XP_BY_LEVEL[target_level] - CUMULATIVE_XP_BY_LEVEL[current_level]
    if count_passive_xp:
        xp_needed = max(0, xp_needed - PASSIVE_XP_PER_ROUND * rounds)
    return int(xp_needed * GOLD_PER_XP)

