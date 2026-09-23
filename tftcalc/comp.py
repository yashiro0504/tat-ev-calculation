"""컴프(덱) 단위 비용/효율 랭킹 엔진.

이 모듈이 "어떤 덱을 가야 가장 효율이 좋은가"에 답하는 부분이다.

무엇을 계산하는가
----------------
1. **기물별 2성/3성 확률** (격리 계산): 그 기물 하나만 노릴 때, 현재 풀 상태와
   골드로 2성/3성에 도달할 확률.
2. **컴프 동시 완성 확률** (동시 계산): 같은 골드·같은 상점에서 여러 유닛을
   동시에 노릴 때의 확률. 골드와 상점 5칸을 **공유**하므로 격리 계산보다 항상 낮다.
   단일 기물 표만 보면 "각 유닛 80%니까 다 되겠지"라는 착각이 생기는데, 그것을 막는다.
3. **랭킹**: 후보 컴프들을 (동시 완성 확률 ↑, 기대 소모 골드 ↓)로 정렬한다.

경계(정직하게 말할 것)
--------------------
* 컴프 목록(메타)은 **이 도구가 만들어내지 않는다**. 외부(MetaTFT 등)나 사용자가
  채워 넣는 입력이다. 이 도구는 "그 후보들 중 지금 이 로비에서 무엇이 가장 싸게
  완성되는가"를 계산한다.
* 아이템(부품 수급), 증강 상성, 포지션, 상대 조합 상성은 범위 밖이다.
  증강 승률/등수 지표는 Riot 정책상 표시 금지라 애초에 넣지 않는다.
* 상점 5칸을 공유하므로 유닛이 많을수록(=컴프가 클수록) 동시 완성 확률이 급감한다.
  이 급감이야말로 "리롤 컴프 vs fast-8 컴프" 판단의 실제 근거다.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from . import pool_math, set_data
from .lobby import LobbySnapshot
from .odds import ShopOdds, UnknownOddsError


@dataclass(frozen=True)
class UnitTarget:
    """컴프가 요구하는 기물 하나."""

    champion: str
    cost: int
    target_star: int = 2

    @property
    def required_copies(self) -> int:
        return set_data.STAR_COPY_WEIGHTS[self.target_star]

    def needed(self, owned_copies: int) -> int:
        return max(0, self.required_copies - owned_copies)


@dataclass
class Comp:
    """컴프 후보 하나."""

    name: str
    units: list[UnitTarget]
    tier: str | None = None
    verified: bool = True
    notes: str | None = None
    source: str | None = None
    roll_level: int | None = None
    core_items: dict[str, int] = field(default_factory=dict)

    def costs(self) -> set[int]:
        return {unit.cost for unit in self.units}

    def item_count(self) -> int:
        """코어 아이템 총 개수(완성템 수)."""
        return sum(self.core_items.values())

    def level_for(self, default_level: int) -> int:
        """이 컴프를 굴릴 레벨. 컴프가 지정하지 않으면 CLI 기본값을 쓴다.

        3코 리롤(6~7레벨)과 fast-8(8레벨)은 상점 확률이 다르므로,
        컴프마다 레벨을 갖는 것이 '같은 조건 비교'의 전제다.
        """
        return self.roll_level if self.roll_level is not None else default_level


def load_comps(path: str | Path) -> list[Comp]:
    """컴프 목록 JSON 을 읽는다.

    형식::

        {
          "source": "사용자 입력 / MetaTFT 등",
          "comps": [
            {"name": "아리 4코 밸류", "tier": "A", "level": 8, "target_star": 2,
             "verified": false,
             "units": [{"champion": "Ahri", "cost": 4},
                       {"champion": "Varus", "cost": 4, "target_star": 2}]},
            {"name": "3코 리롤", "level": 6, "target_star": 3,
             "units": [{"champion": "Sentry", "cost": 3},
                       {"champion": "Leona", "cost": 3, "target_star": 2}]}
          ]
        }

    * ``level`` : 그 컴프를 굴릴 레벨 (없으면 CLI ``--level`` 사용)
    * ``target_star`` (컴프 레벨) : 유닛별 ``target_star`` 가 없을 때 쓰는 기본 성급
    * ``units[].target_star`` : 유닛별 성급 (컴프 기본값을 덮어쓴다)
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    comps: list[Comp] = []
    for entry in raw.get("comps", []):
        default_star = int(entry.get("target_star", 2))
        units = [
            UnitTarget(
                champion=unit["champion"],
                cost=int(unit["cost"]),
                target_star=int(unit.get("target_star", default_star)),
            )
            for unit in entry.get("units", [])
        ]
        roll_level = entry.get("level")
        raw_items = entry.get("items") or {}
        core_items = {
            str(item): int(count)
            for item, count in (raw_items.get("core") or {}).items()
        }
        comps.append(
            Comp(
                name=entry["name"],
                units=units,
                tier=entry.get("tier"),
                verified=bool(entry.get("verified", True)),
                notes=entry.get("notes"),
                source=entry.get("source") or raw.get("source"),
                roll_level=int(roll_level) if roll_level is not None else None,
                core_items=core_items,
            )
        )
    return comps


