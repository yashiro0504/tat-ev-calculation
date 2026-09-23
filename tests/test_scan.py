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
from tftcalc.cv import fingerprint, layout, ocr, scan, screen  # noqa: E402
from tests.fixtures import blank, digit_templates, number, paste, with_separator  # noqa: E402


def make_pattern(pattern_id: int, width: int, height: int) -> screen.Image:
    """결정론적 아이콘 패턴.

    밝기는 ``ocr.STAR_BRIGHTNESS`` **아래**로 묶어 둔다 — 밝은 픽셀이 별 영역에 있으면
    아이콘을 별(성급)로 오인해 테스트가 픽스처 특성에 좌우된다.
    """
    pixels = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            value = ((x * (pattern_id + 1) + y * (pattern_id + 5) + pattern_id * 23) % 50) + 20
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


def _draw_stars(
    canvas: screen.Image,
    x: int,
    y: int,
    width: int,
    height: int,
    count: int,
    *,
    side: int | None = None,
) -> None:
    """칸 하단(별 영역)에 밝은 사각형 ``count`` 개를 그린다.

    ``side`` 를 생략하면 ``ocr`` 의 '별 1개 면적 비율'에 맞춰 크기를 계산한다 —
    별 1개가 차지하는 면적이 기준값과 비슷해야 ``stars_from_ratio`` 가 의도한
    개수를 돌려준다. ``side`` 를 직접 주면 **경계(애매) 상황**을 만들 수 있다.
    """
    bx, by, bw, bh = (int(round(value)) for value in layout.star_band((x, y, width, height)))
    if side is None:
        target = (ocr.STAR_AREA_RATIO * count + ocr.STAR_NOISE_RATIO) * (bw * bh)
        side = max(2, int(round((target / count) ** 0.5)))
    for index in range(count):
        left = bx + 4 + index * (side + 4)
        for row in range(by + 2, min(by + 2 + side, canvas.height)):
            for column in range(left, min(left + side, canvas.width)):
                offset = (row * canvas.width + column) * 4
                canvas.pixels[offset : offset + 4] = bytes((255, 255, 255, 255))


