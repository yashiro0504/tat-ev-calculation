"""CLI 명령 커버리지 + 입력 오류 처리 검증.

리뷰에서 미커버로 지목된 명령(odds/lobby/outlook/items/plan/survive/sensitivity)과
"사용자 실수를 스택 트레이스로 터뜨리지 않는가"를 확인한다.

``cli.main`` 이 예외를 밖으로 떠넘기면 이 테스트가 실패하므로, 종료 코드 2 는
곧 "traceback 없이 안내했음"을 뜻한다.
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

from tftcalc import cli, render  # noqa: E402

SNAPSHOT = str(ROOT / "data" / "example_snapshot.json")
COMPS = str(ROOT / "data" / "comps_set18.json")
ODDS = str(ROOT / "data" / "set18_shop_odds_assumed.json")


def run(*argv: str) -> tuple[int, str]:
    """CLI 를 실행해 (종료 코드, 표준 출력) 를 돌려준다."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main(list(argv))
    return code, buffer.getvalue()


class TestCommandSmoke(unittest.TestCase):
    """정상 입력에서 exit 0 과 핵심 출력을 내는지(미커버 명령)."""

    def test_odds(self):
        code, out = run("odds")
        self.assertEqual(code, 0)
        self.assertIn("상점 확률 소스", out)

    def test_selftest(self):
        code, out = run("selftest")
        self.assertEqual(code, 0)
        self.assertIn("공개값", out)

    def test_lobby(self):
        code, out = run(
            "lobby", "--snapshot", SNAPSHOT, "--champion", "Ahri",
            "--level", "8", "--budget", "60", "--trials", "200",
        )
        self.assertEqual(code, 0)
        self.assertIn("Ahri", out)

    def test_outlook_reports_data_gap_or_table(self):
        """확률표가 모자라면 [데이터 부족] 으로 정직하게 멈춘다(추정 금지)."""
        code, out = run(
            "outlook", "--snapshot", SNAPSHOT, "--level", "8", "--trials", "200"
        )
        if code == 0:
            self.assertIn("격리", out)
        else:
            self.assertEqual(code, 2)
            self.assertIn("[데이터 부족]", out)

    def test_items(self):
        code, out = run("items", "--comps", COMPS, "--comp-index", "1")
        self.assertEqual(code, 0)
        self.assertIn("필요 부품", out)

    def test_plan(self):
        code, out = run(
            "plan", "--round", "4-1", "--gold", "60", "--level", "7", "--rounds", "6"
        )
        self.assertEqual(code, 0)
        self.assertIn("라운드 수입", out)

    def test_survive(self):
        code, out = run("survive", "--round", "4-1", "--hp", "40", "--rounds", "6")
        self.assertEqual(code, 0)
        self.assertIn("생존", out)

    def test_sensitivity(self):
        code, out = run(
            "sensitivity", "--level", "8", "--cost", "4",
            "--own", "1", "--tier-in-play", "5",
            "--cost-odds", "0.30,0.35", "--trials", "200",
        )
        self.assertEqual(code, 0)
        self.assertIn("민감도", out)


class TestInputErrorsAreGuidance(unittest.TestCase):
    """미처리 예외 대신 [입력 오류] 로 안내한다(트레이스백 금지).

    Regression: ``UnknownOddsError`` 만 친절하게 처리하던 나머지 4종(라운드 형식·
    부품 키·없는 챔피언·is_me 누락)은 스택 트레이스로 터졌다.
    """

    def test_unknown_champion(self):
        code, out = run(
            "lobby", "--snapshot", SNAPSHOT, "--champion", "Zed", "--level", "8"
        )
        self.assertEqual(code, 2)
        self.assertIn("[입력 오류]", out)

    def test_snapshot_without_me(self):
        code, out = run(
            "outlook", "--snapshot", COMPS, "--level", "8", "--trials", "100"
        )
        self.assertEqual(code, 2)
        self.assertIn("[입력 오류]", out)

    def test_bad_round_format(self):
        code, out = run("plan", "--round", "5", "--gold", "10", "--level", "6")
        self.assertEqual(code, 2)
        self.assertIn("[입력 오류]", out)

    def test_unknown_component_key(self):
        code, out = run(
            "items", "--comps", COMPS, "--comp-index", "1", "--components", "banana"
        )
        self.assertEqual(code, 2)
        self.assertIn("[입력 오류]", out)

    def test_level_11_plan_is_data_gap(self):
        """레벨 11 레벨업 비용을 모른다는 사실을 조용히 0 으로 처리하지 않는다.

        레벨업 계획 라운드가 전망 범위 안에 있어야 경로를 지나므로, 목표를
        반드시 포함하는 ``--rounds`` 를 함께 준다.
        """
        code, out = run(
            "plan", "--round", "9-5", "--gold", "100", "--level", "10",
            "--rounds", "3", "--levelup", "9-6:11",
        )
        self.assertEqual(code, 2)
        self.assertIn("[데이터 부족]", out)
        self.assertIn("레벨 11", out)

    def test_invalid_odds_file_is_rejected(self):
        """300% 확률표를 그대로 받아들이면 틀린 숫자를 정확한 척한다."""
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad_odds.json"
            bad.write_text(json.dumps({"odds": {"8": {"4": 300}}}), encoding="utf-8")
            code, out = run(
                "unit", "--level", "8", "--cost", "4", "--own", "1",
                "--odds-file", str(bad), "--trials", "100",
            )
        self.assertEqual(code, 2)
        self.assertIn("[입력 오류]", out)