def pool_state_from_snapshot(
    snapshot: LobbySnapshot,
) -> tuple[dict[str, int], dict[int, int]]:
    """스냅샷 → (챔피언별 소모 사본, 코스트별 소모 사본)."""
    copies_in_play = snapshot.copies_in_play()
    tier_in_play: dict[int, int] = {}
    for champion, copies in copies_in_play.items():
        cost = snapshot.cost_of(champion)
        tier_in_play[cost] = tier_in_play.get(cost, 0) + copies
    return copies_in_play, tier_in_play


def unit_outlook(
    odds: ShopOdds,
    *,
    unit: UnitTarget,
    owned_copies: int,
    copies_in_play: dict[str, int],
    tier_in_play: dict[int, int],
    level: int,
    roll_budget: int,
    trials: int = 3_000,
    seed: int = 31,
) -> dict[str, object]:
    """기물 1종의 2성/3성 확률 (격리 계산: 그 기물만 노릴 때).

    격리 계산은 '각 유닛을 하나씩 따로 노렸을 때'의 값이다. 컴프 전체를 동시에
    노리면 골드·상점을 공유하므로 실제 확률은 이보다 낮다(simulate_comp 와 비교).
    """
    cost_odds = odds.cost_odds(level, unit.cost)
    remaining_target = pool_math.remaining_target_copies(
        unit.cost, copies_in_play.get(unit.champion, 0)
    )
    remaining_tier = pool_math.remaining_tier_copies(
        unit.cost, tier_in_play.get(unit.cost, 0)
    )
    p_slot = pool_math.p_slot_is_target(cost_odds, remaining_target, remaining_tier)

    outlook: dict[str, object] = {
        "champion": unit.champion,
        "cost": unit.cost,
        "owned_copies": owned_copies,
        "remaining_target": remaining_target,
        "remaining_tier": remaining_tier,
        "p_shop": pool_math.p_shop_at_least_one(p_slot),
        "expected_roll_gold_next_copy": pool_math.expected_roll_gold_for_next_copy(p_slot),
    }

    for star in (1, 2, 3):
        need = max(0, set_data.STAR_COPY_WEIGHTS[star] - owned_copies)
        key = f"p_star{star}"
        if need == 0:
            outlook[key] = 1.0
            outlook[f"gold_star{star}"] = 0.0
            outlook[f"note_star{star}"] = "이미 완성"
            continue
        if remaining_target < need:
            outlook[key] = 0.0
            outlook[f"gold_star{star}"] = None
            outlook[f"note_star{star}"] = f"풀 부족(남은 {remaining_target} < 필요 {need})"
            continue
        result = pool_math.simulate_roll_down(
            odds,
            level=level,
            unit_cost=unit.cost,
            remaining_target=remaining_target,
            remaining_tier=remaining_tier,
            need=need,
            budget=roll_budget,
            trials=trials,
            seed=seed + star,
        )
        outlook[key] = result.p_complete
        # 표시용 '기대 골드'는 조건부(성공했을 때 평균 소모)다.
        # 실패하면 골드를 다 태우고 못 얻으므로, 전체 평균은 의미가 흐려진다.
        outlook[f"gold_star{star}"] = result.mean_gold_on_success
        outlook[f"total_gold_star{star}"] = result.mean_total_gold
        outlook[f"note_star{star}"] = ""

    return outlook


def _pick_weighted(
    rng: random.Random, weights: list[tuple[UnitTarget, float]]
) -> UnitTarget:
    total = sum(weight for _, weight in weights)
    threshold = rng.random() * total
    cumulative = 0.0
    for unit, weight in weights:
        cumulative += weight
        if cumulative >= threshold:
            return unit
    return weights[-1][0]


