"""CLI 데모: 확률/기대 골드 계산기.

사용 예
-------
  python -m tftcalc.cli odds
  python -m tftcalc.cli unit --level 8 --cost 4 --own 1 --others 4 --target-star 2 --budget 60
  python -m tftcalc.cli lobby --snapshot data/example_snapshot.json --champion Ahri \
        --level 8 --target-star 2 --budget 60
  python -m tftcalc.cli selftest

경고: 상대 보유분을 모르면 남은 사본이 과대평가되어 결과가 낙관 편향된다.
      --others 또는 --snapshot 으로 실제 로비 상태를 반드시 넣는다.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import comp as comp_module
from . import decision, economy, items, lobby, pool_math, render, rules, set_data, survival
from .trials import FAST, HEAVY, STANDARD
from .cv import fingerprint
from .cv import layout as layout_module
from .cv import scan as scan_module
from .cv import screen
from .odds import DEFAULT_ODDS_FILE, ShopOdds, UnknownOddsError


def _item_input_given(args: argparse.Namespace) -> bool:
    """아이템 확률을 계산할 만한 입력이 있는지(보유/앞으로/선택 부품)."""
    return bool(
        getattr(args, "components", None)
        or getattr(args, "future_components", 0)
        or getattr(args, "choice_components", 0)
    )


def build_odds(args: argparse.Namespace) -> ShopOdds:
    """상점 확률표를 만든다.

    우선순위: ``builtin``(검증 셀)  <  ``data/set18_shop_odds.json``(실전, 있으면 자동)
              <  ``--odds-file``(명시 지정이 항상 이김)

    실전 파일을 자동으로 얹는 것은 다른 ``data/*.json``(코스트표·템플릿·컴프)과 같은 방식이다.
    그래서 **파일만 채우면 모든 명령에 반영되고**, 채우기 전에는 null 셀이 모르는 채로 남아
    그 셀을 쓰는 계산이 ``UnknownOddsError`` 로 멈춘다.
    """
    odds = ShopOdds.builtin()
    if DEFAULT_ODDS_FILE.exists():
        odds = ShopOdds.from_json(DEFAULT_ODDS_FILE, base=odds)
    path = getattr(args, "odds_file", None)
    if path:
        odds = ShopOdds.from_json(path, base=odds)
    return odds


def _print_unit_report(report: dict[str, object], confidence_note: str | None) -> None:
    print("=== [검증된 수학] 기물 완성 비용 ===")
    print(f"세트: {set_data.SET_NAME} (데이터 확인 {set_data.DATA_VERIFIED_ON})")
    print(
        f"레벨 {report['level']} / {report['cost']}코 / 목표 {report['target_star']}성 "
        f"/ 보유 {report['own_copies']}장 / 더 필요 {report['need']}장"
    )
    print(
        f"풀: 챔피언당 {report['pool_per_champion']}사본, "
        f"대상 남은 사본 {report['remaining_target']}, "
        f"등급 남은 사본 {report['remaining_tier']}"
    )
    if report.get("need") == 0 or report.get("impossible"):
        print(f"-> {report['verdict']}")
        return

    print(
        f"1칸 확률 {render.pct(float(report['p_slot']))} / "
        f"1상점(5칸) 확률 {render.pct(float(report['p_shop']))}"
    )
    print(f"다음 1장까지 기대 리롤 비용: {render.gold(float(report['expected_roll_gold_next_copy']))}")
    print(f"1장을 80% 확률로 보는데 필요한 상점 수: {report['shops_for_80pct_one_copy']}회")
    roll = report.get("roll_down")
    if isinstance(roll, dict):
        print("--- 몬테카를로 롤다운 (구매로 인한 풀 감소 반영) ---")
        print(f"예산 {roll['budget']}골드 -> 완성 확률 {render.pct(float(roll['p_complete']))}")
        print(
            f"기대 소모: 총 {roll['mean_total_gold']}골드 "
            f"(리롤 {roll['mean_roll_gold']} + 구매 {roll['mean_purchase_gold']}), "
            f"평균 상점 {roll['mean_shops']}회"
        )
        if roll["mean_gold_on_success"] is not None:
            print(f"성공했을 때 평균 소모: {roll['mean_gold_on_success']}골드")
        print(f"풀 고갈로 실패한 비율: {render.pct(float(roll['pool_exhausted_rate']))}")
        print(f"80% 도달 예산: {report['gold_for_80pct']}골드")
    if confidence_note:
        print(f"[데이터 신뢰도] {confidence_note}")
    print(
        "[미검증] 보드 전투력/증강 상성/메타는 계산하지 않는다. "
        "그 값이 필요하면 실측 캘리브레이션이 선행되어야 한다."
    )


def cmd_odds(args: argparse.Namespace) -> int:
    """아는 상점 확률 셀 출력 + (실전 파일이 있으면) 채움 진행 격자."""
    odds = build_odds(args)
    if not odds.declared:
        # 확률표 파일이 없으면 예전처럼 아는 셀만 나열한다.
        print(odds.describe())
        return 0

    print(odds.describe_source())
    pending = odds.pending()
    print()
    print(
        f"=== 확률표 채움: {len(odds.declared) - len(pending)} / {len(odds.declared)} 셀 "
        f"(미채움 {len(pending)}) ==="
    )
    for line in render.odds_grid(
        levels=sorted({level for level, _ in odds.declared}),
        costs=sorted({cost for _, cost in odds.declared}),
        values=odds.cells,
        declared=odds.declared,
    ):
        print(line)
    if pending:
        print(
            f"  ('?' = 미채움 {len(pending)}개 — {DEFAULT_ODDS_FILE.name} 의 null 을 "
            "인게임 값으로 채우세요.)"
        )
    else:
        print("  (모든 셀이 채워졌습니다. --odds-file 없이 그대로 쓰입니다.)")
    return 0


def cmd_unit(args: argparse.Namespace) -> int:
    odds = build_odds(args)
    own, others = args.own, args.others
    tier_in_play = args.tier_in_play
    if tier_in_play is None:
        tier_in_play = own + others
        print(
            "[가정] 같은 코스트의 다른 기물은 아무도 안 들고 있다고 가정했다 "
            "(등급 소모 = 내 보유 + 상대 보유). --tier-in-play 로 정확히 줄 수 있다."
        )
    report = decision.unit_cost_report(
        odds,
        level=args.level,
        cost=args.cost,
        copies_of_target_in_play=own + others,
        copies_in_play_of_tier=tier_in_play,
        own_copies=own,
        target_star=args.target_star,
        budget=args.budget,
        trials=args.trials,
    )
    _print_unit_report(report, None)
    return 0


def cmd_lobby(args: argparse.Namespace) -> int:
    odds = build_odds(args)
    snapshot = lobby.LobbySnapshot.from_json(args.snapshot)
    cost = snapshot.cost_of(args.champion)
    report = decision.unit_cost_report(
        odds,
        level=args.level,
        cost=cost,
        copies_of_target_in_play=snapshot.copies_in_play()[args.champion],
        copies_in_play_of_tier=snapshot.copies_in_play_of_tier(cost),
        own_copies=snapshot.my_copies(args.champion),
        target_star=args.target_star,
        budget=args.budget,
        trials=args.trials,
    )
    _print_unit_report(report, snapshot.confidence_note())
    print()
    print(f"=== [검증된 수학] {cost}코 남은 사본 순위 (적은 순) ===")
    for row in snapshot.contest_table(cost=cost)[:12]:
        flag = "  <-- 풀 고갈" if row["impossible"] else ""
        print(
            f"  {row['champion']:<16} 소모 {row['copies_in_play']:>2} "
            f"/ 남은 {row['remaining']:>2} (풀 {row['pool_per_champion']}){flag}"
        )
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:  # noqa: ARG001
    """공개 벤치마크(4코 10사본/14종, L8 30%)를 재현해 계산 엔진을 검증한다."""
    odds = ShopOdds.builtin()  # noqa: F841  (소스 확인용)
    remaining_target = pool_math.remaining_target_copies(4, 3)
    remaining_tier = pool_math.remaining_tier_copies(4, 3)
    p_slot = pool_math.p_slot_is_target(0.30, remaining_target, remaining_tier)
    print("=== 벤치마크 재현 (tft.ninja 'Champion Pool Math (Set 18)') ===")
    print(f"남은 사본 {remaining_target} / 남은 4코 풀 {remaining_tier} -> 1칸 {render.pct(p_slot)}")
    print(f"1상점 확률 {render.pct(pool_math.p_shop_at_least_one(p_slot))} (공개값 7.4%)")
    reference = {20: "54%", 30: "69%", 50: "85%", 60: "90%"}
    for gold in (20, 30, 50, 60):
        probability = pool_math.p_at_least_one_in_shops(
            p_slot, pool_math.shops_for_gold(gold)
        )
        print(f"  {gold:>3}골드 -> {render.pct(probability)} (공개값 {reference[gold]})")
    print(
        "다음 1장 기대 리롤 비용: "
        f"{render.gold(pool_math.expected_roll_gold_for_next_copy(p_slot))}"
    )
    return 0


def cmd_sensitivity(args: argparse.Namespace) -> int:
    """상점 확률표를 모를 때: 후보 확률값들에 대한 비용 민감도를 계산한다.

    이건 '추정'이 아니라 '입력에 따른 출력 표'다. 사용자가 인게임에서 확률을 확인해
    해당 행만 --odds-file 로 넣으면 정확한 값이 된다.
    """
    candidates = [float(v) for v in args.cost_odds.split(",")]
    if args.cost_odds_are_percent:
        candidates = [v / 100.0 for v in candidates]
    print(f"=== 민감도: {args.level}레벨 {args.cost}코 확률 후보별 비용 ===")
    print(f"조건: 내 {args.own}장 / 상대 {args.others}장 / 목표 {args.target_star}성")
    # 한글 헤더는 표시 폭(2칸) 기준으로 맞춘다 — f-string 의 `>8` 은 글자 수라 어긋난다.
    # '예산내완성' 만 표시 폭 10 이라 이 열만 1칸 넓혔다(데이터도 함께).
    header = (
        f"{render.pad('3코확률', 8, '>')} {render.pad('남은사본', 8, '>')} "
        f"{render.pad('1상점', 7, '>')} {render.pad('기대리롤', 9, '>')} "
        f"{render.pad('예산내완성', 10, '>')} {render.pad('기대총골드', 10, '>')}"
    )
    print(header)
    print("-" * render.disp_len(header))
    for value in candidates:
        odds = ShopOdds(
            cells={(args.level, args.cost): value},
            source=f"가정 {value * 100:.0f}%",
        )
        report = decision.unit_cost_report(
            odds,
            level=args.level,
            cost=args.cost,
            copies_of_target_in_play=args.own + args.others,
            copies_in_play_of_tier=args.tier_in_play,
            own_copies=args.own,
            target_star=args.target_star,
            budget=args.budget,
            trials=args.trials,
        )
        if report.get("impossible"):
            print(
                f"{value * 100:>7.1f}% {report['remaining_target']:>8} "
                f"{'':>7} {'':>9} {render.pad('불가', 10, '>')} {'':>10}"
            )
            continue
        roll = report["roll_down"]
        print(
            f"{value * 100:>7.1f}% {report['remaining_target']:>8} "
            f"{float(report['p_shop']) * 100:>6.1f}% "
            f"{float(report['expected_roll_gold_next_copy']):>8.1f}g "
            f"{float(roll['p_complete']) * 100:>9.1f}% "
            f"{roll['mean_total_gold']:>9.1f}g"
        )
    print()
    print(
        "[읽는 법] 확률 후보 중 어느 값에서도 '기대총골드'가 감당 불가라면 그 라인은 "
        "확률표 정밀도와 무관하게 위험하다. 반대로 결론이 후보에 따라 뒤집히면 "
        "반드시 인게임 확률을 확인한 뒤 판단해야 한다."
    )
    return 0


def _parse_unit_specs(spec: str) -> list["comp_module.UnitTarget"]:
    """'Karma:4,Varus:4:3' -> [UnitTarget(Karma,4,2), UnitTarget(Varus,4,3)]"""
    targets: list[comp_module.UnitTarget] = []
    for chunk in spec.split(","):
        parts = [part.strip() for part in chunk.split(":") if part.strip()]
        if len(parts) < 2:
            raise ValueError(
                f"'{chunk}' 형식이 잘못되었습니다. 예: Karma:4 (2성) / Karma:4:3 (3성)"
            )
        targets.append(
            comp_module.UnitTarget(
                champion=parts[0],
                cost=int(parts[1]),
                target_star=int(parts[2]) if len(parts) > 2 else 2,
            )
        )
    return targets


def cmd_outlook(args: argparse.Namespace) -> int:
    """기물별 2성/3성 확률 표 (격리 계산)."""
    odds = build_odds(args)
    snapshot = lobby.LobbySnapshot.from_json(args.snapshot)
    copies_in_play, tier_in_play = comp_module.pool_state_from_snapshot(snapshot)
    owned_map = snapshot.my_copies_map()

    if args.units:
        units = _parse_unit_specs(args.units)
    else:
        units = [
            comp_module.UnitTarget(champion=champion, cost=snapshot.cost_of(champion))
            for champion in sorted(owned_map, key=lambda name: snapshot.cost_of(name))
        ]

    print("=== 기물별 2성/3성 확률 (격리 계산: 그 기물 하나만 노릴 때) ===")
    print(
        f"Lv{args.level} / 예산 {args.budget}골드 / {set_data.SET_NAME} / "
        f"상점 확률 소스: {odds.source}"
    )
    header = (
        f"{render.pad('기물', 14)}{render.pad('코', 3, '>')}{render.pad('보유', 5, '>')}"
        f"{render.pad('남은', 5, '>')}{render.pad('1상점', 8, '>')}"
        f"{render.pad('2성', 8, '>')}{render.pad('2성기대골드', 12, '>')}"
        f"{render.pad('3성', 8, '>')}{render.pad('3성기대골드', 12, '>')}"
    )
    print(header)
    print("-" * render.disp_len(header))
    for unit in units:
        owned = owned_map.get(unit.champion, 0)
        if copies_in_play.get(unit.champion, 0) == 0:
            print(
                f"{unit.champion:<14}{unit.cost:>3}{owned:>5}{'?':>5}"
                f"{'':>8}{'':>8}{'':>12}{'':>8}{'':>12}  "
                "<-- 로비에서 관측되지 않음(풀 상태 미확인)"
            )
            continue
        outlook = comp_module.unit_outlook(
            odds,
            unit=unit,
            owned_copies=owned,
            copies_in_play=copies_in_play,
            tier_in_play=tier_in_play,
            level=args.level,
            roll_budget=args.budget,
            trials=args.trials,
        )
        gold2, gold3 = outlook["gold_star2"], outlook["gold_star3"]
        note = str(outlook["note_star2"] or outlook["note_star3"] or "")
        print(
            f"{unit.champion:<14}{unit.cost:>3}{owned:>5}"
            f"{int(outlook['remaining_target']):>5}"
            f"{render.pct_fmt(float(outlook['p_shop']), 8)}"
            f"{render.pct_fmt(float(outlook['p_star2']), 8)}"
            f"{render.gold_fmt(gold2)}"
            f"{render.pct_fmt(float(outlook['p_star3']), 8)}"
            f"{render.gold_fmt(gold3)}" + (f"  {note}" if note else "")
        )
    print()
    print(f"[데이터 신뢰도] {snapshot.confidence_note()}")
    print(
        "[주의] 여기 확률은 '그 기물만' 노렸을 때다. 컴프 전체를 동시에 노리면 "
        "골드와 상점 5칸을 공유하므로 실제 확률은 더 낮다 (comp 명령으로 확인)."
    )
    return 0


def comps_by_name(comps: list["comp_module.Comp"], name: str) -> "comp_module.Comp | None":
    for comp in comps:
        if comp.name == name:
            return comp
    return None


def comps_units(
    comps: list["comp_module.Comp"], name: str
) -> list["comp_module.UnitTarget"]:
    found = comps_by_name(comps, name)
    return list(found.units) if found else []


def _load_item_book(args: argparse.Namespace) -> "items.RecipeBook | None":
    """조합식 파일 로드. 없으면 안내만 하고 None(아이템 축 비활성)."""
    try:
        return items.RecipeBook.load(getattr(args, "recipes", None) or items.DEFAULT_RECIPES)
    except FileNotFoundError:
        print(
            "[아이템 데이터 없음] data/set18_item_recipes.json 이 없습니다. "
            "python scripts/fetch_item_recipes.py 를 먼저 실행하세요."
        )
        return None


def _item_readiness(
    book: "items.RecipeBook | None",
    comp: "comp_module.Comp",
    *,
    have: dict[str, int],
    future_components: int,
    choice_components: int,
    core_items_limit: int | None,
) -> tuple["items.ItemReadiness | None", str | None]:
    """컴프의 코어 아이템 준비도. (결과, 오류메시지)"""
    if book is None or not comp.core_items:
        return None, None
    core = items.comp_core_items(comp.core_items, limit=core_items_limit)
    try:
        return (
            items.analyze_items(
                book,
                core,
                have=have,
                future_components=future_components,
                choice_components=choice_components,
            ),
            None,
        )
    except items.UnknownRecipeError as exc:
        return None, str(exc)


def cmd_items(args: argparse.Namespace) -> int:
    """특정 컴프의 아이템 부품 수급 분석(단독 실행)."""
    book = _load_item_book(args)
    if book is None:
        return 2
    comps = comp_module.load_comps(args.comps)
    target = comps_by_name(comps, args.comp_name)
    if args.comp_index:
        index = int(args.comp_index)
        if not 1 <= index <= len(comps):
            print(f"[입력 오류] --comp-index 는 1~{len(comps)} 범위여야 합니다.")
            return 2
        target = comps[index - 1]
    if target is None:
        names = ", ".join(comp.name for comp in comps)
        print(f"[입력 오류] '{args.comp_name}' 컴프가 없습니다. 있는 컴프: {names}")
        return 2
    if not target.core_items:
        print(f"[데이터 없음] '{target.name}' 에 코어 아이템(items.core) 정보가 없습니다.")
        return 2

    have = dict(items.parse_component_spec(args.components or ""))
    readiness, error = _item_readiness(
        book,
        target,
        have=have,
        future_components=args.future_components,
        choice_components=args.choice_components,
        core_items_limit=args.core_items_limit,
    )
    if error or readiness is None:
        print(f"[조합식 미확인] {error}")
        return 2

    print(f"=== 아이템 부품 수급: {target.name} ===")
    print(f"조합식 출처: {book.source}")
    core = items.comp_core_items(target.core_items, limit=args.core_items_limit)
    print(f"코어 아이템({len(core)}개, 우선순위 순): {', '.join(core)}")
    print(f"필요 부품: {', '.join(f'{k} x{v}' for k, v in readiness.required.items())}")
    if readiness.have:
        print(f"보유 부품: {', '.join(f'{k} x{v}' for k, v in readiness.have.items())}")
    if readiness.missing_now:
        print(
            "지금 부족: "
            + ", ".join(f"{k} x{v}" for k, v in readiness.missing_now.items())
        )
        print(
            "부품 우선순위(캐러셀/모루에서 이걸 집는다): "
            + " > ".join(f"{k} x{v}" for k, v in readiness.priority)
        )
    else:
        print("지금 부족한 부품 없음 -> 아이템 준비 완료")
    print(
        f"앞으로 부품 {readiness.future_components}개(+선택 {readiness.choice_components}개)를 "
        f"받으면 전부 완성될 확률: {readiness.p_ready * 100:.1f}%"
    )
    print(
        f"그때도 평균 {readiness.expected_shortfall_after:.2f}개 부품이 부족하다 "
        "(가정: 무작위 부품은 8종 균등, 선택 부품은 아무 부족분이나 메움)"
    )
    return 0


def cmd_comp(args: argparse.Namespace) -> int:
    """컴프(덱) 단위 비용/효율 랭킹 — '어떤 덱이 가장 싸게 완성되는가'."""
    odds = build_odds(args)
    snapshot = lobby.LobbySnapshot.from_json(args.snapshot)
    copies_in_play, tier_in_play = comp_module.pool_state_from_snapshot(snapshot)
    comps = comp_module.load_comps(args.comps)
    book = _load_item_book(args)
    has_item_input = _item_input_given(args)

    count_passive = args.levelup_rounds > 0
    use_gold_total = args.gold is not None
    if not use_gold_total and args.budget is None:
        print("[입력 오류] --gold(총 보유 골드) 또는 --budget(롤 전용 예산) 중 하나가 필요합니다.")
        return 2

    ranking = comp_module.rank_comps(
        odds,
        comps=comps,
        owned_by_champion=snapshot.my_copies_map(),
        copies_in_play=copies_in_play,
        tier_in_play=tier_in_play,
        level=args.level,
        gold_total=args.gold,
        roll_budget=args.budget,
        current_level=args.levelup_from,
        levelup_rounds=args.levelup_rounds,
        trials=args.trials,
    )

    print("=== 컴프(덱) 효율 랭킹: 같은 골드로 무엇이 가장 싸게 완성되는가 ===")
    if use_gold_total:
        print(
            f"총 보유 골드 {args.gold}골드 / 컴프별 롤 레벨 사용 / "
            f"동시 완성 시뮬레이션(상점 5칸 공유) / {set_data.SET_NAME}"
        )
        print(
            "정산: 총 골드 - 레벨업 비용 = 롤·구매 예산. "
            "레벨이 다른 컴프(리롤 vs fast-8)를 같은 조건에서 비교한다."
        )
    else:
        print(
            f"롤·구매 예산 {args.budget}골드 (기본 Lv{args.level}) / "
            f"동시 완성 시뮬레이션 / {set_data.SET_NAME}"
        )
    print(f"상점 확률 소스: {odds.source}   (가정값이면 결과를 신뢰하지 말 것)")
    if args.levelup_from is not None:
        print(
            f"현재 레벨 Lv{args.levelup_from} -> 컴프별 목표 레벨까지 XP 골드 계산"
            + (
                f" (패시브 XP {args.levelup_rounds}라운드 반영)"
                if count_passive
                else " (패시브 XP 미반영: 보수적 상한)"
            )
        )
    print("기대총골드 = 레벨업 + 리롤 + 구매 (즉 '이 덱을 완성하는 데 드는 총 골드')")
    print("성공시 = 실제로 완성했을 때의 평균 소모. '-' 는 성공 사례가 없다는 뜻(사실상 불가).")
    print(
        "아이템 = 지금+앞으로 받을 부품으로 '코어 아이템'이 다 맞을 확률. "
        "결합 = 유닛 완성확률 x 아이템 확률(두 조건이 모두 성립할 확률, 독립 가정)."
    )
    header = (
        f"{render.pad('순위', 4, '>')} {render.pad('컴프', 22)}"
        f"{render.pad('Lv', 3, '>')}{render.pad('유닛', 4, '>')}"
        f"{render.pad('동시완성', 9, '>')}{render.pad('아이템', 8, '>')}"
        f"{render.pad('결합', 8, '>')}"
        f"{render.pad('기대총골드', 10, '>')}{render.pad('성공시', 9, '>')}"
        f"{render.pad('레벨업', 8, '>')}{render.pad('리롤', 7, '>')}"
        f"{render.pad('구매', 7, '>')}  비고"
    )
    print(header)
    print("-" * render.disp_len(header))
    have = dict(items.parse_component_spec(args.components or ""))
    for index, row in enumerate(ranking, start=1):
        if row.get("error"):
            print(
                f"{index:>4} {render.pad(render.trunc(str(row['comp']), 22), 22)}"
                f"{'':>3}{'':>4}{'':>9}{'':>8}{'':>8}"
                f"{'':>10}{'':>9}{'':>8}{'':>7}{'':>7}  [데이터 부족 - 확률표 채우면 계산됨]"
            )
            continue
        note = ""
        if row["impossible"]:
            note = f"[불가] 풀 부족: {', '.join(row['impossible'])}"
        elif not row["verified"]:
            note = "[미검증 컴프 데이터]"
        comp_obj = comps_by_name(comps, str(row["comp"]))
        readiness, item_error = (
            _item_readiness(
                book,
                comp_obj,
                have=have,
                future_components=args.future_components,
                choice_components=args.choice_components,
                core_items_limit=args.core_items_limit,
            )
            if comp_obj is not None
            else (None, None)
        )
        item_text, joint_text = render.item_cells(
            readiness,
            p_complete=float(row["p_complete"]),
            has_input=has_item_input,
        )
        if item_error:
            note = (note + " " if note else "") + "[조합식 미확인]"
        success_gold = row.get("mean_gold_on_success")
        success_text = (
            f"{float(success_gold):.1f}g" if success_gold is not None else "-"
        )
        print(
            f"{index:>4} {render.pad(render.trunc(str(row['comp']), 22), 22)}"
            f"{int(row['level']):>3}"
            f"{int(row['unit_count']):>4}"
            f"{render.pct_fmt(float(row['p_complete']), 9)}"
            f"{item_text}{joint_text}"
            f"{float(row['mean_total_gold']):>9.1f}g"
            f"{success_text:>9}"
            f"{float(row['levelup_gold']):>7.1f}g"
            f"{float(row['mean_roll_gold']):>6.1f}g"
            f"{float(row['mean_purchase_gold']):>6.1f}g  {note}"
        )
    if not has_item_input:
        print(
            "  (부품 미입력 -> 아이템 확률 대신 '필요 부품 수'만 표시. "
            "--components/--future-components 로 확률을 계산한다)"
        )
    print()
    return _print_comp_breakdown(
        args, odds, snapshot, copies_in_play, tier_in_play, comps, ranking
    )


def _print_comp_breakdown(
    args: argparse.Namespace,
    odds: ShopOdds,
    snapshot: "lobby.LobbySnapshot",
    copies_in_play: dict[str, int],
    tier_in_play: dict[int, int],
    comps: list["comp_module.Comp"],
    ranking: list[dict[str, object]],
) -> int:
    """1위 컴프를 유닛별로 분해해 '격리 vs 동시' 차이를 보여준다."""
    best = next((row for row in ranking if not row.get("error")), None)
    if best is None:
        print("[결론] 계산 가능한 컴프가 없다. 확률표/컴프 데이터를 채워 넣어야 한다.")
        return 0
    if best["impossible"]:
        print(
            f"[결론] 1순위 {best['comp']} 는 풀 부족으로 불가: "
            f"{', '.join(best['impossible'])}. 다른 라인이 더 현실적이다."
        )
        return 0

    print(f"--- 1위 컴프 분해: {best['comp']} ---")
    comp_obj = comps_by_name(comps, str(best["comp"]))
    comp_level = comp_obj.level_for(args.level) if comp_obj else args.level
    unit_map = {unit.champion: unit for unit in comps_units(comps, str(best["comp"]))}
    if comp_obj is not None and comp_obj.source:
        print(f"구성 출처: {comp_obj.source}")
    if comp_obj is not None and comp_obj.notes:
        print(f"메모: {comp_obj.notes}")
    print(
        f"롤 레벨 Lv{comp_level} / 롤·구매 예산 {int(best['roll_budget'])}골드 / "
        f"레벨업 {float(best['levelup_gold']):.0f}골드 "
        f"(격리 계산도 같은 레벨로 맞춰 비교)"
    )
    for champion, completion in sorted(
        best["unit_completion"].items(), key=lambda item: item[1]
    ):
        unit = unit_map.get(champion)
        isolated_text = "-"
        if unit is not None:
            isolated = comp_module.unit_outlook(
                odds,
                unit=unit,
                owned_copies=snapshot.my_copies(champion),
                copies_in_play=copies_in_play,
                tier_in_play=tier_in_play,
                level=comp_level,
                roll_budget=int(best["roll_budget"]),
                trials=args.trials,
            )
            isolated_text = (
                f"{float(isolated[f'p_star{unit.target_star}']) * 100:.1f}%"
            )
        print(
            f"  {champion:<16} 목표 {unit.target_star if unit else '?'}성  "
            f"격리 {isolated_text:>7}  ->  동시 {render.pct_fmt(float(completion), 7)}"
        )
    print()
    print(
        "[읽는 법] '격리'는 그 유닛만 골드를 몰아줬을 때, '동시'는 같은 골드를 컴프 "
        "전체가 나눠 썼을 때다. 차이가 크면 컴프가 너무 크거나 경쟁이 심한 유닛이 섞였다는 뜻."
    )
    print(
        "[범위 밖] 증강 상성, 포지션, 상대 조합 상성은 계산하지 않는다. "
        "아이템은 '부품 수급'까지만 모델링하고(코어 아이템이 다 맞을 확률), "
        "실제 드랍/캐러셀 선택은 --components/--future-components/--choice-components 로 입력한다. "
        "증강 승률/평균등수 지표는 Riot 정책상 표시 금지라 넣지 않았다."
    )
    return 0


def cmd_robustness(args: argparse.Namespace) -> int:
    odds = build_odds(args)
    scan = decision.robustness_scan(
        odds,
        level=args.level,
        unit_cost=args.cost,
        own_copies=args.own,
        others_copies=args.others,
        tolerance=args.tolerance,
        target_star=args.target_star,
        budget=args.budget,
        commit_threshold=args.commit_threshold,
        tier_in_play=args.tier_in_play,
        trials=args.trials,
    )
    print(f"=== 인식/입력 오차 내성 검사 (상대 보유 ±{scan['tolerance']}장) ===")
    print(
        f"조건: 내 {args.own}장 / {args.cost}코 {args.target_star}성 / "
        f"Lv{args.level} / 예산 {args.budget}골드 / 등급 소모 {scan['tier_in_play']}장"
    )
    if scan["tier_assumed"]:
        # cmd_unit 이 같은 가정을 [가정] 으로 알리는 것과 맞춘다. 오차 내성 검사가
        # 하는 일이 '가정이 결론을 뒤집는가' 인데, 정작 이 가정은 검사 밖에 있었다.
        print(
            "[가정] 같은 코스트의 다른 기물은 아무도 안 들고 있다고 가정했다 "
            "(등급 소모 = 내 보유 + 상대 보유). --tier-in-play 로 정확히 줄 수 있다."
        )
    header = (
        f"{render.pad('상대보유', 8, '>')} {render.pad('남은사본', 8, '>')} "
        f"{render.pad('1상점', 7, '>')} "
        f"{render.pad('예산내완성', 10, '>')} {render.pad('기대총골드', 10, '>')}  결론"
    )
    print(header)
    print("-" * render.disp_len(header))
    for row in scan["rows"]:
        print(
            f"{row['others']:>8} {row['remaining_target']:>8} "
            f"{float(row['p_shop']) * 100:>6.1f}% "
            f"{float(row['p_complete']) * 100:>9.1f}% "
            f"{float(row['mean_total_gold']):>9.1f}g  {row['verdict']}"
        )
    print()
    if scan["stable"]:
        print(
            f"[판정] 오차 범위 안에서 결론이 유지된다: {scan['verdicts'][0]}. "
            "지금 판단해도 된다."
        )
    else:
        print(f"[판정] 오차에 따라 결론이 뒤집힌다: {' / '.join(scan['verdicts'])}")
        print(
            "       -> 경계 케이스다. 남은 사본을 한 번 더 확인(대기석 포함)한 뒤 "
            "판단해야 한다. 원시 확률은 오차에 민감해도 결론은 안정적일 수 있고, "
            "그 반대도 가능하므로 이 표를 반드시 함께 본다."
        )
    print(
        f"[표시 규칙] 예산 내 완성 확률 "
        f"{float(scan['commit_threshold']) * 100:.0f}% 미만이면 '전환 검토'로 표시한다. "
        "이 임계값은 사용자가 정하는 표시 규칙이며 과학적 상수가 아니다."
    )
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """라운드 수입/롤 타이밍 계획 + (옵션) 그 시점 예산으로 컴프 판정."""
    start = economy.parse_round(args.round)
    target = (
        economy.parse_round(args.target_round)
        if args.target_round
        else economy.round_sequence(start, args.rounds)[-1]
    )
    # 목표를 반드시 담도록 길이를 정한다. --rounds 는 최소 길이로 보장된다.
    horizon = economy.projection_horizon(start, target, args.rounds)
    state = economy.EconomyState(
        gold=args.gold, level=args.level, streak=args.streak,
        stage=start[0], round=start[1],
    )
    plans = economy.parse_level_plan(args.levelup) if args.levelup else []
    projection = economy.project(
        state,
        rounds=horizon,
        level_plans=plans,
        win_rate=args.win_rate,
        pve_gold=args.pve_gold,
        streak_behavior=args.streak_behavior,
    )

    print("=== 라운드 수입 / 롤 타이밍 계획 ===")
    print(
        f"현재 {args.round} / {args.gold}골드 / Lv{args.level} / "
        f"스트릭 {args.streak:+d} / {horizon}라운드 전망"
    )
    for note in projection.notes:
        print(f"  - {note}")
    header = (
        f"{render.pad('라운드', 6, '>')}{render.pad('유형', 9, '>')}"
        f"{render.pad('기본', 5, '>')}{render.pad('이자', 5, '>')}"
        f"{render.pad('스트릭', 7, '>')}{render.pad('승리', 6, '>')}"
        f"{render.pad('PvE', 5, '>')}"
        f"{render.pad('수입', 7, '>')}{render.pad('레벨업', 7, '>')}"
        f"{render.pad('종료골드', 9, '>')}{render.pad('롤예산', 8, '>')}"
        f"{render.pad('레벨', 5, '>')}"
    )
    print(header)
    print("-" * render.disp_len(header))
    for row in projection.rounds:
        print(
            f"{economy.format_round(row.stage, row.round):>6}{row.kind:>9}"
            f"{row.base:>5}{row.interest_gold:>5}{row.streak_gold:>7}"
            f"{row.win_gold:>6.1f}{row.pve_gold:>5}"
            f"{row.income:>7.1f}{row.levelup_spend:>7}"
            f"{row.gold_end:>9}{row.roll_budget:>8}{row.target_level:>5}"
        )

    summary = projection.summary()
    print(
        f"\n요약: {summary['start']} -> {summary['end']} / "
        f"총수입 {summary['total_income']}골드 / 총 레벨업 지출 {summary['total_spend']}골드 / "
        f"최종 {summary['gold_end']}골드 Lv{summary['level_end']}"
    )

    row = projection.at(*target)
    if row is None:
        # economy.projection_horizon 이 목표를 담도록 보장하므로 사실상 도달 불가다.
        print(
            f"\n[목표 라운드] {economy.format_round(*target)} 는 전망({horizon}라운드)에 "
            "없다. --rounds 를 늘리세요."
        )
        return 0
    print(
        f"\n[{economy.format_round(*target)} 시점] 보유 {row.gold_end}골드 / Lv{row.target_level} / "
        f"리롤·구매 예산 {row.roll_budget}골드"
    )
    if args.need_gold:
        need = int(args.need_gold)
        verdict = "충족" if row.roll_budget >= need else "부족"
        print(
            f"[필요 골드 판정] 필요 {need}골드 vs 예산 {row.roll_budget}골드 -> {verdict}"
            + (
                ""
                if row.roll_budget >= need
                else f" ({need - row.roll_budget}골드 부족: 세이빙 라운드를 늘리거나 목표를 낮춰야 한다)"
            )
        )

    if args.comps:
        return _plan_comp_check(args, projection, target)
    return 0


def _plan_comp_check(
    args: argparse.Namespace,
    projection: "economy.Projection",
    target: tuple[int, int],
) -> int:
    """목표 라운드의 리롤 예산으로 각 컴프가 되는지 계산한다."""
    row = projection.at(*target)
    if row is None:
        return 0
    odds = build_odds(args)
    snapshot = lobby.LobbySnapshot.from_json(args.snapshot)
    copies_in_play, tier_in_play = comp_module.pool_state_from_snapshot(snapshot)
    comps = comp_module.load_comps(args.comps)
    book = _load_item_book(args)
    has_item_input = _item_input_given(args)

    print(
        f"\n=== {economy.format_round(*target)} 예산 {row.roll_budget}골드로 컴프 판정 "
        f"(Lv{row.target_level}, 레벨업 비용은 이미 반영됨) ==="
    )
    ranking = comp_module.rank_comps(
        odds,
        comps=comps,
        owned_by_champion=snapshot.my_copies_map(),
        copies_in_play=copies_in_play,
        tier_in_play=tier_in_play,
        level=row.target_level,
        gold_total=row.roll_budget,
        current_level=row.target_level,  # 레벨업은 계획에서 이미 끝났다
        levelup_rounds=0,
        trials=args.trials,
    )
    have = dict(items.parse_component_spec(args.components or ""))
    header = (
        f"{render.pad('순위', 4, '>')} {render.pad('컴프', 22)}"
        f"{render.pad('Lv', 3, '>')}{render.pad('유닛', 4, '>')}"
        f"{render.pad('동시완성', 9, '>')}{render.pad('아이템', 8, '>')}"
        f"{render.pad('결합', 8, '>')}  비고"
    )
    print(header)
    print("-" * render.disp_len(header))
    for index, comp_row in enumerate(ranking, start=1):
        if comp_row.get("error"):
            print(f"{index:>4} {render.pad(render.trunc(str(comp_row['comp']), 22), 22)}  [데이터 부족]")
            continue
        comp_obj = comps_by_name(comps, str(comp_row["comp"]))
        readiness, _ = (
            _item_readiness(
                book,
                comp_obj,
                have=have,
                future_components=args.future_components,
                choice_components=args.choice_components,
                core_items_limit=args.core_items_limit,
            )
            if comp_obj is not None
            else (None, None)
        )
        item_text, joint_text = render.item_cells(
            readiness,
            p_complete=float(comp_row["p_complete"]),
            has_input=has_item_input,
        )
        note = ""
        if comp_row["impossible"]:
            note = f"[불가] 풀 부족: {', '.join(comp_row['impossible'])}"
        print(
            f"{index:>4} {render.pad(render.trunc(str(comp_row['comp']), 22), 22)}"
            f"{int(comp_row['level']):>3}"
            f"{int(comp_row['unit_count']):>4}"
            f"{render.pct_fmt(float(comp_row['p_complete']), 9)}"
            f"{item_text}{joint_text}  {note}"
        )
    print(
        "  (예산 = 그 라운드 보유 골드 - 레벨업 지출. 실제 게임에서는 상대 템포·체력까지 보고 조정한다)"
    )
    return 0


def cmd_survive(args: argparse.Namespace) -> int:
    """체력/피해 축: 세이빙 리스크와 '지금 안정화 vs 세이빙' 비교."""
    start = economy.parse_round(args.round)
    target = (
        economy.parse_round(args.target_round)
        if args.target_round
        else economy.round_sequence(start, args.rounds)[-1]
    )
    # 목표 라운드까지의 라운드 수(범위 밖이면 오류). 예전의 30/40 마법 숫자 두개를
    # economy.rounds_between(MAX_HORIZON) 한곳으로 모았다.
    horizon = economy.projection_horizon(start, target, args.rounds)

    print("=== 체력/피해(생존) 분석 ===")
    print(
        f"현재 {args.round} / {args.hp}HP / 승률 {args.win_rate:.0%} / "
        f"패배 시 잔존 유닛 {args.enemy_survivors:.1f} / 목표 {economy.format_round(*target)}"
    )
    print(
        f"  지금 체력으로 감당 가능한 패배 횟수(근사): "
        f"{survival.losses_survivable(args.hp, start[0], enemy_survivors=int(args.enemy_survivors))}회"
    )

    result = survival.simulate_survival(
        args.hp,
        start,
        rounds=horizon,
        win_rate=args.win_rate,
        enemy_survivors=args.enemy_survivors,
        survivors_sd=args.survivors_sd,
        pve_damage=args.pve_damage,
        trials=args.trials,
    )
    for note in result.notes:
        print(f"  - {note}")
    header = (
        f"{render.pad('라운드', 6, '>')}{render.pad('유형', 9, '>')}"
        f"{render.pad('기본피해', 9, '>')}{render.pad('기대피해', 9, '>')}"
        f"{render.pad('기대체력', 9, '>')}{render.pad('생존확률', 9, '>')}"
    )
    print(header)
    print("-" * render.disp_len(header))
    for row in result.rounds:
        print(
            f"{economy.format_round(row.stage, row.round):>6}{row.kind:>9}"
            f"{row.base:>9}{row.expected_damage:>9.1f}"
            f"{row.expected_hp:>9.1f}{render.pct_fmt(row.p_alive, 9)}"
        )
    summary = result.summary()
    print(
        f"\n[{summary['end_round']}] 생존확률 {float(summary['p_alive_end']) * 100:.1f}% / "
        f"기대 체력 {summary['expected_hp_end']}HP"
        + (
            f" / 기대 사망 라운드 {summary['expected_death_round']}"
            if summary["expected_death_round"]
            else " / 이 구간 내 사망 없음"
        )
    )

    if args.roll_gold:
        print("\n=== 지금 안정화(롤) vs 그대로 세이빙 ===")
        save_outcome = _strategy_outcome(
            name="세이빙 유지",
            win_rate=args.win_rate,
            spend_now=0,
            args=args,
            start=start,
            target=target,
            horizon=horizon,
            trials=args.trials,
        )
        stabilize_outcome = _strategy_outcome(
            name=f"지금 {args.roll_gold}골드 롤",
            win_rate=args.win_rate_roll,
            spend_now=args.roll_gold,
            args=args,
            start=start,
            target=target,
            horizon=horizon,
            trials=args.trials,
        )
        comparison = survival.compare_stabilize_vs_save(
            save=save_outcome, stabilize=stabilize_outcome
        )
        for outcome in comparison.outcomes:
            print(
                f"  {outcome.name:<18} 승률 {outcome.win_rate:.0%} / "
                f"생존 {outcome.p_survive * 100:5.1f}% / "
                f"기대 체력 {outcome.expected_hp:5.1f} / "
                f"{economy.format_round(*target)} 골드 {outcome.gold_at_target}"
            )
        print(f"  판정: {comparison.verdict}")
        print(f"  {comparison.exchange}")
        print("  결론에 필요한데 아직 없는 정보:")
        for item in comparison.missing_inputs:
            print(f"    - {item}")
    return 0


def _strategy_outcome(
    *,
    name: str,
    win_rate: float,
    spend_now: int,
    args: argparse.Namespace,
    start: tuple[int, int],
    target: tuple[int, int],
    horizon: int,
    trials: int,
) -> "survival.StrategyOutcome":
    """전략 하나의 (**목표 라운드** 생존확률, 목표 라운드 골드)를 계산한다.

    지표는 항상 목표 라운드 기준이어야 한다. ``horizon`` 은 ``--rounds`` 때문에
    목표보다 길어질 수 있는데, 그때 ``rounds[-1]`` 을 쓰면 목표가 아닌 라운드의
    값을 "목표 시점" 라벨로 표시하게 된다(필드명이 ``gold_at_target`` 인데도).
    """
    result = survival.simulate_survival(
        args.hp,
        start,
        rounds=horizon,
        win_rate=win_rate,
        enemy_survivors=args.enemy_survivors,
        survivors_sd=args.survivors_sd,
        pve_damage=args.pve_damage,
        trials=trials,
    )
    state = economy.EconomyState(
        gold=args.gold,
        level=args.level,
        streak=args.streak,
        stage=start[0],
        round=start[1],
    )
    spends = {start: spend_now} if spend_now else None
    projection = economy.project(
        state,
        rounds=horizon,
        extra_spends=spends,
        win_rate=win_rate,
        pve_gold=args.pve_gold,
    )
    target_row = projection.at(*target)
    survival_row = next(
        (row for row in result.rounds if (row.stage, row.round) == target), None
    )
    if target_row is None or survival_row is None:
        # economy.projection_horizon 이 목표를 담도록 보장하므로 사실상 도달 불가다.
        raise ValueError(
            f"목표 라운드 {economy.format_round(*target)} 가 전망({horizon}라운드)에 없다."
        )
    return survival.StrategyOutcome(
        name=name,
        win_rate=win_rate,
        spend_now=spend_now,
        p_survive=survival_row.p_alive,
        expected_hp=survival_row.expected_hp,
        gold_at_target=target_row.gold_end,
    )


def cmd_report(args: argparse.Namespace) -> int:
    """A~E 통합 리포트: 현재 상태 하나로 4축(유닛·아이템·골드·체력)을 한 화면에."""
    start = economy.parse_round(args.round)
    target = (
        economy.parse_round(args.target_round)
        if args.target_round
        else economy.round_sequence(start, args.rounds)[-1]
    )
    horizon = economy.projection_horizon(start, target, args.rounds)
    target_label = economy.format_round(*target)

    print("=" * 74)
    print("TFT 통합 리포트 — 유닛(풀) · 아이템(부품) · 골드(시간) · 체력(생존)")
    print("=" * 74)

    # ── [1] 현재 상태 ────────────────────────────────────────────────
    snapshot = None
    if getattr(args, "scan", False):
        snapshot = _scan_snapshot(args)
        if snapshot is None:
            return 2
    elif args.snapshot:
        snapshot = lobby.LobbySnapshot.from_json(args.snapshot)
    have = dict(items.parse_component_spec(args.components or ""))
    survivable = survival.losses_survivable(
        args.hp, start[0], enemy_survivors=int(args.enemy_survivors)
    )
    print(
        f"\n[1] 현재 상태: {args.round} / {args.gold}골드 / Lv{args.level} / "
        f"{args.hp}HP / 스트릭 {args.streak:+d}"
    )
    print(f"    지금 체력으로 감당 가능한 패배(근사): {survivable}회")
    if snapshot is not None:
        print(f"    로비: {snapshot.confidence_note()}")
    else:
        print("    로비: 스냅샷 없음(--snapshot 미지정) -> 컴프 판정 생략")
    if have:
        print("    부품: " + ", ".join(f"{key} x{value}" for key, value in have.items()))
    else:
        print("    부품: 미입력(--components) -> 아이템 축은 계산만 하고 확률은 표시하지 않음")

    # ── [2] 골드 전망 ───────────────────────────────────────────────
    plans = economy.parse_level_plan(args.levelup) if args.levelup else []
    state = economy.EconomyState(
        gold=args.gold, level=args.level, streak=args.streak, stage=start[0], round=start[1]
    )
    projection = economy.project(
        state,
        rounds=horizon,
        level_plans=plans,
        win_rate=args.win_rate,
        pve_gold=args.pve_gold,
    )
    print(f"\n[2] 골드 전망: {args.round} -> {target_label} (승률 {args.win_rate:.0%} 가정)")
    header = (
        f"{render.pad('라운드', 7, '>')}{render.pad('유형', 9, '>')}"
        f"{render.pad('수입', 7, '>')}{render.pad('레벨업', 7, '>')}"
        f"{render.pad('종료골드', 9, '>')}{render.pad('롤예산', 8, '>')}"
        f"{render.pad('레벨', 5, '>')}"
    )
    print(header)
    print("-" * render.disp_len(header))
    for row in projection.rounds:
        print(
            f"{economy.format_round(row.stage, row.round):>7}{row.kind:>9}"
            f"{row.income:>7.1f}{row.levelup_spend:>7}"
            f"{row.gold_end:>9}{row.roll_budget:>8}{row.target_level:>5}"
        )
    target_row = projection.at(*target)
    if target_row is None:
        print("  (목표 라운드가 범위 밖입니다. --rounds 를 늘리세요.)")
        return 2

    # ── [3] 체력/생존 ──────────────────────────────────────────────
    surv = survival.simulate_survival(
        args.hp,
        start,
        rounds=horizon,
        win_rate=args.win_rate,
        enemy_survivors=args.enemy_survivors,
        survivors_sd=args.survivors_sd,
        pve_damage=args.pve_damage,
        trials=args.trials,
    )
    print(f"\n[3] 생존 전망 (피해 = 기본 {start[0]}스테이지 {survival.base_damage(start[0])} + 잔존 유닛)")
    header = (
        f"{render.pad('라운드', 7, '>')}{render.pad('유형', 9, '>')}"
        f"{render.pad('기대피해', 9, '>')}{render.pad('기대체력', 9, '>')}"
        f"{render.pad('생존확률', 9, '>')}"
    )
    print(header)
    print("-" * render.disp_len(header))
    for row in surv.rounds:
        print(
            f"{economy.format_round(row.stage, row.round):>7}{row.kind:>9}"
            f"{row.expected_damage:>9.1f}{row.expected_hp:>9.1f}{render.pct_fmt(row.p_alive, 9)}"
        )
    target_survival = next(
        (row for row in surv.rounds if (row.stage, row.round) == target), None
    )
    if target_survival is None:
        # economy.projection_horizon 이 목표를 담도록 보장하므로 사실상 도달 불가다.
        # 예전엔 `p_alive_at(*target) or 0.0` 이라서 목표가 범위 밖이면
        # "생존확률 0.0%" 라는 거짓이, 그리고 다음 줄의 `rounds[-1]` 은 horizon
        # 마지막 라운드의 값을 목표 라벨로 보여줬다.
        raise ValueError(
            f"목표 {target_label} 가 생존 전망({horizon}라운드)에 없다. --rounds 를 늘리세요."
        )
    p_survive_target = target_survival.p_alive
    print(
        f"  -> {target_label} 생존확률 {p_survive_target * 100:.1f}% "
        f"(기대 체력 {target_survival.expected_hp:.1f}HP)"
    )
    return _report_decision(
        args,
        snapshot=snapshot,
        have=have,
        target=target,
        target_row=target_row,
        p_survive_target=p_survive_target,
        horizon=horizon,
        start=start,
    )


def _report_decision(
    args: argparse.Namespace,
    *,
    snapshot: "lobby.LobbySnapshot | None",
    have: dict[str, int],
    target: tuple[int, int],
    target_row: "economy.RoundProjection",
    p_survive_target: float,
    horizon: int,
    start: tuple[int, int],
) -> int:
    """[4] 컴프 판정 + [5] 권장 동선 + [6] 불확실성."""
    target_label = economy.format_round(*target)
    book = _load_item_book(args)
    has_item_input = _item_input_given(args)
    ranking: list[dict[str, object]] | None = None
    odds_source = "?"
    best: dict[str, object] | None = None

    if snapshot is not None and args.comps:
        odds = build_odds(args)
        odds_source = odds.source
        copies_in_play, tier_in_play = comp_module.pool_state_from_snapshot(snapshot)
        comps = comp_module.load_comps(args.comps)
        ranking = comp_module.rank_comps(
            odds,
            comps=comps,
            owned_by_champion=snapshot.my_copies_map(),
            copies_in_play=copies_in_play,
            tier_in_play=tier_in_play,
            level=target_row.target_level,
            gold_total=target_row.roll_budget,
            current_level=target_row.target_level,
            levelup_rounds=0,
            trials=args.trials,
        )
        print(
            f"\n[4] 컴프 판정: {target_label} 예산 {target_row.roll_budget}골드 / "
            f"Lv{target_row.target_level} / 상점 확률 소스 {odds_source}"
        )
        header = (
            f"{render.pad('순위', 4, '>')} {render.pad('컴프', 22)}"
            f"{render.pad('유닛', 4, '>')}{render.pad('동시완성', 9, '>')}"
            f"{render.pad('아이템', 8, '>')}{render.pad('결합', 8, '>')}  비고"
        )
        print(header)
        print("-" * render.disp_len(header))
        for index, row in enumerate(ranking[: args.top], start=1):
            if row.get("error"):
                print(f"{index:>4} {render.pad(render.trunc(str(row['comp']), 22), 22)}  [데이터 부족]")
                continue
            comp_obj = comps_by_name(comps, str(row["comp"]))
            readiness, _ = (
                _item_readiness(
                    book,
                    comp_obj,
                    have=have,
                    future_components=args.future_components,
                    choice_components=args.choice_components,
                    core_items_limit=args.core_items_limit,
                )
                if comp_obj is not None
                else (None, None)
            )
            item_text, joint_text = render.item_cells(
                readiness,
                p_complete=float(row["p_complete"]),
                has_input=has_item_input,
            )
            note = ""
            if row["impossible"]:
                note = f"[불가] 풀 부족: {', '.join(row['impossible'])}"
            print(
                f"{index:>4} {render.pad(render.trunc(str(row['comp']), 22), 22)}"
                f"{int(row['unit_count']):>4}"
                f"{render.pct_fmt(float(row['p_complete']), 9)}{item_text}{joint_text}  {note}"
            )
        if has_item_input:
            print("  (아이템 = 지금+앞으로 부품으로 코어 아이템 완성 확률, 결합 = 유닛 x 아이템)")
        else:
            print("  (부품 미입력 -> 아이템 확률 대신 '필요 부품 수'만 표시)")
        best = next((row for row in ranking if not row.get("error")), None)
    else:
        print("\n[4] 컴프 판정: 스냅샷(--snapshot) 또는 컴프(--comps) 없음 -> 생략")
    return _report_action(
        args,
        target=target,
        target_label=target_label,
        target_row=target_row,
        p_survive_target=p_survive_target,
        best=best,
        ranking=ranking,
        odds_source=odds_source,
        snapshot=snapshot,
        horizon=horizon,
        start=start,
    )


def _report_action(
    args: argparse.Namespace,
    *,
    target: tuple[int, int],
    target_label: str,
    target_row: "economy.RoundProjection",
    p_survive_target: float,
    best: dict[str, object] | None,
    ranking: list[dict[str, object]] | None,
    odds_source: str,
    snapshot: "lobby.LobbySnapshot | None",
    horizon: int,
    start: tuple[int, int],
) -> int:
    """[5] 권장 동선 + [6] 불확실성 출력."""
    comparison = None
    if args.roll_gold:
        save_outcome = _strategy_outcome(
            name="세이빙 유지",
            win_rate=args.win_rate,
            spend_now=0,
            args=args,
            start=start,
            target=target,
            horizon=horizon,
            trials=args.trials,
        )
        stabilize_outcome = _strategy_outcome(
            name=f"지금 {args.roll_gold}골드 롤",
            win_rate=args.win_rate_roll,
            spend_now=args.roll_gold,
            args=args,
            start=start,
            target=target,
            horizon=horizon,
            trials=args.trials,
        )
        comparison = survival.compare_stabilize_vs_save(
            save=save_outcome, stabilize=stabilize_outcome
        )

    # 판정과 근거는 rules.py 에 산다(순수 함수라 단독 테스트가 된다).
    basis = rules.build_basis(
        target_label=target_label,
        roll_budget=target_row.roll_budget,
        target_level=target_row.target_level,
        p_survive_target=p_survive_target,
        best=best,
        need_gold=args.need_gold,
        comparison=comparison,
    )
    action = rules.recommend_action(
        target_label=target_label,
        roll_gold=args.roll_gold,
        need_gold=args.need_gold,
        roll_budget=target_row.roll_budget,
        p_survive_target=p_survive_target,
        best=best,
        comparison=comparison,
    )

    print(f"\n[5] 권장 동선(규칙 기반): {action}")
    for line in basis:
        print(f"    근거: {line}")
    if comparison is not None:
        print(f"    교환비율: {comparison.exchange.replace('교환비율: ', '')}")

    print("\n[6] 이 결론의 불확실성")
    print(
        "    - 로비 신뢰도: "
        + (snapshot.confidence_note() if snapshot is not None else "스냅샷 없음")
    )
    if ranking is not None:
        print(f"    - 상점 확률표: {odds_source} (가정값이면 절대 수치를 믿지 말 것)")
    print(f"    - 승률 {args.win_rate:.0%} 는 입력값(실측 캘리브레이션 전)")
    print("    ※ 정답이 아니라 네 축의 사실과 불확실성을 한 화면에 모은 것이다.")
    return 0


def _parse_star_spec(spec: str | None) -> dict[str, int]:
    """'Ahri=2,Krug=3' -> {'ahri': 2, 'krug': 3}"""
    stars: dict[str, int] = {}
    if not spec:
        return stars
    for pair in spec.split(","):
        name, _, value = pair.partition("=")
        if not value.strip():
            raise ValueError(f"성급 지정 형식 오류: '{pair}' (예: Ahri=2)")
        stars[name.strip().lower()] = int(value)
    return stars


def _load_or_capture(
    source: str | None, window: str | None = None
) -> "screen.Image | None":
    """BMP 가 있으면 그걸, ``window`` 가 있으면 그 창의 **클라이언트 영역**, 아니면 전체 화면.

    창모드로 게임을 띄우면 전체 화면 캡처에는 게임이 화면 일부만 차지하므로 비율
    좌표가 어긋난다. ``--window`` 는 클라이언트 영역만 잘라 내므로 비율 좌표가 그대로
    통한다(16:9 창이면 해상도가 달라도 동일).
    """
    if source:
        return screen.load_bmp(source)
    if not screen.is_supported():
        print("[오류] 자동 캡처는 Windows(GDI)에서만 됩니다. --in <BMP> 로 테스트하세요.")
        return None
    if window:
        image = screen.capture_client(window)
        if image is None:
            print(
                f"[입력 오류] 창을 찾지 못했습니다: '{window}' "
                "(정확한 제목은 물론 부분 일치도 되지만, 게임이 실행 중인지 확인하세요)"
            )
            return None
        print(f"[캡처] 창 '{window}' 클라이언트 영역 {image.width}x{image.height}")
        return image
    return screen.capture()


def _load_digit_templates(args: argparse.Namespace) -> "fingerprint.TemplateSet | None":
    """숫자 0~9 지문 템플릿을 로드한다. 없으면 ``None``(숫자는 '손 입력 필요'로 고지)."""
    path = getattr(args, "digits", None) or scan_module.DEFAULT_DIGITS
    target = Path(path)
    if not target.exists():
        return None
    return fingerprint.TemplateSet.load(target)


def _run_scan(
    args: argparse.Namespace,
    *,
    area: str,
    star_spec: str | None,
    source: str | None,
    window: str | None = None,
    layout_path: str | None = None,
    shop_as_owned: bool = False,
    detect_stars: bool = True,
    digit_templates: "fingerprint.TemplateSet | None" = None,
) -> "scan_module.ScanReport | None":
    """공통 스캔 절차(템플릿/코스트 로드 -> 캡처 -> 인식)."""
    templates_path = getattr(args, "templates", None)
    if not templates_path:
        print(
            "[입력 오류] --templates 가 필요합니다. "
            "python scripts/build_templates.py --from-comps data/comps_set18.json 로 생성하세요."
        )
        return None
    template_set = fingerprint.TemplateSet.load(templates_path)
    try:
        cost_table = scan_module.load_cost_table(getattr(args, "costs", None) or scan_module.DEFAULT_COSTS)
    except FileNotFoundError:
        print("[입력 오류] 유닛 코스트 표를 찾지 못했습니다(data/set18_unit_costs.json).")
        return None
    # 개인 캘리브레이션 좌표(data/layout_1920x1080.json)를 **실사용 경로에서도** 반영한다.
    # Regression(2026-09-23): scan/report 가 이 파일을 읽지 않아, 문서대로 보정해도
    # 인식이 그대로 실패했다(원인을 알 수 없는 '인식 실패'만 보였다).
    layout_path = layout_path or getattr(args, "layout", None)
    try:
        overrides = layout_module.load_overrides(layout_path)
    except (ValueError, FileNotFoundError) as exc:
        print(f"[입력 오류] 좌표 오버라이드 파일을 읽지 못했습니다: {exc}")
        return None
    if overrides:
        resolved = layout_path or layout_module.DEFAULT_LAYOUT_PATH
        print(f"[좌표] 보정 파일 적용: {resolved}")
    image = _load_or_capture(source, window)
    if image is None:
        return None
    return scan_module.scan(
        image,
        template_set,
        cost_table,
        which=tuple(part.strip() for part in area.split(",") if part.strip()),
        star_overrides=_parse_star_spec(star_spec),
        shop_as_owned=shop_as_owned,
        detect_stars=detect_stars,
        digit_templates=digit_templates,
        overrides=overrides,
    )


def cmd_scan(args: argparse.Namespace) -> int:
    """화면을 스캔해 로비 스냅샷 파일을 만든다(CV -> 계산기 연결)."""
    report = _run_scan(
        args,
        area=args.area,
        star_spec=args.star,
        source=args.source,
        window=args.window,
        layout_path=args.layout,
        shop_as_owned=args.shop_as_owned,
        detect_stars=bool(args.star_ocr),
        digit_templates=_load_digit_templates(args),
    )
    if report is None:
        return 2
    print("=== 화면 스캔 결과 ===")
    for line in report.summary_lines():
        print(line)
    snapshot = scan_module.merge_with_opponents(report.snapshot, args.keep_opponents)
    scan_module.write_snapshot(snapshot, args.out)
    print(f"\n저장: {args.out}")
    print(f"  -> 이 파일로 계산: python -m tftcalc.cli report --snapshot {args.out} ...")
    return 0


def _scan_snapshot(args: argparse.Namespace) -> "lobby.LobbySnapshot | None":
    """`report --scan` 용: 화면 스캔 결과(+기존 상대 보존)를 LobbySnapshot 으로."""
    report = _run_scan(
        args,
        area=getattr(args, "scan_area", "bench,shop"),
        star_spec=getattr(args, "star", None),
        source=getattr(args, "scan_in", None),
        window=getattr(args, "scan_window", None),
        layout_path=getattr(args, "scan_layout", None),
        shop_as_owned=getattr(args, "shop_as_owned", False),
        detect_stars=bool(getattr(args, "star_ocr", False)),
        digit_templates=_load_digit_templates(args),
    )
    if report is None:
        return None
    print("\n=== 화면 스캔(내 보드/벤치/상점) ===")
    for line in report.summary_lines():
        print(line)
    merged = scan_module.merge_with_opponents(report.snapshot, args.snapshot)
    out_path = getattr(args, "scan_out", None)
    if out_path:
        scan_module.write_snapshot(merged, out_path)
        print(f"  스냅샷 저장: {out_path}")
    return lobby.LobbySnapshot.from_dict(merged)


def build_parser() -> argparse.ArgumentParser:
    """CLI 파서를 만든다.

    ``main`` 에서 분리한 이유: 테스트가 아규먼트 기본값(예: ``--trials`` 가
    ``trials.py`` 상수를 쓰는지)을 직접 검사할 수 있게 하기 위해서다.
    """
    parser = argparse.ArgumentParser(prog="tftcalc", description="TFT 기회비용 계산기")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--odds-file", default=None, help="data/set18_shop_odds.json 등")
    common.add_argument("--trials", type=int, default=STANDARD, help="몬테카를로 시행 수")

    odds_parser = sub.add_parser("odds", parents=[common], help="아는 상점 확률 셀 출력")
    odds_parser.set_defaults(func=cmd_odds)

    selftest = sub.add_parser("selftest", help="공개 벤치마크 재현")
    selftest.set_defaults(func=cmd_selftest)

    unit = sub.add_parser("unit", parents=[common], help="기물 1종 완성 비용")
    unit.add_argument("--level", type=int, required=True)
    unit.add_argument("--cost", type=int, required=True)
    unit.add_argument("--own", type=int, required=True, help="내 보유 사본(보드+대기석)")
    unit.add_argument("--others", type=int, default=0, help="상대 보유 사본 합")
    unit.add_argument(
        "--tier-in-play",
        type=int,
        default=None,
        help="해당 코스트 등급 전체 소모 사본 수(모르면 내+상대로 가정)",
    )
    unit.add_argument("--target-star", type=int, default=2, choices=[1, 2, 3])
    unit.add_argument("--budget", type=int, default=60)
    unit.set_defaults(func=cmd_unit)

    lby = sub.add_parser("lobby", parents=[common], help="로비 스냅샷 기반 계산")
    lby.add_argument("--snapshot", required=True)
    lby.add_argument("--champion", required=True)
    lby.add_argument("--level", type=int, required=True)
    lby.add_argument("--target-star", type=int, default=2, choices=[1, 2, 3])
    lby.add_argument("--budget", type=int, default=60)
    lby.set_defaults(func=cmd_lobby)

    out = sub.add_parser(
        "outlook", parents=[common], help="기물별 2성/3성 확률 표 (격리 계산)"
    )
    out.add_argument("--snapshot", required=True)
    out.add_argument("--level", type=int, required=True)
    out.add_argument("--budget", type=int, default=60)
    out.add_argument(
        "--units",
        default=None,
        help="쉼표 구분. 예: 'Karma:4,Varus:4:3' (별 생략 시 2성). 생략하면 내 보유 기물 전부",
    )
    out.set_defaults(func=cmd_outlook)

    items_parser = sub.add_parser(
        "items", help="아이템 부품 수급 분석(코어 아이템이 다 맞을 확률)"
    )
    items_parser.add_argument("--comps", required=True, help="data/comps_set18.json 등")
    items_parser.add_argument(
        "--comp-name", default=None, help="컴프 이름(예: '아리 모르가나')"
    )
    items_parser.add_argument(
        "--comp-index", type=int, default=None, help="컴프 번호(1부터). 한글 인자 인용 문제 회피"
    )
    items_parser.add_argument(
        "--components", default=None, help="보유 부품(예: 'rod:2,gloves,tear')"
    )
    items_parser.add_argument("--future-components", type=int, default=0)
    items_parser.add_argument("--choice-components", type=int, default=0)
    items_parser.add_argument(
        "--core-items-limit", type=int, default=6, help="코어 아이템 우선순위 개수(0=전부)"
    )
    items_parser.add_argument("--recipes", default=None)
    items_parser.set_defaults(func=cmd_items)

    plan_parser = sub.add_parser(
        "plan", help="라운드 수입/롤 타이밍 계획 + 그 시점 예산으로 컴프 판정"
    )
    plan_parser.add_argument("--round", required=True, help="현재 라운드(예: 3-5)")
    plan_parser.add_argument("--gold", type=int, required=True, help="현재 보유 골드")
    plan_parser.add_argument("--level", type=int, required=True, help="현재 레벨")
    plan_parser.add_argument("--streak", type=int, default=0, help="연승(+)/연패(-) 스트릭")
    plan_parser.add_argument("--rounds", type=int, default=6, help="몇 라운드 전망할지")
    plan_parser.add_argument(
        "--levelup", default=None, help="레벨업 계획(예: '4-1:7,4-5:8')"
    )
    plan_parser.add_argument("--win-rate", type=float, default=0.5, help="PvP 승률 가정")
    plan_parser.add_argument(
        "--pve-gold", type=int, default=economy.DEFAULT_PVE_GOLD, help="PvE 라운드 골드 가정"
    )
    plan_parser.add_argument(
        "--streak-behavior", default="hold", choices=["hold", "reset"], help="스트릭 유지/초기화"
    )
    plan_parser.add_argument("--target-round", default=None, help="판정할 목표 라운드(예: 4-2)")
    plan_parser.add_argument("--need-gold", type=int, default=None, help="그 라운드에 필요한 골드")
    plan_parser.add_argument("--comps", default=None, help="주면 목표 라운드 예산으로 컴프 판정")
    plan_parser.add_argument("--snapshot", default=None)
    plan_parser.add_argument("--odds-file", default=None)
    plan_parser.add_argument("--recipes", default=None)
    plan_parser.add_argument("--trials", type=int, default=FAST)
    plan_parser.add_argument("--components", default=None, help="보유 부품(예: 'rod:2,gloves')")
    plan_parser.add_argument("--future-components", type=int, default=0)
    plan_parser.add_argument("--choice-components", type=int, default=0)
    plan_parser.add_argument("--core-items-limit", type=int, default=3)
    plan_parser.set_defaults(func=cmd_plan)

    survive_parser = sub.add_parser(
        "survive", help="체력/피해 축: 세이빙 리스크 + 안정화(롤) vs 세이빙 비교"
    )
    survive_parser.add_argument("--round", required=True, dest="round", help="현재 라운드(예: 4-1)")
    survive_parser.add_argument("--hp", type=int, required=True, help="현재 체력")
    survive_parser.add_argument("--gold", type=int, default=0, help="현재 골드(전략 비교에 사용)")
    survive_parser.add_argument("--level", type=int, default=7, help="현재 레벨(전략 비교에 사용)")
    survive_parser.add_argument("--streak", type=int, default=0, help="스트릭(전략 비교에 사용)")
    survive_parser.add_argument("--win-rate", type=float, default=0.35, help="현재 승률 가정")
    survive_parser.add_argument(
        "--enemy-survivors", type=float, default=8.0, help="패배 시 상대 잔존 유닛 수 가정"
    )
    survive_parser.add_argument("--survivors-sd", type=float, default=2.0)
    survive_parser.add_argument("--pve-damage", type=int, default=0)
    survive_parser.add_argument("--rounds", type=int, default=6)
    survive_parser.add_argument("--target-round", default=None, help="판정 기준 라운드(예: 4-5)")
    survive_parser.add_argument(
        "--roll-gold", type=int, default=0, help="지금 롤다운할 골드(주면 비교 실행)"
    )
    survive_parser.add_argument(
        "--win-rate-roll", type=float, default=0.6, help="롤 후 승률 가정(전략 비교)"
    )
    survive_parser.add_argument("--pve-gold", type=int, default=economy.DEFAULT_PVE_GOLD)
    survive_parser.add_argument("--trials", type=int, default=HEAVY)
    survive_parser.set_defaults(func=cmd_survive)

    rep = sub.add_parser(
        "report", help="통합 리포트: 현재 상태 하나로 4축(유닛·아이템·골드·체력) 한 화면"
    )
    rep.add_argument("--round", required=True, dest="round", help="현재 라운드(예: 4-1)")
    rep.add_argument("--gold", type=int, required=True)
    rep.add_argument("--level", type=int, required=True)
    rep.add_argument("--hp", type=int, required=True)
    rep.add_argument("--streak", type=int, default=0)
    rep.add_argument("--rounds", type=int, default=6)
    rep.add_argument("--target-round", default=None, help="판정 기준 라운드(예: 4-5)")
    rep.add_argument("--levelup", default=None, help="레벨업 계획(예: '4-2:8')")
    rep.add_argument("--need-gold", type=int, default=None)
    rep.add_argument("--roll-gold", type=int, default=0, help="지금 롤다운할 골드(비교용)")
    rep.add_argument("--win-rate", type=float, default=0.35)
    rep.add_argument("--win-rate-roll", type=float, default=0.6)
    rep.add_argument("--enemy-survivors", type=float, default=8.0)
    rep.add_argument("--survivors-sd", type=float, default=2.0)
    rep.add_argument("--pve-damage", type=int, default=0)
    rep.add_argument("--pve-gold", type=int, default=economy.DEFAULT_PVE_GOLD)
    rep.add_argument("--snapshot", default=None)
    rep.add_argument(
        "--scan", action="store_true", help="화면을 스캔해 내 보드/벤치를 자동 입력(CV)"
    )
    rep.add_argument("--templates", default=None, help="아이콘 템플릿 JSON(--scan 용)")
    rep.add_argument("--costs", default=None, help="유닛 코스트 JSON(--scan 용)")
    rep.add_argument("--scan-area", default="bench,shop", help="스캔 영역(bench,shop,board)")
    rep.add_argument("--scan-in", default=None, help="BMP 입력으로 스캔(게임 없이 테스트)")
    rep.add_argument(
        "--scan-window",
        default=None,
        help="창 제목(주면 그 창의 클라이언트 영역만 캡처 — 창모드 권장)",
    )
    rep.add_argument(
        "--scan-layout",
        default=None,
        help="좌표 오버라이드 JSON(기본 data/layout_1920x1080.json — 개인 캘리브레이션)",
    )
    rep.add_argument("--scan-out", default=None, help="스캔 결과 스냅샷 저장 경로")
    rep.add_argument("--star", default=None, help="성급 지정 'Ahri=2,Krug=3'")
    rep.add_argument(
        "--shop-as-owned",
        action="store_true",
        help="상점 칸을 '지금 산다'고 가정해 보유로 센다(기본은 세지 않음 — 낙관 편향 방지)",
    )
    rep.add_argument(
        "--star-ocr",
        action="store_true",
        help="별(성급) 자동 인식을 켠다(기본 꺼짐 — 임계값 캘리브레이션 전에는 3배 오차 위험)",
    )
    rep.add_argument(
        "--digits",
        default=None,
        help="숫자 0~9 지문 JSON(기본 data/digits_1920x1080.json, 없으면 숫자는 손 입력)",
    )
    rep.add_argument("--comps", default=None)
    rep.add_argument("--odds-file", default=None)
    rep.add_argument("--recipes", default=None)
    rep.add_argument("--components", default=None)
    rep.add_argument("--future-components", type=int, default=0)
    rep.add_argument("--choice-components", type=int, default=0)
    rep.add_argument("--core-items-limit", type=int, default=3)
    rep.add_argument("--top", type=int, default=3, help="컴프 랭킹에서 상위 몇 개를 보여줄지")
    rep.add_argument("--trials", type=int, default=FAST)
    rep.set_defaults(func=cmd_report)

    scan_parser = sub.add_parser(
        "scan", help="화면을 스캔해 로비 스냅샷 파일 생성(CV -> 계산기 연결)"
    )
    scan_parser.add_argument("--templates", required=True, help="data/templates_set18.json")
    scan_parser.add_argument("--costs", default=None, help="data/set18_unit_costs.json")
    scan_parser.add_argument("--area", default="bench,shop", help="스캔 영역(bench,shop,board)")
    scan_parser.add_argument("--in", dest="source", default=None, help="BMP 입력(없으면 화면 캡처)")
    scan_parser.add_argument(
        "--window",
        default=None,
        help="창 제목(주면 그 창의 클라이언트 영역만 캡처 — 창모드 권장, 예: --window TFT)",
    )
    scan_parser.add_argument(
        "--layout",
        default=None,
        help="좌표 오버라이드 JSON(기본 data/layout_1920x1080.json — 개인 캘리브레이션)",
    )
    scan_parser.add_argument("--out", default="data/my_board.json")
    scan_parser.add_argument(
        "--keep-opponents", default=None, help="기존 스냅샷(상대 항목 보존)"
    )
    scan_parser.add_argument("--star", default=None, help="성급 지정 'Ahri=2,Krug=3'")
    scan_parser.add_argument(
        "--shop-as-owned",
        action="store_true",
        help="상점 칸을 '지금 산다'고 가정해 보유로 센다(기본은 세지 않음 — 낙관 편향 방지)",
    )
    scan_parser.add_argument(
        "--star-ocr",
        action="store_true",
        help="별(성급) 자동 인식을 켠다(기본 꺼짐 — 임계값 캘리브레이션 전에는 3배 오차 위험)",
    )
    scan_parser.add_argument(
        "--digits",
        default=None,
        help="숫자 0~9 지문 JSON(기본 data/digits_1920x1080.json, 없으면 숫자는 손 입력)",
    )
    scan_parser.add_argument("--name", default="나")
    scan_parser.set_defaults(func=cmd_scan)

    cmp_parser = sub.add_parser(
        "comp", parents=[common], help="컴프(덱) 효율 랭킹 - 가장 싸게 완성되는 덱"
    )
    cmp_parser.add_argument("--snapshot", required=True)
    cmp_parser.add_argument("--comps", required=True, help="data/comps_set18.json 등")
    cmp_parser.add_argument(
        "--level",
        type=int,
        default=8,
        help="컴프가 자기 'level' 을 지정하지 않았을 때 쓰는 기본 롤 레벨",
    )
    cmp_parser.add_argument(
        "--gold",
        type=int,
        default=None,
        help="지금 가진 총 골드. 레벨업 비용을 먼저 떼고 남은 골드로 롤/구매(권장 모드)",
    )
    cmp_parser.add_argument(
        "--budget",
        type=int,
        default=None,
        help="롤/구매 전용 예산(레벨업 비용은 총비용에만 가산). --gold 와 함께 쓰지 않는다",
    )
    cmp_parser.add_argument(
        "--levelup-from",
        type=int,
        default=None,
        help="현재 레벨. 주면 컴프별 목표 레벨까지 XP 골드를 계산한다(예: 지금 7레벨)",
    )
    cmp_parser.add_argument(
        "--levelup-rounds",
        type=int,
        default=0,
        help="레벨업에 걸리는 라운드 수(주면 패시브 XP 2/라운드만큼 비용 차감)",
    )
    cmp_parser.add_argument(
        "--components",
        default=None,
        help="보유 부품(예: 'rod:2,gloves,tear'). 아이템 축 계산에 쓰인다",
    )
    cmp_parser.add_argument(
        "--future-components", type=int, default=0, help="앞으로 받을 무작위 부품 수"
    )
    cmp_parser.add_argument(
        "--choice-components",
        type=int,
        default=0,
        help="캐러셀/모루 등 '골라 받는' 부품 수(아무 부족분이나 메움)",
    )
    cmp_parser.add_argument(
        "--core-items-limit",
        type=int,
        default=6,
        help="코어 아이템을 우선순위 순으로 몇 개까지 볼지(0=전부). 기본 6(현실적 완성템 수)",
    )
    cmp_parser.add_argument("--recipes", default=None, help="조합식 JSON 경로")
    cmp_parser.set_defaults(func=cmd_comp)

    sense = sub.add_parser(
        "sensitivity", parents=[common], help="확률표를 모를 때 후보값 민감도 표"
    )
    sense.add_argument("--level", type=int, required=True)
    sense.add_argument("--cost", type=int, required=True)
    sense.add_argument("--own", type=int, required=True)
    sense.add_argument("--others", type=int, default=0)
    sense.add_argument("--tier-in-play", type=int, required=True)
    sense.add_argument("--target-star", type=int, default=2, choices=[1, 2, 3])
    sense.add_argument("--budget", type=int, default=60)
    sense.add_argument(
        "--cost-odds", required=True, help="쉼표로 구분한 후보 확률(예: 0.25,0.30,0.35)"
    )
    sense.add_argument(
        "--cost-odds-are-percent", action="store_true", help="후보를 퍼센트로 해석"
    )
    sense.set_defaults(func=cmd_sensitivity)

    rob = sub.add_parser(
        "robustness", parents=[common], help="입력 오차 ±n장이 결론을 뒤집는지 검사"
    )
    rob.add_argument("--level", type=int, required=True)
    rob.add_argument("--cost", type=int, required=True)
    rob.add_argument("--own", type=int, required=True)
    rob.add_argument("--others", type=int, required=True, help="내가 센 상대 보유 장수")
    rob.add_argument("--tolerance", type=int, default=1, help="오차 가정(±n장)")
    rob.add_argument(
        "--tier-in-play",
        type=int,
        default=None,
        help="해당 코스트 등급 전체 소모 사본 수(모르면 내+상대로 가정하고 [가정] 표시)",
    )
    rob.add_argument("--target-star", type=int, default=2, choices=[1, 2, 3])
    rob.add_argument("--budget", type=int, default=60)
    rob.add_argument(
        "--commit-threshold",
        type=float,
        default=0.5,
        help="이 확률 미만이면 '전환 검토'로 표시(표시 규칙)",
    )
    rob.set_defaults(func=cmd_robustness)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (UnknownOddsError, items.UnknownRecipeError, set_data.UnknownLevelError) as exc:
        # 모르는 값을 추정하지 않고 멈춘다. 사용자에게 무엇을 채워야 하는지 알려준다.
        print(f"[데이터 부족] {exc}")
        return 2
    except (ValueError, KeyError) as exc:
        # 사용자 입력/데이터 파일 오류(라운드 형식·부품 키·없는 챔피언·범위 밖 목표
        # 등)도 스택 트레이스가 아니라 안내로 바꾼다. 같은 카테고리의 오류를
        # UnknownOddsError 만 친절하게 다루던 예전과의 불일치를 없애기 위해서다.
        print(f"[입력 오류] {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
