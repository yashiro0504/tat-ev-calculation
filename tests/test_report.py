"""통합 리포트(CLI `report`) 검증.

리포트는 여러 축을 한 화면에 모으는 것이 목적이므로, '각 섹션이 실제로 나오는가'와
'필수 입력이 없을 때 우아하게 생략하는가'를 본다.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc import cli  # noqa: E402

SNAPSHOT = str(ROOT / "data" / "example_snapshot.json")
COMPS = str(ROOT / "data" / "comps_set18.json")
ODDS = str(ROOT / "data" / "set18_shop_odds_assumed.json")


def run_report(*extra: str) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main(["report", *extra])
    return code, buffer.getvalue()


class TestReportSections(unittest.TestCase):
    def test_full_report_has_all_sections(self):
        code, output = run_report(
            "--round", "4-1", "--gold", "60", "--level", "7", "--hp", "38", "--streak", "-3",
            "--target-round", "4-5", "--levelup", "4-2:8", "--roll-gold", "40",
            "--win-rate", "0.35", "--win-rate-roll", "0.6",
            "--snapshot", SNAPSHOT, "--comps", COMPS, "--odds-file", ODDS,
            "--components", "rod:2,gloves,tear", "--future-components", "6",
            "--trials", "600",
        )
        self.assertEqual(code, 0)
        for section in ("[1] 현재 상태", "[2] 골드 전망", "[3] 생존 전망",
                        "[4] 컴프 판정", "[5] 권장 동선", "[6] 이 결론의 불확실성"):
            self.assertIn(section, output)
        self.assertIn("감당 가능한 패배", output)
        self.assertIn("생존확률", output)
        self.assertIn("교환비율", output)
        # 중복 접두사가 없어야 한다
        self.assertNotIn("교환비율: 교환비율", output)

    def test_report_without_snapshot_skips_comp_section(self):
        code, output = run_report(
            "--round", "4-1", "--gold", "60", "--level", "7", "--hp", "50",
            "--target-round", "4-5", "--trials", "400",
        )
        self.assertEqual(code, 0)
        self.assertIn("[4] 컴프 판정: 스냅샷", output)
        self.assertIn("컴프 판정 생략", output)
        # 스냅샷이 없으면 불확실성 섹션도 그 사실을 알려야 한다
        self.assertIn("스냅샷 없음", output)

    def test_report_without_components_reports_component_count(self):
        code, output = run_report(
            "--round", "4-1", "--gold", "200", "--level", "7", "--hp", "60",
            "--target-round", "4-5", "--snapshot", SNAPSHOT, "--comps", COMPS,
            "--odds-file", ODDS, "--top", "2", "--trials", "600",
        )
        self.assertEqual(code, 0)
        self.assertIn("부품 미입력", output)
        self.assertIn("부품", output)

    def test_report_need_gold_shortfall_message(self):
        code, output = run_report(
            "--round", "4-1", "--gold", "40", "--level", "7", "--hp", "70",
            "--target-round", "4-3", "--need-gold", "150", "--trials", "400",
        )
        self.assertEqual(code, 0)
        self.assertIn("부족", output)
        self.assertIn("세이빙 연장", output)

    def test_report_invalid_round_is_guidance_not_traceback(self):
        """라운드 형식 오류는 스택 트레이스가 아니라 [입력 오류] 로 안내한다.

        Regression: 예전엔 ValueError 가 cli.main 밖으로 터져 트레이스백이 나왔다.
        """
        code, output = run_report(
            "--round", "5", "--gold", "10", "--level", "6", "--hp", "50"
        )
        self.assertEqual(code, 2)
        self.assertIn("[입력 오류]", output)
        self.assertIn("4-2", output)  # 올바른 예시까지 함께 안내

    def test_target_round_beyond_horizon_is_guidance(self):
        """목표가 MAX_HORIZON 밖이면 조용히 fallback 하지 않고 오류로 알린다."""
        code, output = run_report(
            "--round", "4-1", "--gold", "60", "--level", "7", "--hp", "40",
            "--target-round", "11-1",
        )
        self.assertEqual(code, 2)
        self.assertIn("[입력 오류]", output)
        self.assertIn("--rounds", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)