def synthetic_screenshot(
    slot_icons: dict[str, int],
    *,
    which: str | None = None,
    stars: dict[str, int] | None = None,
    star_side: int | None = None,
) -> tuple[screen.Image, fingerprint.TemplateSet]:
    """지정한 칸에 패턴 아이콘을 붙인 가짜 스크린샷 + 그 아이콘들로 만든 템플릿 세트.

    ``which`` 를 생략하면 슬롯 이름 접두사(bench_/shop_)로 영역을 추론한다.
    ``stars`` 로 칸별 별(성급) 개수를 그린다(기본 0개 = 별 미검출).
    ``star_side`` 로 별 크기를 강제해 경계(애매) 상황을 만들 수 있다.
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
        count = (stars or {}).get(slot, 0)
        if count:
            _draw_stars(canvas, x, y, width, height, count, side=star_side)
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
        units = report.snapshot["players"][0]["shop"]
        self.assertEqual([unit["champion"] for unit in units], ["unit1", "unit3"])
        self.assertEqual([unit["cost"] for unit in units], [4, 3])
        self.assertTrue(any(item["name"] == "unknown" for item in report.review))

    def test_star_overrides_applied(self):
        canvas, templates = synthetic_screenshot({"shop_1": 1})
        report = scan.scan(
            canvas, templates, self.COSTS, which=("shop",), star_overrides={"unit1": 2}
        )
        self.assertEqual(report.snapshot["players"][0]["shop"][0]["star"], 2)

    def test_missing_cost_is_reported_not_guessed(self):
        canvas, templates = synthetic_screenshot({"shop_1": 2})
        report = scan.scan(canvas, templates, {"unit1": 4}, which=("shop",))
        self.assertEqual(report.snapshot["players"][0]["shop"], [])
        self.assertIn("unit2", report.missing_cost)

    def test_summary_lines_mention_star_source(self):
        canvas, templates = synthetic_screenshot({"shop_1": 1})
        report = scan.scan(
            canvas, templates, self.COSTS, which=("shop",), detect_stars=True
        )
        text = "\n".join(report.summary_lines())
        self.assertIn("성급은 별 인식 결과", text)
        self.assertIn("[확정]", text)

    def test_summary_lines_mention_caveat_when_star_ocr_off(self):
        """별 인식이 기본(꺼짐)이면 1성 + 켜는 방법을 고지한다."""
        canvas, templates = synthetic_screenshot({"shop_1": 1})
        report = scan.scan(canvas, templates, self.COSTS, which=("shop",))
        text = "\n".join(report.summary_lines())
        self.assertIn("성급은 1로", text)
        self.assertIn("--star-ocr", text)

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
        self.assertEqual(players[0]["shop"][0]["champion"], "unit1")
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


class TestAreaSeparation(unittest.TestCase):
    """상점 칸을 '보유'로 세지 않는지(낙관 편향 회귀 방지).

    Regression: 예전엔 ``board``/``bench`` 구분 없이 상점 칸까지 ``board`` 로 넣었다.
    그래서 **아직 사지 않은 기물이 이미 보유로** 세어져 내 보유 장수가 과대평가되고
    남은 풀 사본이 과소평가됐다 -> "롤다운" 쪽으로 낙관 편향.
    """

    COSTS = {"unit1": 4, "unit2": 4, "unit3": 3, "unit4": 5}

    def test_areas_stay_separate(self):
        # 주의: ``synthetic_screenshot`` 의 패턴은 좌표 기반이라 칸 크기에 따라 달라진다.
        # 같은 id 를 벤치/상점에 재사용하면(크기가 다름) 지문이 달라지므로 id 를 나눠 쓴다.
        canvas, templates = synthetic_screenshot(
            {"bench_1": 1, "bench_2": 2, "shop_1": 3, "shop_2": 4}
        )
        report = scan.scan(canvas, templates, self.COSTS, which=("bench", "shop"))
        mine = report.snapshot["players"][0]
        self.assertEqual([u["champion"] for u in mine["bench"]], ["unit1", "unit2"])
        self.assertEqual([u["champion"] for u in mine["shop"]], ["unit3", "unit4"])
        self.assertEqual(mine["board"], [])
        self.assertEqual(set(report.by_area), {"board", "bench", "shop"})

    def test_shop_units_are_not_counted_as_owned(self):
        """핵심 회귀: 상점에 보였을 뿐인 기물은 내 보유가 아니다."""
        canvas, templates = synthetic_screenshot({"shop_1": 1})
        report = scan.scan(canvas, templates, self.COSTS, which=("shop",))
        snapshot = lobby.LobbySnapshot.from_dict(report.snapshot)
        self.assertEqual(snapshot.my_copies("unit1"), 0)
        self.assertEqual(snapshot.copies_in_play(), {})
        self.assertEqual(snapshot.opponents_copies("unit1"), 0)
        # 그래도 '즉시 살 수 있는 것'으로서 보고에는 남는다
        self.assertEqual(
            [u["champion"] for u in report.by_area["shop"]], ["unit1"]
        )

    def test_bench_units_are_counted_as_owned(self):
        canvas, templates = synthetic_screenshot({"bench_2": 2})
        report = scan.scan(canvas, templates, self.COSTS, which=("bench",))
        snapshot = lobby.LobbySnapshot.from_dict(report.snapshot)
        self.assertEqual(snapshot.my_copies("unit2"), 1)

    def test_shop_as_owned_moves_to_bench_and_notes_the_assumption(self):
        canvas, templates = synthetic_screenshot({"shop_1": 1})
        report = scan.scan(
            canvas, templates, self.COSTS, which=("shop",), shop_as_owned=True
        )
        mine = report.snapshot["players"][0]
        self.assertEqual(mine["shop"], [])
        self.assertEqual([u["champion"] for u in mine["bench"]], ["unit1"])
        self.assertTrue(any("shop-as-owned" in note for note in report.notes))
        self.assertIn("[가정]", "\n".join(report.summary_lines()))

    def test_flag_visibly_changes_pool_math(self):
        """가정이 결과를 바꾼다는 걸 고정한다(기본 0장 vs 가정 1장)."""
        canvas, templates = synthetic_screenshot({"shop_1": 1})
        plain = lobby.LobbySnapshot.from_dict(
            scan.scan(canvas, templates, self.COSTS, which=("shop",)).snapshot
        )
        owned = lobby.LobbySnapshot.from_dict(
            scan.scan(
                canvas, templates, self.COSTS, which=("shop",), shop_as_owned=True
            ).snapshot
        )
        self.assertEqual(plain.my_copies("unit1"), 0)
        self.assertEqual(owned.my_copies("unit1"), 1)

    def test_summary_reports_area_counts_and_shop_caveat(self):
        canvas, templates = synthetic_screenshot({"bench_1": 1, "shop_3": 3})
        report = scan.scan(canvas, templates, self.COSTS, which=("bench", "shop"))
        text = "\n".join(report.summary_lines())
        self.assertIn("[영역]", text)
        self.assertIn("벤치 1칸", text)
        self.assertIn("상점 1칸", text)
        self.assertIn("[상점]", text)
        self.assertIn("'보유'가 아니므로", text)

    def test_no_assumption_notes_without_flags(self):
        """플래그를 안 주면 '가정' note 는 없다(별 미검출 note 는 별개)."""
        canvas, templates = synthetic_screenshot({"shop_1": 1})
        report = scan.scan(canvas, templates, self.COSTS, which=("shop",))
        self.assertFalse(any("shop-as-owned" in note for note in report.notes))


class TestStarOcr(unittest.TestCase):
    """성급(별) 인식 파이프라인: ``--star`` 지정 > 별 인식 > 기본값.

    별 인식은 **기본 꺼짐**이다(임계값 캘리브레이션 전에는 3배 오차 위험이 있어서).
    그래서 여기서는 ``detect_stars=True`` 를 명시해 켠 상태를 검증한다.
    """

    COSTS = {"unit1": 4, "unit2": 4, "unit3": 3}

    def _scan(self, canvas, templates, **kwargs):
        kwargs.setdefault("detect_stars", True)
        return scan.scan(canvas, templates, self.COSTS, which=("shop",), **kwargs)

    def test_detected_star_lands_in_snapshot(self):
        canvas, templates = synthetic_screenshot({"shop_1": 1}, stars={"shop_1": 2})
        report = self._scan(canvas, templates)
        self.assertEqual(report.recognized[0]["star"], 2)
        self.assertEqual(report.snapshot["players"][0]["shop"][0]["star"], 2)
        self.assertIn("2성", "\n".join(report.summary_lines()))

    def test_three_stars_detected(self):
        canvas, templates = synthetic_screenshot({"shop_1": 1}, stars={"shop_1": 3})
        report = self._scan(canvas, templates)
        self.assertEqual(report.recognized[0]["star"], 3)
        snapshot = lobby.LobbySnapshot.from_dict(report.snapshot)
        self.assertEqual(snapshot.my_copies("unit1"), 0)  # 상점이라 보유 아님

    def test_unseen_star_falls_back_to_default_with_note(self):
        """별이 안 보이면 1성으로 두되 '몇 칸인지' 고지한다(0성은 없으므로)."""
        canvas, templates = synthetic_screenshot({"shop_1": 1})
        report = self._scan(canvas, templates)
        self.assertEqual(report.recognized[0]["star"], 1)
        self.assertTrue(any("별을 못 본" in note for note in report.notes))

    def test_ambiguous_star_is_excluded_not_guessed(self):
        """별 비율이 정수 경계에 가까우면 개수를 확정하지 않고 칸을 뺀다.

        ``star_side=13`` 은 이 칸(상점 253x95, 별 띠 높이 15px)에서 비율이 2성과 3성의
        **중간**(scaled 2.47)이 되도록 고른 값이다. 별 띠 기하(``layout.STAR_BAND``)나
        ``ocr.STAR_AREA_RATIO`` 가 바뀌면 이 값도 다시 골라야 한다(실측 스윕: 12->2.26
        확정, 13->2.47 애매, 14->2.68 애매, 15->2.90 확정).
        """
        canvas, templates = synthetic_screenshot(
            {"shop_1": 1}, stars={"shop_1": 2}, star_side=13
        )
        report = self._scan(canvas, templates)
        self.assertEqual(report.recognized, [])
        self.assertEqual(report.snapshot["players"][0]["shop"], [])
        reasons = "\n".join(str(item.get("reason", "")) for item in report.review)
        self.assertIn("성급 확인 필요", reasons)

    def test_icon_bleeding_into_star_band_is_not_read_as_three_stars(self):
        """아이콘이 별 영역을 덮으면 3성으로 clamp 하지 않고 '확인 필요'로 뺀다.

        Regression: 실제 Data Dragon 아이콘을 칸에 채운 화면에서 별 영역 비율이
        별 1개 면적의 약 12배였는데, 그 값을 3성으로 clamp 하면 조용한 3배 오차가 된다.
        """
        canvas, templates = synthetic_screenshot({"shop_1": 1})
        box = dict(layout.resolve("shop")).get("shop_1")
        x, y, width, height = layout.to_pixels(box, canvas.width, canvas.height)
        # 별 영역만 밝게 칠해 '아이콘 오염' 상황을 만든다(분류가 흔들리지 않게
        # 템플릿도 같은 크롭으로 다시 만든다).
        bx, by, bw, bh = (
            int(round(value)) for value in layout.star_band((x, y, width, height))
        )
        for row in range(by, min(by + bh, canvas.height)):
            for column in range(bx, min(bx + bw, canvas.width)):
                offset = (row * canvas.width + column) * 4
                canvas.pixels[offset : offset + 4] = bytes((255, 255, 255, 255))
        crop = canvas.crop(x, y, width, height)
        templates = fingerprint.TemplateSet(
            grid=8,
            source="합성",
            templates=[
                fingerprint.Template(name="unit1", values=fingerprint.fingerprint(crop))
            ],
        )
        report = self._scan(canvas, templates)
        self.assertEqual(report.recognized, [])
        reasons = "\n".join(str(item.get("reason", "")) for item in report.review)
        self.assertIn("성급 확인 필요", reasons)

    def test_user_override_beats_ocr(self):
        canvas, templates = synthetic_screenshot({"shop_1": 1}, stars={"shop_1": 2})
        report = self._scan(canvas, templates, star_overrides={"unit1": 3})
        self.assertEqual(report.recognized[0]["star"], 3)

    def test_default_is_off_and_uses_one_star(self):
        """별 인식은 기본 꺼짐 — 켜기 전에는 1성 + 켜는 방법 고지."""
        canvas, templates = synthetic_screenshot({"shop_1": 1}, stars={"shop_1": 2})
        report = scan.scan(canvas, templates, self.COSTS, which=("shop",))
        self.assertEqual(report.recognized[0]["star"], 1)
        self.assertFalse(report.star_ocr)
        self.assertIn("--star-ocr", "\n".join(report.summary_lines()))


class TestInfoOcrIntegration(unittest.TestCase):
    """``scan`` 이 ``layout.INFO_REGIONS`` 의 **올바른 영역**에서 숫자/라운드를 읽는지.

    좌표 배선이 틀리면 "읽히긴 하는데 엉뚱한 값" 이라는 조용한 오류가 나므로,
    각 영역에 실제로 숫자를 그려 넣고 결과가 그 값과 일치하는지 확인한다.
    """

    EMPTY_TEMPLATES = fingerprint.TemplateSet(grid=8, templates=[], source="빈")

    def _canvas_with_info(self) -> screen.Image:
        canvas = blank(layout.BASE_WIDTH, layout.BASE_HEIGHT)
        for key, text in (("gold", "62"), ("level", "8"), ("my_hp", "41")):
            x, y, _w, _h = layout.to_pixels(
                layout.INFO_REGIONS[key], canvas.width, canvas.height
            )
            paste(canvas, number(text), x, y)
        x, y, _w, _h = layout.to_pixels(
            layout.INFO_REGIONS["stage_round"], canvas.width, canvas.height
        )
        paste(canvas, with_separator("4", "2"), x, y)
        return canvas

    def test_reads_gold_level_hp_and_round(self):
        report = scan.scan(
            self._canvas_with_info(),
            self.EMPTY_TEMPLATES,
            {},
            which=(),
            digit_templates=digit_templates(),
        )
        self.assertEqual(report.info["gold"], 62)
        self.assertEqual(report.info["level"], 8)
        self.assertEqual(report.info["my_hp"], 41)
        self.assertEqual(report.stage_round, (4, 2))
        summary = "\n".join(report.summary_lines())
        self.assertIn("골드 62", summary)
        self.assertIn("라운드 4-2", summary)
        self.assertFalse(any("손 입력" in note for note in report.notes))

    def test_without_digits_everything_is_none_and_flagged(self):
        report = scan.scan(
            self._canvas_with_info(), self.EMPTY_TEMPLATES, {}, which=()
        )
        self.assertEqual(sorted(report.info), ["gold", "level", "my_hp"])
        self.assertTrue(all(value is None for value in report.info.values()))
        self.assertIsNone(report.stage_round)
        notes = "\n".join(report.notes)
        self.assertIn("손 입력 필요", notes)
        self.assertIn("--digits", notes)
        self.assertIn("라운드 ?", "\n".join(report.summary_lines()))


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
            self.assertEqual(data["players"][0]["shop"][0]["champion"], "unit1")
            self.assertEqual(data["players"][0]["shop"][0]["cost"], 4)
            # 상점은 '보유'가 아니므로 board/bench 에는 안 들어간다
            self.assertEqual(data["players"][0]["board"], [])
            self.assertEqual(data["players"][0]["bench"], [])

    @unittest.skipUnless(screen.is_supported(), "Windows(GDI) 아님")
    def test_cli_scan_with_missing_window_fails_cleanly(self):
        """창모드 캡처: 없는 창 제목이면 **조용히 전체 화면으로 대체하지 않고** 실패한다.

        (전체 화면으로 대체하면 창모드에서 좌표가 어긋난 채 '스캔 성공'으로 보여
        잘못된 스냅샷을 만든다 -> 그게 더 위험하다.)
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _, templates_path, costs_path = self._write_fixture(tmp_path, {"shop_1": 1})
            out = tmp_path / "my_board.json"
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = cli.main(
                    [
                        "scan",
                        "--templates", str(templates_path),
                        "--costs", str(costs_path),
                        "--window", "이런 창은 없습니다 (테스트용 제목)",
                        "--area", "shop",
                        "--out", str(out),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("창을 찾지 못했습니다", buffer.getvalue())
            self.assertFalse(out.exists())

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
            self.assertIn("화면 스캔(내 보드/벤치/상점)", output)
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