def simulate_comp(
    odds: ShopOdds,
    *,
    comp: Comp,
    owned_by_champion: dict[str, int],
    copies_in_play: dict[str, int],
    tier_in_play: dict[int, int],
    level: int,
    roll_budget: int,
    fixed_gold_cost: int = 0,
    trials: int = 3_000,
    seed: int = 5,
) -> dict[str, object]:
    """컴프 동시 완성 시뮬레이션 (같은 골드·같은 상점 5칸을 공유).

    fixed_gold_cost : 롤/구매와 별개로 '무조건 드는' 비용(예: 목표 레벨까지 XP 구매 골드).
        같은 값이 모든 시행에 더해지므로 확률에는 영향이 없고 총비용만 올린다.
    """
    # 컴프가 자기 롤 레벨을 지정했으면 그 레벨의 상점 확률을 쓴다(3코 리롤 vs fast-8).
    level = comp.level_for(level)
    result: dict[str, object] = {
        "comp": comp.name,
        "tier": comp.tier,
        "verified": comp.verified,
        "level": level,
        "roll_budget": roll_budget,
        "fixed_gold_cost": fixed_gold_cost,
        "unit_count": len(
            [
                unit
                for unit in comp.units
                if unit.needed(owned_by_champion.get(unit.champion, 0)) > 0
            ]
        ),
    }

    try:
        # 이 컴프에 필요한 모든 코스트의 확률을 알아야 한다.
        # 모르는 코스트가 하나라도 있으면 그 컴프만 '데이터 부족'으로 표시하고 추정하지 않는다.
        cost_odds = {cost: odds.cost_odds(level, cost) for cost in sorted(comp.costs())}
    except UnknownOddsError as exc:
        result.update(error=str(exc), p_complete=None, mean_total_gold=None)
        return result

    targets = [
        unit
        for unit in comp.units
        if unit.needed(owned_by_champion.get(unit.champion, 0)) > 0
    ]

    if not targets:
        result.update(
            p_complete=1.0,
            mean_total_gold=float(fixed_gold_cost),
            mean_gold_on_success=float(fixed_gold_cost),
            mean_roll_gold=0.0,
            mean_purchase_gold=0.0,
            impossible=[],
            unit_completion={unit.champion: 1.0 for unit in comp.units},
        )
        return result

    remaining_base: dict[str, int] = {}
    impossible: list[str] = []
    for unit in targets:
        owned = owned_by_champion.get(unit.champion, 0)
        remaining = pool_math.remaining_target_copies(
            unit.cost, copies_in_play.get(unit.champion, 0)
        )
        remaining_base[unit.champion] = remaining
        if remaining < unit.needed(owned):
            impossible.append(unit.champion)

    if impossible:
        result.update(
            p_complete=0.0,
            mean_total_gold=float(fixed_gold_cost),
            mean_gold_on_success=None,
            mean_roll_gold=0.0,
            mean_purchase_gold=0.0,
            impossible=sorted(impossible),
            unit_completion={unit.champion: 0.0 for unit in comp.units},
        )
        return result

    tier_remaining_base = {
        cost: pool_math.remaining_tier_copies(cost, tier_in_play.get(cost, 0))
        for cost in cost_odds
    }

    successes = 0
    sum_total = sum_roll = sum_buy = 0.0
    sum_on_success = 0.0
    unit_success = {unit.champion: 0 for unit in targets}
    rng = random.Random(seed)

    for _ in range(trials):
        owned = {
            unit.champion: owned_by_champion.get(unit.champion, 0) for unit in targets
        }
        rem = dict(remaining_base)
        tier_rem = dict(tier_remaining_base)
        spent = roll_spent = buy_spent = 0

        while spent + set_data.ROLL_COST_GOLD <= roll_budget:
            pending = [
                unit for unit in targets if unit.needed(owned[unit.champion]) > 0
            ]
            if not pending:
                break
            spent += set_data.ROLL_COST_GOLD
            roll_spent += set_data.ROLL_COST_GOLD

            for _slot in range(set_data.SHOP_SLOTS):
                pending = [
                    unit for unit in targets if unit.needed(owned[unit.champion]) > 0
                ]
                if not pending:
                    break
                weights: list[tuple[UnitTarget, float]] = []
                for unit in pending:
                    tier_total = tier_rem.get(unit.cost, 0)
                    if tier_total <= 0 or rem[unit.champion] <= 0:
                        continue
                    # 이 슬롯이 '이 코스트'일 확률 x 그 안에서 이 유닛의 비중
                    weights.append(
                        (unit, cost_odds[unit.cost] * rem[unit.champion] / tier_total)
                    )
                total_probability = sum(probability for _, probability in weights)
                if total_probability <= 0 or rng.random() >= total_probability:
                    continue  # 이 슬롯은 내 유닛이 아니다
                unit = _pick_weighted(rng, weights)
                if (roll_budget - spent) < unit.cost:
                    continue  # 살 돈이 없다
                spent += unit.cost
                buy_spent += unit.cost
                owned[unit.champion] += 1
                rem[unit.champion] -= 1
                tier_rem[unit.cost] = max(0, tier_rem[unit.cost] - 1)

        if all(unit.needed(owned[unit.champion]) == 0 for unit in targets):
            successes += 1
            sum_on_success += spent + fixed_gold_cost
        for unit in targets:
            if unit.needed(owned[unit.champion]) == 0:
                unit_success[unit.champion] += 1

        sum_total += spent
        sum_roll += roll_spent
        sum_buy += buy_spent

    result.update(
        p_complete=successes / trials,
        mean_total_gold=sum_total / trials + fixed_gold_cost,
        mean_gold_on_success=(sum_on_success / successes if successes else None),
        mean_roll_gold=sum_roll / trials,
        mean_purchase_gold=sum_buy / trials,
        impossible=[],
        unit_completion={
            unit.champion: unit_success[unit.champion] / trials for unit in targets
        },
    )
    return result


