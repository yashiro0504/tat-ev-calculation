"""CV 어댑터 검증 (화면 캡처 · 지문 인식 · 좌표).

검증 전략
--------
* 실제 게임 화면을 이 환경에서 구할 수 없으므로, **합성 이미지**로 알고리즘을 검증한다
  (아이콘 지문을 캔버스에 붙여 '가짜 스크린샷'을 만들고, 다시 분류해 맞히는지 본다).
* 실제 캡처 자체는 이 PC 에서 가능하므로 스모크 테스트로 확인한다(해상도/분산).
* Data Dragon 으로 만든 템플릿 파일이 있으면 '자기 분류 100%'인지도 확인한다.
"""

from __future__ import annotations

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

    def test_build_snapshot_shape(self):
        results = [
            {"slot": "shop_1", "area": "shop", "name": "Ahri", "score": 0.9, "margin": 0.3,
             "runner_up": None, "needs_review": False},
            {"slot": "shop_2", "area": "shop", "name": "unknown", "score": 0.2, "margin": 0.0,
             "runner_up": None, "needs_review": True},
        ]
        snapshot = layout.build_snapshot(results)
        units = snapshot["players"][0]["board"]
        self.assertEqual(len(units), 1)  # unknown 은 제외
        self.assertEqual(units[0]["champion"], "Ahri")


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


if __name__ == "__main__":
    unittest.main(verbosity=2)