class TestItemColumnHonesty(unittest.TestCase):
    """부품 입력이 없으면 0% 로 확률을 위장하지 않는다(M1).

    Regression: ``cmd_comp`` 는 입력이 없어도 ``p_ready=0.0`` 을 "아이템 0%" 로
    찍었고, 결합(유닛 x 아이템)까지 0% 가 되어 유닛 확률을 통째로 덮어썼다.
    ``report`` 만 부품 개수를 보여주는 불일치도 있었다.
    """

    def _comp(self, *extra: str) -> tuple[int, str]:
        return run(
            "comp", "--snapshot", SNAPSHOT, "--comps", COMPS,
            "--odds-file", ODDS, "--level", "8", "--budget", "60",
            "--trials", "300", *extra,
        )

    def test_without_input_shows_component_count(self):
        code, out = self._comp()
        self.assertEqual(code, 0)
        self.assertIn("필요 부품 수", out)
        self.assertIn("--components", out)  # 어떻게 확률을 얻는지 안내

    def test_with_input_shows_probability(self):
        code, out = self._comp("--components", "rod:2,gloves")
        self.assertEqual(code, 0)
        self.assertNotIn("필요 부품 수", out)


class TestRobustnessTierAssumption(unittest.TestCase):
    """등급 소모 가정을 조용히 만들지 않고 노출한다(H4)."""

    def _robust(self, *extra: str) -> tuple[int, str]:
        return run(
            "robustness", "--level", "8", "--cost", "4",
            "--own", "1", "--others", "2", "--tolerance", "1",
            "--trials", "200", *extra,
        )

    def test_assumption_is_reported(self):
        code, out = self._robust()
        self.assertEqual(code, 0)
        self.assertIn("[가정]", out)
        self.assertIn("등급 소모", out)

    def test_explicit_tier_suppresses_assumption(self):
        code, out = self._robust("--tier-in-play", "40")
        self.assertEqual(code, 0)
        self.assertNotIn("[가정]", out)
        self.assertIn("등급 소모 40장", out)


class TestTableAlignment(unittest.TestCase):
    """한글 폭을 2칸으로 세어 헤더·행·구분선이 맞는지(L4).

    Regression: ``{'컴프':<22}`` 나 ``len(header)`` 는 **글자 수** 기준이라
    한글이 섞이면 열이 어긋나고 구분선 길이도 틀렸다.
    """

    def test_comp_table_separator_matches_header_display_width(self):
        code, out = run(
            "comp", "--snapshot", SNAPSHOT, "--comps", COMPS,
            "--odds-file", ODDS, "--level", "8", "--budget", "60", "--trials", "200",
        )
        self.assertEqual(code, 0)
        lines = out.splitlines()
        index = next(
            i for i, line in enumerate(lines) if "동시완성" in line and "비고" in line
        )
        header, separator = lines[index], lines[index + 1]
        self.assertEqual(set(separator), {"-"})
        self.assertEqual(len(separator), render.disp_len(header))

    def test_survive_table_rows_match_header_display_width(self):
        code, out = run(
            "survive", "--round", "4-1", "--hp", "40", "--rounds", "5", "--trials", "300"
        )
        self.assertEqual(code, 0)
        lines = out.splitlines()
        index = next(
            i for i, line in enumerate(lines) if "생존확률" in line and "기대체력" in line
        )
        header = lines[index]
        self.assertEqual(len(lines[index + 1]), render.disp_len(header))
        rows = [line for line in lines[index + 2:] if line.strip()][:5]
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(row=row.strip()[:16]):
                self.assertEqual(render.disp_len(row), render.disp_len(header))


if __name__ == "__main__":
    unittest.main(verbosity=2)