def rank_comps(
    odds: ShopOdds,
    *,
    comps: list[Comp],
    owned_by_champion: dict[str, int],
    copies_in_play: dict[str, int],
    tier_in_play: dict[int, int],
    level: int,
    roll_budget: int | None = None,
    gold_total: int | None = None,
    current_level: int | None = None,
    levelup_rounds: int = 0,
    extra_fixed_gold_cost: int = 0,
    trials: int = 3_000,
    seed: int = 5,
) -> list[dict[str, object]]:
    """컴프들을 (동시 완성 확률 ↑, 기대 총비용 ↓)로 정렬한다.

    정산 모드 두 가지:
    * ``gold_total`` 지정: '지금 가진 총 골드'에서 **레벨업 비용을 먼저 떼고**,
      남은 골드로 롤/구매한다. 3코 리롤(Lv6)과 fast-8(Lv8)처럼 레벨이 다른 컴프를
      같은 조건에서 비교하려면 이 모드여야 한다.
    * ``roll_budget`` 지정: 롤/구매 예산을 따로 주고 레벨업 비용은 총비용에만 가산한다.

    '데이터 부족'으로 계산하지 못한 컴프는 항상 뒤로 보낸다(추정으로 채우지 않는다).
    """
    if gold_total is None and roll_budget is None:
        raise ValueError("gold_total 또는 roll_budget 중 하나는 필요합니다.")

    results: list[dict[str, object]] = []
    for comp in comps:
        comp_level = comp.level_for(level)
        levelup_gold = 0
        if current_level is not None:
            levelup_gold = set_data.level_up_gold(
                current_level,
                comp_level,
                count_passive_xp=levelup_rounds > 0,
                rounds=levelup_rounds,
            )

        if gold_total is not None:
            budget = max(0, int(gold_total) - levelup_gold)
            fixed = levelup_gold + extra_fixed_gold_cost
        else:
            budget = int(roll_budget)  # type: ignore[arg-type]
            fixed = levelup_gold + extra_fixed_gold_cost

        row = simulate_comp(
            odds,
            comp=comp,
            owned_by_champion=owned_by_champion,
            copies_in_play=copies_in_play,
            tier_in_play=tier_in_play,
            level=comp_level,
            roll_budget=budget,
            fixed_gold_cost=fixed,
            trials=trials,
            seed=seed,
        )
        row["levelup_gold"] = levelup_gold
        row["roll_budget"] = budget
        results.append(row)

    def _key(row: dict[str, object]) -> tuple[int, float, float]:
        if row.get("error"):
            return (1, 0.0, 0.0)
        return (0, -float(row["p_complete"]), float(row["mean_total_gold"]))

    return sorted(results, key=_key)