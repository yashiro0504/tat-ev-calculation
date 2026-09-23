"""화면에서 UI 칸(벤치/상점/보드)을 잘라 BMP 로 저장한다.

용도
----
TFT 전용 유닛(Sentinel, Krug, Pebbles, Kobuko, Cinderling, Brambleback, Mama Beak …)은
Riot Data Dragon 에 아이콘이 없다. 게임 화면에서 그 칸을 잘라 **파일명을 유닛 이름으로 바꾸면**
곧바로 템플릿이 된다.

    py -3 scripts/crop_slots.py                      # 전체화면 캡처 -> data/crops/*.bmp
    py -3 scripts/crop_slots.py --in shot.bmp --area shop,bench
    (그다음 data/crops/shop_3.bmp -> data/crops/Krug.bmp 로 이름 변경)
    py -3 scripts/build_templates.py --from-crops data/crops

주의: 좌표(layout.py)가 실제 화면과 어긋나면 잘린 그림이 엉뚱하게 나온다.
      그럴 때는 `scripts/check_capture.py --out shot.bmp` 로 화면을 먼저 확인한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc.cv import layout, screen  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UI 칸 크롭 도구")
    parser.add_argument("--in", dest="source", default=None, help="BMP 입력(생략 시 화면 캡처)")
    parser.add_argument("--area", default="shop,bench", help="잘라낼 영역(shop,bench,board)")
    parser.add_argument("--out", default=str(ROOT / "data" / "crops"), help="출력 폴더")
    parser.add_argument("--layout", default=None, help="좌표 오버라이드 JSON")
    args = parser.parse_args(argv)

    if args.source:
        image = screen.load_bmp(args.source)
        print(f"[입력] {args.source}: {image.width}x{image.height}")
    else:
        if not screen.is_supported():
            print("[오류] 자동 캡처는 Windows 에서만 됩니다. --in 으로 BMP 를 주세요.")
            return 2
        image = screen.capture()
        print(f"[캡처] 화면: {image.width}x{image.height}")

    areas = tuple(part.strip() for part in args.area.split(",") if part.strip())
    overrides = layout.load_overrides(args.layout)
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)

    count = 0
    for area in areas:
        for slot_name, box in layout.resolve(area, overrides):
            x, y, width, height = layout.to_pixels(box, image.width, image.height)
            region = image.crop(x, y, width, height)
            path = output / f"{slot_name}.bmp"
            screen.save_bmp(region, str(path))
            count += 1
    print(f"\n저장: {output} 에 {count}개 BMP")
    print("  -> 필요한 칸을 유닛 이름으로 바꾸세요 (예: shop_3.bmp -> Krug.bmp)")
    print("  -> 그다음: py -3 scripts/build_templates.py --from-crops data/crops")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
