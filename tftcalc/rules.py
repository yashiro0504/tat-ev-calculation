"""규칙 기반 판정(통합 리포트의 [5] 권장 동선과 그 근거).

왜 cli.py 에서 분리했나(L6): ``_report_action`` 이 시뮬레이션 호출·형식 출력·판정
로직을 한 데 섞고 있었다. 판정은 "사실들 -> 문자열" 인 순수 함수라 여기에 두면 단독
테스트가 된다. 시뮬레이션은 여전히 cli 쪽에서 돌리고, 여기에는 결과만 넘긴다.

원칙(README 3.4 와 동일)
-----------------------
* 한쪽이 **지배 관계**이거나 생존 확률이 크게 벌어질 때만 결론을 말한다.
* 아니면 사실과 누락 정보를 나열한다. 지어내지 않는다.
* 임계값(0.1 / 0.5 / 0.4)은 **표시 규칙**이지 과학적 상수가 아니다.
"""

from __future__ import annotations

from . import survival


def build_basis(
    *,
    target_label: str,
    roll_budget: int,
    target_level: int,
    p_survive_target: float,
    best: dict[str, object] | None,
    need_gold: int | None,
    comparison: "survival.StrategyComparison | None",
) -> list[str]:
    """[5] 아래에 ``근거:`` 로 붙일 사실 목록."""
    basis = [
        f"{target_label} 리롤 예산 {roll_budget}골드 / Lv{target_level}",
        f"{target_label} 생존확률 {p_survive_target * 100:.1f}%",
    ]
    if best is not None:
        basis.append(
            f"1순위 컴프 {best['comp']}: 유닛 완성 {float(best['p_complete']) * 100:.1f}%"
        )
    if need_gold:
        basis.append(f"필요 골드 {need_gold} vs 예산 {roll_budget}")
    if comparison is not None:
        basis.append(
            f"세이빙 생존 {comparison.outcomes[0].p_survive * 100:.1f}% vs "
            f"롤 생존 {comparison.outcomes[1].p_survive * 100:.1f}%"
        )
    return basis


def recommend_action(
    *,
    target_label: str,
    roll_gold: int,
    need_gold: int | None,
    roll_budget: int,
    p_survive_target: float,
    best: dict[str, object] | None,
    comparison: "survival.StrategyComparison | None",
) -> str:
    """규칙 기반 권장 동선 한 줄.

    우선순위
    --------
    1. 지금 롤하면 생존이 크게 오르고 세이빙이 위험 구간 -> 안정화
    2. 필요한 골드가 부족 -> 세이빙 연장 / 목표 하향
    3. 1순위 컴프 완성 확률이 충분 -> 계획대로 리롤
    4. 생존 확률이 위험 구간 -> 안정화 우선
    5. 그 외 -> 관망
    """
    if (
        comparison is not None
        and comparison.outcomes[1].p_survive - comparison.outcomes[0].p_survive > 0.1
        and comparison.outcomes[0].p_survive < 0.5
    ):
        return (
            f"지금 안정화(롤 {roll_gold}골드) 우선 — 생존확률이 "
            f"{comparison.outcomes[0].p_survive * 100:.0f}% -> "
            f"{comparison.outcomes[1].p_survive * 100:.0f}% 로 오른다"
        )
    if need_gold and roll_budget < need_gold:
        return f"세이빙 연장 또는 목표 하향 — {need_gold - roll_budget}골드 부족"
    if best is not None and float(best["p_complete"]) >= 0.5:
        return f"{target_label}에 계획대로 리롤 (1순위: {best['comp']})"
    if p_survive_target < 0.4:
        return "체력 리스크 큼 — 안정화 우선 또는 목표 라운드 앞당김"
    return "관망 — 세이빙 유지하고 다음 라운드에 재평가"
