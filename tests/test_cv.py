"""CV 어댑터 검증 (화면 캡처 · 지문 인식 · 좌표).

검증 전략
--------
* 실제 게임 화면을 이 환경에서 구할 수 없으므로, **합성 이미지**로 알고리즘을 검증한다
  (아이콘 지문을 캔버스에 붙여 '가짜 스크린샷'을 만들고, 다시 분류해 맞히는지 본다).
* 실제 캡처 자체는 이 PC 에서 가능하므로 스모크 테스트로 확인한다(해상도/분산).
* Data Dragon 으로 만든 템플릿 파일이 있으면 '자기 분류 100%'인지도 확인한다.
"""

from __future__ import annotations

import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc.cv import fingerprint, layout, screen  # noqa: E402


def make_pattern(pattern_id: int, width: int = 40, height: int = 40) -> screen.Image:
    """결정론적 패턴 이미지(테스트용 아이콘 대체)."""
    pixels = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            value = ((x * (pattern_id + 1) + y * (pattern_id + 3) + pattern_id * 17) % 200) + 30
            offset = (y * width + x) * 4
            pixels[offset] = value
            pixels[offset + 1] = (value * 2) % 256
            pixels[offset + 2] = (value * 3) % 256
            pixels[offset + 3] = 255
    return screen.Image(width=width, height=height, pixels=pixels)


def paste(canvas: screen.Image, patch: screen.Image, x: int, y: int) -> None:
    """캔버스의 (x, y) 위치에 이미지를 붙인다(합성 스크린샷 만들기)."""
    for row in range(patch.height):
        for column in range(patch.width):
            source = (row * patch.width + column) * 4
            target = ((y + row) * canvas.width + (x + column)) * 4
            canvas.pixels[target : target + 4] = patch.pixels[source : source + 4]


class TestScreenImage(unittest.TestCase):
    def test_crop_and_pixel(self):
        image = make_pattern(1, 20, 10)
        cropped = image.crop(5, 2, 6, 4)
        self.assertEqual((cropped.width, cropped.height), (6, 4))
        self.assertEqual(cropped.pixel(0, 0), image.pixel(5, 2))

    def test_crop_outside_bounds_is_zero_filled(self):
        image = make_pattern(2, 10, 10)
        cropped = image.crop(-4, -4, 6, 6)
        self.assertEqual(cropped.pixel(0, 0), (0, 0, 0))  # 화면 밖
        self.assertEqual(cropped.pixel(5, 5), image.pixel(1, 1))

    def test_bmp_roundtrip(self):
        image = make_pattern(3, 16, 12)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.bmp"
            screen.save_bmp(image, str(path))
            loaded = screen.load_bmp(str(path))
        self.assertEqual((loaded.width, loaded.height), (16, 12))
        for point in ((0, 0), (7, 5), (15, 11)):
            self.assertEqual(loaded.pixel(*point), image.pixel(*point))

    def test_variance_detects_flat_image(self):
        flat = screen.Image(width=8, height=8, pixels=bytearray(8 * 8 * 4))
        self.assertEqual(flat.variance(), 0.0)
        self.assertGreater(make_pattern(4).variance(), 0.0)


