"""아이템 부품 수급 모델 (C단계).

문제: "유닛은 완성되는데 아이템이 안 맞는 덱"이 있다. 유닛 확률만으로 랭킹하면
그런 덱이 1위로 올라온다. 그래서 아이템 축을 별도로 계산해 함께 보여준다.

계산 흐름
--------
1. 조합식 로더: ``data/set18_item_recipes.json`` (scripts/fetch_item_recipes.py 생성)
2. 컴프 코어 아이템 -> 필요한 부품 다중집합 (components_required)
3. 현재 보유 부품 + 앞으로 얻을 부품 수 -> '코어 아이템이 다 맞을 확률' (p_ready)

정직성 규칙
----------
* 조합식을 모르는 아이템이 코어에 있으면 **추정하지 않고** ``UnknownRecipeError`` 로 알린다.
* 미래 부품은 기본적으로 '8종 균등 무작위'로 가정한다(가정임을 출력에 명시).
  캐러셀/모루/아이템 증강처럼 **고를 수 있는** 부품은 ``choice_components`` 로 따로 센다.
* 아이템 슬롯이 3개(유닛당)라는 제약은 '코어 아이템 개수'로 이미 반영된다.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .trials import HEAVY

DEFAULT_RECIPES = Path(__file__).resolve().parents[1] / "data" / "set18_item_recipes.json"

#: CLI 에서 쓰는 짧은 부품 키 -> 실제 부품명
COMPONENT_KEYS: dict[str, str] = {
    "sword": "B.F. Sword",
    "bow": "Recurve Bow",
    "rod": "Needlessly Large Rod",
    "tear": "Tear of the Goddess",
    "vest": "Chain Vest",
    "cloak": "Negatron Cloak",
    "belt": "Giant's Belt",
    "gloves": "Sparring Gloves",
    "spatula": "Spatula",
}

#: 무작위로 떨어지는 부품 풀(스패출라 제외: 별도 획득 경로)
RANDOM_POOL: tuple[str, ...] = tuple(
    name for key, name in COMPONENT_KEYS.items() if key != "spatula"
)


class UnknownRecipeError(LookupError):
    """코어 아이템의 조합식을 모를 때(추정 금지)."""


def normalize_item_name(value: str) -> str:
    """아이템 이름 비교용 정규화: 아포스트로피/공백/대소문자 무시."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


@dataclass
class RecipeBook:
    recipes: dict[str, list[str]]
    component_names: list[str]
    source: str
    #: 이름 정규화 인덱스(아포스트로피/공백/대소문자 무시). ``__post_init__`` 에서 채운다.
    #: 필드로 선언하지 않으면 타입 체커가 "선언 안 된 속성"으로 잡는다.
    by_normalized: dict[str, str] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        # 아이템 이름 표기가 출처마다 다르다(tft.ninja 'Warmogs Armor' vs 한국어 자료 'Warmog's Armor').
        # 그래서 아포스트로피/공백/대소문자를 무시한 정규화 인덱스를 함께 만든다.
        self.by_normalized = {
            normalize_item_name(name): name for name in self.recipes
        }

    @classmethod
    def load(cls, path: str | Path = DEFAULT_RECIPES) -> "RecipeBook":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        recipes = {
            str(name): [str(component) for component in value.get("components", [])]
            for name, value in raw.get("recipes", {}).items()
        }
        return cls(
            recipes=recipes,
            component_names=[str(name) for name in raw.get("component_names", [])],
            source=str(raw.get("source", "?")),
        )

    def recipe(self, item: str) -> list[str]:
        if item in self.recipes:
            return self.recipes[item]
        normalized = normalize_item_name(item)
        if normalized in self.by_normalized:
            return self.recipes[self.by_normalized[normalized]]
        raise UnknownRecipeError(
            f"'{item}' 의 조합식을 모릅니다. data/set18_item_recipes.json 에 없으면 "
            "scripts/fetch_item_recipes.py 로 수집한 뒤 다시 실행하세요."
        )


def parse_component_spec(spec: str) -> Counter[str]:
    """'sword:2,bow,rod' -> Counter({'B.F. Sword': 2, 'Recurve Bow': 1, ...})"""
    counts: Counter[str] = Counter()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, _, amount = chunk.partition(":")
        key = key.strip().lower()
        name = COMPONENT_KEYS.get(key)
        if name is None:
            raise ValueError(
                f"부품 키 '{key}' 를 모릅니다. 사용 가능: {', '.join(COMPONENT_KEYS)}"
            )
        counts[name] += int(amount) if amount.strip() else 1
    return counts


