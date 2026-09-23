"""TFT 기회비용/밸류 계산기 프로토타입 (검증된 수학 코어).

설계 원칙
---------
1. 검증 가능한 것(풀 확률, 기대 골드)과 검증 불가능한 것(보드 파워, 증강 상성)을
   코드 레벨에서 분리한다. 후자는 이 패키지에 없다.
2. 모르는 게임 데이터는 절대 추정하지 않는다. 해당 셀이 없으면 예외를 던진다.
3. 게임 입력(라이엇 API/화면인식/GEP/수동)은 '어댑터'로만 취급한다. 수학 코어는
   입력 출처를 모른다.
"""

from . import comp, decision, economy, items, lobby, odds, pool_math, set_data, survival

__all__ = [
    "comp",
    "decision",
    "economy",
    "items",
    "lobby",
    "odds",
    "pool_math",
    "set_data",
    "survival",
]
__version__ = "0.1.0"