class TestFingerprint(unittest.TestCase):
    def setUp(self):
        self.templates = fingerprint.TemplateSet(
            grid=8,
            templates=[
                fingerprint.Template(name=f"unit{i}", values=fingerprint.fingerprint(make_pattern(i)))
                for i in range(1, 6)
            ],
            source="테스트",
        )

    def test_identical_image_classifies_exactly(self):
        match = fingerprint.classify(make_pattern(3), self.templates)
        self.assertEqual(match.name, "unit3")
        self.assertFalse(match.needs_review)
        self.assertGreater(match.margin, 0.05)

    def test_duplicate_samples_do_not_break_margin(self):
        """같은 챔피언 샘플이 여러 개여도 2등 마진은 **다른 이름**과 비교해야 한다.

        Regression(2026-09-23): 상점 카드 템플릿 + 벤치 3D 모델 템플릿을 같은 이름
        (``Camille``)으로 넣으면 2등이 같은 이름이 되어 마진이 0 에 가까워지고, 그 챔피언이
        통째로 '확인 필요' 로 떨어진다(자기 자신과 비교하는 셈).
        """
        icon = make_pattern(7)
        template_set = fingerprint.TemplateSet(
            grid=8,
            templates=[
                fingerprint.Template(name="Camille", values=fingerprint.fingerprint(icon)),
                fingerprint.Template(
                    name="Camille", values=fingerprint.fingerprint(make_pattern(8))
                ),
                fingerprint.Template(
                    name="Ahri", values=fingerprint.fingerprint(make_pattern(9))
                ),
            ],
            source="테스트",
        )
        match = fingerprint.classify(icon, template_set)
        self.assertEqual(match.name, "Camille")
        self.assertFalse(match.needs_review)
        self.assertGreater(match.margin, 0.05)
        self.assertNotEqual(match.runner_up, "Camille")

    def test_blank_region_is_unknown(self):
        blank = screen.Image(width=40, height=40, pixels=bytearray(40 * 40 * 4))
        match = fingerprint.classify(blank, self.templates)
        self.assertEqual(match.name, "unknown")
        self.assertTrue(match.needs_review)

    def test_near_duplicates_require_review(self):
        """거의 같은 템플릿 두 개만 있으면 margin 이 작아 '확인 필요'가 되어야 한다."""
        base = make_pattern(7)
        template_set = fingerprint.TemplateSet(
            grid=8,
            templates=[
                fingerprint.Template(name="A", values=fingerprint.fingerprint(base)),
                fingerprint.Template(
                    name="B",
                    values=fingerprint.fingerprint(
                        screen.Image(width=base.width, height=base.height, pixels=bytearray(base.pixels))
                    ),
                ),
            ],
            source="테스트",
        )
        match = fingerprint.classify(base, template_set)
        self.assertTrue(match.needs_review)
        self.assertLess(match.margin, 0.05)

    def test_similarity_and_distance_are_consistent(self):
        values = fingerprint.fingerprint(make_pattern(2))
        self.assertAlmostEqual(fingerprint.distance(values, values), 0.0)
        self.assertAlmostEqual(fingerprint.similarity(values, values), 1.0)

    def test_template_set_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "templates.json"
            self.templates.save(path)
            loaded = fingerprint.TemplateSet.load(path)
        self.assertEqual(loaded.grid, self.templates.grid)
        self.assertEqual(loaded.names(), self.templates.names())


