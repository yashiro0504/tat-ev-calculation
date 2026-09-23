"""크롭 -> 템플릿 빌드의 가드 검증 (``scripts/build_templates.py``).

Regression(2026-09-23): 빈 칸 크롭이 ``shop_4`` 라는 파일명 그대로 템플릿이 되어,
**다른 빈 칸을 'shop_4' 로 오인**했다(빈 칸끼리는 지문이 거의 같다). 실게임 스캔에서
`[확인 필요] 코스트 표에 없음(shop_4)` 라는 이상한 출력으로 드러났다.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_templates  # noqa: E402
from tftcalc.cv import screen  # noqa: E402


def pattern(width: int = 60, height: int = 50, seed: int = 1) -> screen.Image:
    """결정론적 패턴 이미지(테스트용 아이콘)."""
    pixels = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            value = ((x * (seed + 1) + y * (seed + 3) + seed * 11) % 200) + 30
            offset = (y * width + x) * 4
            pixels[offset] = value
            pixels[offset + 1] = (value * 2) % 256
            pixels[offset + 2] = (value * 3) % 256
            pixels[offset + 3] = 255
    return screen.Image(width=width, height=height, pixels=pixels)


class TestBuildFromCropsGuards(unittest.TestCase):
    def build(self, folder: Path):
        with redirect_stdout(io.StringIO()):
            return build_templates.build_from_crops(folder, 8)

    def test_unlabeled_crop_is_skipped(self):
        """``shop_3.bmp`` 처럼 이름표 그대로인 크롭은 템플릿이 되면 안 된다."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            screen.save_bmp(pattern(seed=1), str(folder / "Ahri.bmp"))
            screen.save_bmp(pattern(seed=2), str(folder / "shop_3.bmp"))
            templates, failures = self.build(folder)
        self.assertEqual([t.name for t in templates], ["Ahri"])
        self.assertEqual(len(failures), 1)
        self.assertIn("shop_3.bmp", failures[0])
        self.assertIn("라벨링", failures[0])

    def test_blank_crop_is_skipped(self):
        """단색(빈 칸) 크롭은 지문이 0 벡터라 걸러야 한다(다른 빈 칸과 매칭 방지)."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            flat = screen.Image(width=60, height=50, pixels=bytearray(60 * 50 * 4))
            screen.save_bmp(flat, str(folder / "Ghost.bmp"))
            screen.save_bmp(pattern(seed=3), str(folder / "Yorick.bmp"))
            templates, failures = self.build(folder)
        self.assertEqual([t.name for t in templates], ["Yorick"])
        self.assertEqual(len(failures), 1)
        self.assertIn("Ghost.bmp", failures[0])

    def test_at_suffix_is_a_sample_name(self):
        """``Camille@bench.bmp`` 는 라벨이 ``Camille`` — 같은 챔피언의 여러 샘플을 함께 넣는다.

        벤치 유닛은 상점 카드와 지문이 크게 달라(실측 0.39~0.64) 샘플을 따로 모아야 한다.
        """
        self.assertEqual(build_templates.crop_label("Camille"), "Camille")
        self.assertEqual(build_templates.crop_label("Camille@bench"), "Camille")
        self.assertEqual(build_templates.crop_label("Camille@2"), "Camille")
        self.assertEqual(build_templates.crop_label("Kog'Maw@bench2"), "Kog'Maw")

    def test_two_samples_of_one_champion_share_the_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            screen.save_bmp(pattern(seed=1), str(folder / "Camille.bmp"))
            screen.save_bmp(pattern(seed=2), str(folder / "Camille@bench.bmp"))
            templates, failures = self.build(folder)
        self.assertEqual([t.name for t in templates], ["Camille", "Camille"])
        self.assertEqual(failures, [])

    def test_labeled_crops_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name, seed in (("Ahri", 1), ("Yorick", 2), ("Kog'Maw", 3)):
                screen.save_bmp(pattern(seed=seed), str(folder / f"{name}.bmp"))
            templates, failures = self.build(folder)
        self.assertEqual(sorted(t.name for t in templates), ["Ahri", "Kog'Maw", "Yorick"])
        self.assertEqual(failures, [])
        # 파일명이 곧 라벨이다(코스트 표 이름과 같아야 코스트가 붙는다)
        self.assertEqual(len({t.name for t in templates}), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
