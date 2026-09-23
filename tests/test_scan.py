"""CV -> 스냅샷 -> 리포트 연결 검증.

게임 화면 없이도 전체 경로를 검증하기 위해, **합성 스크린샷**(아이콘 지문을 상점/벤치
좌표에 붙인 캔버스)을 만들어 실제 파이프라인(scan -> snapshot -> LobbySnapshot)에 통과시킨다.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc import cli, lobby  # noqa: E402
from tftcalc.cv import fingerprint, layout, scan, screen  # noqa: E402


def make_pattern(pattern_id: int, width: int, height: int) -> screen.Image:
    pixels = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            value = ((x * (pattern_id + 1) + y * (pattern_id + 5) + pattern_id * 23) % 180) + 40
            offset = (y * width + x) * 4
            pixels[offset] = value
            pixels[offset + 1] = (value * 3) % 256
            pixels[offset + 2] = (value * 5) % 256
            pixels[offset + 3] = 255
    return screen.Image(width=width, height=height, pixels=pixels)


def paste(canvas: screen.Image, patch: screen.Image, x: int, y: int) -> None:
    for row in range(patch.height):
        for column in range(patch.width):
            source = (row * patch.width + column) * 4
            target = ((y + row) * canvas.width + (x + column)) * 4
            canvas.pixels[target : target + 4] = patch.pixels[source : source + 4]


def synthetic_screenshot(
    slot_icons: dict[str, int], *, which: str | None = None
) -> tuple[screen.Image, fingerprint.TemplateSet]:
    """지정한 칸에 패턴 아이콘을 붙인 가짜 스크린샷 + 그 아이콘들로 만든 템플릿 세트.

    ``which`` 를 생략하면 슬롯 이름 접두사(bench_/shop_)로 영역을 추론한다.
    """
    canvas = screen.Image(
        width=layout.BASE_WIDTH,
        height=layout.BASE_HEIGHT,
        pixels=bytearray(layout.BASE_WIDTH * layout.BASE_HEIGHT * 4),
    )
    template_set = fingerprint.TemplateSet(grid=8, templates=[], source="합성")
    for slot, pattern_id in slot_icons.items():
        area = which or slot.split("_")[0]
        box = dict(layout.resolve(area)).get(slot)
        assert box is not None, f"{slot} (영역 {area})"
        x, y, width, height = layout.to_pixels(box, canvas.width, canvas.height)
        icon = make_pattern(pattern_id, width, height)
        paste(canvas, icon, x, y)
        name = f"unit{pattern_id}"
        if not any(template.name == name for template in template_set.templates):
            template_set.templates.append(
                fingerprint.Template(name=name, values=fingerprint.fingerprint(icon))
            )
    return canvas, template_set


class TestScan(unittest.TestCase):
    COSTS = {"unit1": 4, "unit2": 4, "unit3": 3}

    def test_scan_builds_snapshot_with_costs(self):
        canvas, templates = synthetic_screenshot({"shop_1": 1, "shop_3": 3})
        report = scan.scan(canvas, templates, self.COSTS, which=("shop",))
        units = report.snapshot["players"][0]["board"]
        self.assertEqual([unit["champion"] for unit in units], ["unit1", "unit3"])
        self.assertEqual([unit["cost"] for unit in units], [4, 3])
        self.assertTrue(any(item["name"] == "unknown" for item in report.review))

    def test_star_overrides_applied(self):
        canvas, templates = synthetic_screenshot({"shop_1": 1})
        report = scan.scan(
            canvas, templates, self.COSTS, which=("shop",), star_overrides={"unit1": 2}
        )
        self.assertEqual(report.snapshot["players"][0]["board"][0]["star"], 2)

    def test_missing_cost_is_reported_not_guessed(self):
        canvas, templates = synthetic_screenshot({"shop_1": 2})
        report = scan.scan(canvas, templates, {"unit1": 4}, which=("shop",))
        self.assertEqual(report.snapshot["players"][0]["board"], [])
        self.assertIn("unit2", report.missing_cost)

    def test_summary_lines_mention_star_caveat(self):
        canvas, templates = synthetic_screenshot({"shop_1": 1})
        report = scan.scan(canvas, templates, self.COSTS, which=("shop",))
        text = "\n".join(report.summary_lines())
        self.assertIn("성급은 1로", text)
        self.assertIn("[확정]", text)

    def test_merge_keeps_opponents_and_replaces_me(self):
        canvas, templates = synthetic_screenshot({"shop_1": 1})
        report = scan.scan(canvas, templates, self.COSTS, which=("shop",))
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "existing.json"
            existing.write_text(
                json.dumps(
                    {
                        "players": [
                            {"name": "나(옛날)", "is_me": True,
                             "board": [{"champion": "Ahri", "cost": 4, "star": 2}]},
                            {"name": "상대A", "board": [{"champion": "Sett", "cost": 4, "star": 1}]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            merged = scan.merge_with_opponents(report.snapshot, existing)
        players = merged["players"]
        self.assertEqual(len(players), 2)
        self.assertTrue(players[0]["is_me"])
        self.assertEqual(players[0]["board"][0]["champion"], "unit1")
        self.assertEqual(players[1]["name"], "상대A")

    def test_snapshot_feeds_lobby_and_cost_lookup(self):
        canvas, templates = synthetic_screenshot({"bench_2": 2})
        report = scan.scan(canvas, templates, {"unit2": 4}, which=("bench",))
        snapshot = lobby.LobbySnapshot.from_dict(report.snapshot)
        self.assertEqual(snapshot.my_copies("unit2"), 1)
        self.assertEqual(snapshot.cost_of("unit2"), 4)

    def test_cost_table_loader_reads_project_file(self):
        table = scan.load_cost_table()
        self.assertGreater(len(table), 10)
        self.assertEqual(table.get("Ahri"), 4)


class TestCliScanAndReport(unittest.TestCase):
    def _write_fixture(self, tmp: Path, icons: dict[str, int]) -> tuple[Path, Path, Path]:
        """합성 스크린샷(BMP) + 템플릿 + 코스트 표를 임시 폴더에 만든다."""
        canvas, templates = synthetic_screenshot(icons)
        bmp = tmp / "shot.bmp"
        screen.save_bmp(canvas, str(bmp))
        templates_path = tmp / "templates.json"
        templates.save(templates_path)
        costs_path = tmp / "costs.json"
        costs_path.write_text(
            json.dumps(
                {
                    "units": {
                        "unit1": {"name": "unit1", "cost": 4},
                        "unit3": {"name": "unit3", "cost": 3},
                    }
                }
            ),
            encoding="utf-8",
        )
        return bmp, templates_path, costs_path

    def test_cli_scan_writes_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bmp, templates_path, costs_path = self._write_fixture(tmp_path, {"shop_1": 1})
            out = tmp_path / "my_board.json"
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = cli.main(
                    [
                        "scan",
                        "--templates", str(templates_path),
                        "--costs", str(costs_path),
                        "--in", str(bmp),
                        "--area", "shop",
                        "--out", str(out),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("화면 스캔 결과", buffer.getvalue())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["players"][0]["board"][0]["champion"], "unit1")
            self.assertEqual(data["players"][0]["board"][0]["cost"], 4)

    def test_cli_scan_keeps_opponents_from_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bmp, templates_path, costs_path = self._write_fixture(tmp_path, {"shop_1": 1})
            existing = tmp_path / "existing.json"
            existing.write_text(
                json.dumps(
                    {
                        "players": [
                            {"name": "나(옛날)", "is_me": True, "board": []},
                            {"name": "상대A", "board": [{"champion": "Sett", "cost": 4, "star": 1}]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            out = tmp_path / "merged.json"
            with redirect_stdout(io.StringIO()):
                code = cli.main(
                    [
                        "scan",
                        "--templates", str(templates_path),
                        "--costs", str(costs_path),
                        "--in", str(bmp),
                        "--area", "shop",
                        "--out", str(out),
                        "--keep-opponents", str(existing),
                    ]
                )
            self.assertEqual(code, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            names = [player["name"] for player in data["players"]]
            self.assertIn("상대A", names)

    def test_report_scan_uses_scanned_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bmp, templates_path, costs_path = self._write_fixture(tmp_path, {"shop_1": 1})
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = cli.main(
                    [
                        "report",
                        "--round", "4-1", "--gold", "60", "--level", "7", "--hp", "40",
                        "--target-round", "4-3", "--trials", "300",
                        "--scan",
                        "--templates", str(templates_path),
                        "--costs", str(costs_path),
                        "--scan-in", str(bmp),
                        "--scan-area", "shop",
                    ]
                )
            output = buffer.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("[1] 현재 상태", output)
            self.assertIn("화면 스캔(내 보드/벤치)", output)
            self.assertIn("unit1", output)
            self.assertIn("[5] 권장 동선", output)

    def test_report_scan_without_templates_fails_cleanly(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(
                ["report", "--round", "4-1", "--gold", "60", "--level", "7", "--hp", "40", "--scan"]
            )
        self.assertEqual(code, 2)
        self.assertIn("--templates", buffer.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)