def components_required(
    book: RecipeBook, core_items: Mapping[str, int]
) -> Counter[str]:
    """코어 아이템 목록 -> 필요한 부품 다중집합."""
    required: Counter[str] = Counter()
    for item, count in core_items.items():
        recipe = book.recipe(item)
        for component in recipe:
            required[component] += count
    return required


def shortfall(
    required: Mapping[str, int], have: Mapping[str, int]
) -> dict[str, int]:
    """지금 부족한 부품만 추린다."""
    return {
        component: needed - int(have.get(component, 0))
        for component, needed in required.items()
        if needed - int(have.get(component, 0)) > 0
    }


@dataclass(frozen=True)
class ItemReadiness:
    required: dict[str, int]
    have: dict[str, int]
    missing_now: dict[str, int]
    future_components: int
    choice_components: int
    p_ready: float
    expected_shortfall_after: float
    priority: list[tuple[str, int]]

    def as_dict(self) -> dict[str, object]:
        return {
            "required": self.required,
            "have": self.have,
            "missing_now": self.missing_now,
            "future_components": self.future_components,
            "choice_components": self.choice_components,
            "p_ready": round(self.p_ready, 4),
            "expected_shortfall_after": round(self.expected_shortfall_after, 3),
            "priority": [f"{name} x{count}" for name, count in self.priority],
        }


def p_ready_after(
    required: Mapping[str, int],
    have: Mapping[str, int],
    *,
    future_components: int = 0,
    choice_components: int = 0,
    trials: int = HEAVY,
    seed: int = 7,
    pool: tuple[str, ...] = RANDOM_POOL,
) -> tuple[float, float]:
    """앞으로 받을 부품까지 반영해 '코어 아이템이 모두 완성될 확률'을 계산한다.

    모델(가정):
    * ``future_components`` 개는 ``pool``(기본 8종)에서 균등 무작위로 떨어진다.
    * ``choice_components`` 개는 캐러셀/모루/증강처럼 **골라 받는** 부품이라 아무 부족분이나
      메울 수 있는 와일드카드로 취급한다.
    * 부품을 모으는 동안 다른 아이템에 쓰지 않는다(코어 아이템에 우선 투자).

    Returns
    -------
    (p_ready, expected_remaining_shortfall)
    """
    missing: Counter[str] = Counter(shortfall(required, have))
    if not missing:
        return 1.0, 0.0

    rng = random.Random(seed)
    success = 0
    shortfall_sum = 0
    for _ in range(trials):
        remaining: Counter[str] = Counter(missing)
        for _draw in range(future_components):
            component = pool[rng.randrange(len(pool))]
            if remaining.get(component, 0) > 0:
                remaining[component] -= 1
        for _draw in range(choice_components):
            available = [name for name, count in remaining.items() if count > 0]
            if not available:
                break
            remaining[available[0]] -= 1
        left = sum(count for count in remaining.values() if count > 0)
        if left == 0:
            success += 1
        shortfall_sum += left

    return success / trials, shortfall_sum / trials


def analyze_items(
    book: RecipeBook,
    core_items: Mapping[str, int],
    *,
    have: Mapping[str, int] | None = None,
    future_components: int = 0,
    choice_components: int = 0,
    trials: int = HEAVY,
    seed: int = 7,
) -> ItemReadiness:
    """코어 아이템 요구량/부족분/확률/부품 우선순위를 한 번에 계산한다."""
    have = dict(have or {})
    required = dict(components_required(book, core_items))
    missing_now = shortfall(required, have)
    probability, expected_left = p_ready_after(
        required,
        have,
        future_components=future_components,
        choice_components=choice_components,
        trials=trials,
        seed=seed,
    )
    priority = sorted(missing_now.items(), key=lambda pair: (-pair[1], pair[0]))
    return ItemReadiness(
        required=dict(sorted(required.items())),
        have=dict(sorted(have.items())),
        missing_now=dict(sorted(missing_now.items())),
        future_components=future_components,
        choice_components=choice_components,
        p_ready=probability,
        expected_shortfall_after=expected_left,
        priority=priority,
    )


def comp_core_items(core_items: Mapping[str, int], limit: int | None = None) -> dict[str, int]:
    """코어 아이템을 '완성템 수' 기준으로 앞에서부터 자른다.

    실제 경기에서 만드는 완성템은 4~6개 정도다(유닛당 3칸 x 캐리 2~3명이 상한).
    ``limit`` 이 0/None 이면 전부 사용한다.
    """
    if not limit:
        return dict(core_items)
    trimmed: dict[str, int] = {}
    remaining = limit
    for item, count in core_items.items():
        if remaining <= 0:
            break
        take = min(count, remaining)
        trimmed[item] = take
        remaining -= take
    return trimmed