class TestLayout(unittest.TestCase):
    def test_ratio_to_pixels(self):
        box = (0.5, 0.25, 0.1, 0.2)
        self.assertEqual(layout.to_pixels(box, 1000, 1000), (500, 250, 100, 200))

    def test_slots_within_bounds(self):
        for name, box in layout.BENCH_SLOTS + layout.SHOP_SLOTS:
            x, y, width, height = layout.to_pixels(box, layout.BASE_WIDTH, layout.BASE_HEIGHT)
            self.assertGreaterEqual(x, 0, name)
            self.assertGreaterEqual(y, 0, name)
            self.assertLessEqual(x + width, layout.BASE_WIDTH, name)
            self.assertLessEqual(y + height, layout.BASE_HEIGHT, name)

    def test_bench_and_shop_do_not_overlap(self):
        bench_bottom = max(
            layout.to_pixels(box, layout.BASE_WIDTH, layout.BASE_HEIGHT)[1]
            + layout.to_pixels(box, layout.BASE_WIDTH, layout.BASE_HEIGHT)[3]
            for _, box in layout.BENCH_SLOTS
        )
        shop_top = min(
            layout.to_pixels(box, layout.BASE_WIDTH, layout.BASE_HEIGHT)[1]
            for _, box in layout.SHOP_SLOTS
        )
        self.assertLessEqual(bench_bottom, shop_top)

    def test_slot_counts(self):
        self.assertEqual(len(layout.BENCH_SLOTS), 9)
        self.assertEqual(len(layout.SHOP_SLOTS), 5)

    def test_overrides_replace_boxes(self):
        overrides = {"shop": [[0.1, 0.1, 0.05, 0.05]] * 5}
        resolved = layout.resolve("shop", overrides)
        self.assertEqual(resolved[0][1], (0.1, 0.1, 0.05, 0.05))

    def test_read_slots_on_synthetic_canvas(self):
        """합성 캔버스에 박스 크기에 맞춘 아이콘을 붙이고 칸 인식이 되는지 확인."""
        canvas = screen.Image(
            width=layout.BASE_WIDTH,
            height=layout.BASE_HEIGHT,
            pixels=bytearray(layout.BASE_WIDTH * layout.BASE_HEIGHT * 4),
        )
        template_set = fingerprint.TemplateSet(grid=8, templates=[], source="테스트")
        pasted: list[str] = []
        for index, (_, box) in enumerate(layout.SHOP_SLOTS, start=1):
            x, y, width, height = layout.to_pixels(box, canvas.width, canvas.height)
            icon = make_pattern(index, width, height)  # 박스와 같은 크기로 생성
            paste(canvas, icon, x, y)
            name = f"unit{index}"
            pasted.append(name)
            template_set.templates.append(
                fingerprint.Template(name=name, values=fingerprint.fingerprint(icon))
            )

        results = layout.read_slots(canvas, template_set, which=("shop",))
        shop_results = {item["slot"]: item["name"] for item in results}
        for index, name in enumerate(pasted, start=1):
            self.assertEqual(shop_results[f"shop_{index}"], name)

    def test_override_wrong_count_is_rejected(self):
        """칸 수가 안 맞으면 일부 칸이 조용히 빠진다 -> 명시적으로 거부.

        Regression: 예전엔 ``boxes[:len(defaults)]`` 로 조용히 잘라서, 오버라이드를
        한두 칸 빠뜨리면 그 칸이 아예 안 읽혔는데 '인식 실패' 로만 보였다.
        """
        with self.assertRaises(ValueError):
            layout.resolve("shop", {"shop": [[0.1, 0.9, 0.1, 0.09]]})  # 5칸 중 1개
        with self.assertRaises(ValueError):
            layout.resolve("bench", {"bench": [[0, 0, 0.05, 0.05]] * 20})  # 9칸 초과

    def test_override_box_must_have_four_values(self):
        with self.assertRaises(ValueError):
            layout.resolve("shop", {"shop": [[0.1, 0.9, 0.1]] * 5})  # h 누락

    def test_info_regions_can_be_overridden(self):
        """골드/레벨/HP 영역도 파일로 보정할 수 있어야 한다(OCR 작업의 전제)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "layout.json"
            path.write_text(
                json.dumps({"info": {"gold": [0.06, 0.90, 0.08, 0.05]}}),
                encoding="utf-8",
            )
            merged = layout.resolve_info(layout.load_overrides(path))
        self.assertEqual(merged["gold"], (0.06, 0.90, 0.08, 0.05))
        # 미지정 영역은 기본값 유지
        self.assertEqual(merged["level"], layout.INFO_REGIONS["level"])

    def test_info_regions_unknown_name_rejected(self):
        with self.assertRaises(ValueError):
            layout.resolve_info({"info": {"nope": [0.0, 0.0, 1.0, 1.0]}})

    def test_unknown_layout_key_rejected(self):
        """오타 키가 조용히 무시되지 않는다(좌표 전체 누락 방지)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "layout.json"
            path.write_text(json.dumps({"shopp": [[0, 0, 1, 1]]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                layout.load_overrides(path)


class TestWindowTitleMatching(unittest.TestCase):
    """창 제목 매칭은 관대해야 한다 — 실제 TFT 창 제목은 뒤에 공백이 붙어 있다('TFT  ').

    Regression(2026-09-23): ``FindWindowW`` 정확 일치만 써서 ``--window TFT`` 가
    실제 게임 창을 찾지 못했다(제목이 ``'TFT  '`` 였다).
    """

    def test_exact_match_beats_loose_match(self):
        self.assertGreater(
            screen._title_score("TFT", "TFT"), screen._title_score("TFT  ", "TFT")
        )

    def test_trailing_spaces_and_case_are_tolerated(self):
        self.assertEqual(screen._title_score("TFT  ", "TFT"), 2)
        self.assertEqual(screen._title_score("teamfight tactics", "TeamFight Tactics"), 2)

    def test_substring_is_weak_but_accepted(self):
        self.assertEqual(screen._title_score("Teamfight Tactics", "Tactics"), 1)

    def test_unrelated_or_empty_query_scores_zero(self):
        self.assertEqual(screen._title_score("League of Legends", "TFT"), 0)
        self.assertEqual(screen._title_score("TFT", ""), 0)

    def test_candidate_key_prefers_score_then_larger_window(self):
        """부분 일치는 큰 창이 이긴다 — 작은 도우미 창(MetaTFT 등)을 잡지 않게.

        Regression(2026-09-23): ``--window TFT`` 로 게임이 꺼진 상태에서 실행하니
        최소화된 ``MetaTFT Companion App``(160x28)을 캡처해 '스캔 성공'처럼 보였다.
        """
        # 점수가 다르면 점수 우선(작아도 정확 일치가 이긴다)
        self.assertGreater(
            screen._candidate_key(2, 10), screen._candidate_key(1, 1_000_000)
        )
        # 점수가 같으면 큰 창 우선
        self.assertGreater(
            screen._candidate_key(1, 2_000_000), screen._candidate_key(1, 160 * 28)
        )


class TestRealCapture(unittest.TestCase):
    """이 PC 에서 실제 캡처가 되는지(스모크). 미지원 환경이면 건너뛴다."""

    @unittest.skipUnless(screen.is_supported(), "Windows(GDI) 아님")
    def test_capture_screen(self):
        image = screen.capture()
        self.assertGreater(image.width, 100)
        self.assertGreater(image.height, 100)
        self.assertGreater(image.variance(), 1.0)  # 검은 화면이면 0

    def test_find_missing_window_returns_none(self):
        self.assertIsNone(screen.find_window("이런 창은 없습니다 (테스트용 제목)"))

    def test_find_missing_client_returns_none(self):
        """창모드 캡처용 클라이언트 조회도 없는 창이면 None(조용히 아무 창이나 잡지 않는다)."""
        self.assertIsNone(screen.find_client("이런 창은 없습니다 (테스트용 제목)"))
        self.assertIsNone(screen.capture_client("이런 창은 없습니다 (테스트용 제목)"))


class TestBuiltTemplates(unittest.TestCase):
    """Data Dragon 으로 만들어 둔 템플릿 파일이 있으면 품질을 확인한다."""

    PATH = ROOT / "data" / "templates_set18.json"

    def setUp(self):
        if not self.PATH.exists():
            self.skipTest("templates_set18.json 없음(빌드 스크립트로 생성 필요)")

    def test_templates_self_classify_on_vectors(self):
        """템플릿 품질: 각 템플릿이 자기 자신을 1등으로 찾아야 한다(자기 분류 100%)."""
        template_set = fingerprint.TemplateSet.load(self.PATH)
        self.assertGreater(len(template_set.templates), 10)
        ambiguous = []
        for template in template_set.templates:
            scores = sorted(
                (
                    (fingerprint.similarity(template.values, other.values), other.name)
                    for other in template_set.templates
                ),
                reverse=True,
            )
            if scores[0][1] != template.name:
                ambiguous.append(f"{template.name} -> {scores[0][1]}")
        self.assertEqual(ambiguous, [], f"자기 분류 실패: {ambiguous}")
        self.assertIn("Data Dragon", template_set.source)

    def test_classify_rejects_blank_but_accepts_real_image(self):
        """빈 칸은 unknown 으로 남고, 실제 아이콘 이미지는 올바르게 분류된다.

        주의: 지문을 이미지로 되돌려 재분류하는 것은 손실이 있어 실제 파이프라인과 다르다.
        그래서 '실제 이미지 -> 템플릿 -> 같은 이미지 분류' 경로로 검증한다.
        """
        template_set = fingerprint.TemplateSet.load(self.PATH)
        blank = screen.Image(width=60, height=60, pixels=bytearray(60 * 60 * 4))
        self.assertEqual(fingerprint.classify(blank, template_set).name, "unknown")

        icon = make_pattern(11, 64, 64)
        single = fingerprint.TemplateSet(
            grid=template_set.grid,
            templates=[
                fingerprint.Template(name="TestUnit", values=fingerprint.fingerprint(icon))
            ],
            source="테스트",
        )
        self.assertEqual(fingerprint.classify(icon, single).name, "TestUnit")
        # 실제 템플릿 세트에 대고 물으면: 챔피언 중 하나 또는 확인 필요로 나온다
        match = fingerprint.classify(icon, template_set)
        self.assertIn(match.name, set(template_set.names()) | {"unknown"})

    @staticmethod
    def _render(template_set: fingerprint.TemplateSet, template: fingerprint.Template) -> screen.Image:
        """지문을 그대로 이미지로 되돌린다(자기 분류 확인용)."""
        grid = template_set.grid
        size = grid * 6
        pixels = bytearray(size * size * 4)
        for row in range(size):
            for column in range(size):
                value = template.values[(row // 6) * grid + (column // 6)]
                level = int(max(0, min(255, 128 + value * 40)))
                offset = (row * size + column) * 4
                pixels[offset] = level
                pixels[offset + 1] = level
                pixels[offset + 2] = level
                pixels[offset + 3] = 255
        return screen.Image(width=size, height=size, pixels=pixels)


class TestStarBandStaysOutOfFingerprint(unittest.TestCase):
    """별(성급) 띠는 지문 영역 **밖**에 있어야 한다.

    Regression(2026-09-23): ``STAR_BAND`` 가 0.76 부터라 지문이 잘라내는 아래쪽 18%
    (경계 0.82) 와 6%p 겹쳤다. 그래서 별 픽셀이 지문에 섞여 **같은 챔피언인데도**
    1성 1.0000 / 3성 0.6341 로 갈렸고, ``MIN_SCORE`` 를 0.85(비아이콘 차단 바닥선)로
    올린 뒤에는 2·3성 칸이 통째로 'unknown' 이 됐다
    (tests/test_scan.py::TestStarOcr.test_three_stars_detected).
    """

    def test_star_band_starts_below_the_fingerprint_boundary(self):
        """별 띠 시작선은 지문이 잘라내는 경계보다 **아래**(=비율이 큼)여야 한다."""
        self.assertGreater(layout.STAR_BAND[1], 1.0 - fingerprint.DEFAULT_INSET)
        self.assertLess(layout.STAR_BAND[1], 1.0)

    def test_star_pixels_are_outside_the_fingerprinted_area(self):
        """실제 슬롯 픽셀 기준으로도 별 띠가 지문 안쪽으로 들어오지 않아야 한다."""
        for area in ("bench", "shop"):
            for name, box in layout.resolve(area, None):
                x, y, width, height = layout.to_pixels(
                    box, layout.BASE_WIDTH, layout.BASE_HEIGHT
                )
                _, band_top, _, _ = layout.star_band((x, y, width, height))
                fingerprint_bottom = y + height - int(height * fingerprint.DEFAULT_INSET)
                with self.subTest(slot=name):
                    self.assertGreaterEqual(int(round(band_top)), fingerprint_bottom)


class TestThresholdsComeFromConstants(unittest.TestCase):
    """분류 문턱이 모듈 상수에서 오고, 그 근거가 문서화돼 있는지(L10)."""

    def test_classify_defaults_reference_module_constants(self):
        """Regression: 0.5 / 0.05 이 함수 안에 하드코딩돼 근거를 알 수 없었다."""
        signature = inspect.signature(fingerprint.classify)
        self.assertEqual(
            signature.parameters["min_score"].default, fingerprint.MIN_SCORE
        )
        self.assertEqual(
            signature.parameters["review_margin"].default, fingerprint.REVIEW_MARGIN
        )

    def test_constants_are_in_a_sane_range(self):
        self.assertGreater(fingerprint.MIN_SCORE, 0.0)
        self.assertLess(fingerprint.MIN_SCORE, 1.0)
        self.assertGreater(fingerprint.REVIEW_MARGIN, 0.0)
        self.assertLess(fingerprint.REVIEW_MARGIN, 1.0)

    def test_min_score_sits_above_icon_confusion_range(self):
        """``MIN_SCORE`` 는 '서로 다른 아이콘끼리의 최대 유사도'보다 **높아야** 한다.

        실측(2026-09-23):
        * 서로 다른 아이콘 쌍 최대 = 0.7438 (템플릿 28개, 378쌍)
        * 아이콘이 아닌 화면 내용   = 0.6494 (게임 없는 바탕화면의 14칸)
        * 실제 아이콘              = 0.95~0.97

        바닥선이 0.74 와 0.95 사이에 있으면 비(非)아이콘은 걸러지고 아이콘은 통과한다.
        Regression: 기본값이 0.5 였을 때는 이 구간 **안**이라서, 게임을 켜지 않은
        바탕화면에서도 Gnar/Kog'Maw 가 '확정'되어 스냅샷을 오염시켰다.
        """
        path = ROOT / "data" / "templates_set18.json"
        if not path.exists():
            self.skipTest("templates_set18.json 없음")
        template_set = fingerprint.TemplateSet.load(path)
        worst_distinct = 0.0
        for index, first in enumerate(template_set.templates):
            for second in template_set.templates[index + 1:]:
                worst_distinct = max(
                    worst_distinct,
                    fingerprint.similarity(first.values, second.values),
                )
        self.assertLess(
            worst_distinct,
            fingerprint.MIN_SCORE,
            "서로 다른 아이콘이 바닥선을 넘으면 '아이콘이 아님'을 걸러낼 수 없다",
        )

    def test_second_best_is_below_min_score_for_every_icon(self):
        """각 아이콘은 1등이 자기 자신이고 2등은 바닥선 아래여야 한다(오분류 0)."""
        path = ROOT / "data" / "templates_set18.json"
        if not path.exists():
            self.skipTest("templates_set18.json 없음")
        template_set = fingerprint.TemplateSet.load(path)
        for template in template_set.templates:
            scores = sorted(
                (
                    (fingerprint.similarity(template.values, other.values), other.name)
                    for other in template_set.templates
                    if other.name != template.name
                ),
                reverse=True,
            )
            with self.subTest(name=template.name):
                self.assertLess(scores[0][0], fingerprint.MIN_SCORE)


if __name__ == "__main__":
    unittest.main(verbosity=2)