"""실제 아이콘으로 '가짜 스크린샷'을 만들어 스캔 파이프라인을 검증한다.

왜 필요한가
----------
게임 화면 없이도 **실제 챔피언 아이콘 -> 템플릿 -> 인식 -> 스냅샷 -> 리포트** 경로를
끝까지 돌려볼 수 있다. 좌표가 맞는지, 인식이 되는지, 코스트가 채워지는지 확인하는 용도.

사용 예
-------
  py -3 scripts/simulate_scan.py --units ahri,morgana,sett,krug --out sim_shot.bmp
  py -3 -m tftcalc.cli scan --templates data/templates_set18.json --in sim_shot.bmp ^
      --area shop --out data/sim_board.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for path in (ROOT, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import build_templates  # noqa: E402  (scripts/build_templates.py)
from tftcalc.cv import layout, screen  # noqa: E402


def paste(canvas: screen.Image, patch: screen.Image, x: int, y: int) -> None:
    for row in range(min(patch.height, canvas.height - y)):
        for column in range(min(patch.width, canvas.width - x)):
            source = (row * patch.width + column) * 4
            target = ((y + row) * canvas.width + (x + column)) * 4
            canvas.pixels[target : target + 4] = patch.pixels[source : source + 4]


def scaled(image: screen.Image, width: int, height: int) -> screen.Image:
    """최근접 이웃으로 크기 변경(아이콘을 칸 크기에 맞춘다)."""
    pixels = bytearray(width * height * 4)
    for row in range(height):
        source_row = min(image.height - 1, int(row * image.height / height))
        for column in range(width):
            source_column = min(image.width - 1, int(column * image.width / width))
            source = (source_row * image.width + source_column) * 4
            target = (row * width + column) * 4
            pixels[target : target + 4] = image.pixels[source : source + 4]
    return screen.Image(width=width, height=height, pixels=pixels)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="가짜 스크린샷 생성(스캔 검증용)")
    parser.add_argument("--units", required=True, help="쉼표 구분 챔피언 이름(상점 칸에 붙임)")
    parser.add_argument("--area", default="shop", choices=["shop", "bench"])
    parser.add_argument("--out", default="sim_shot.bmp")
    parser.add_argument("--blank", default=None, help="비워둘 칸 이름 'shop_3,shop_5'")
    args = parser.parse_args(argv)

    names = [name.strip() for name in args.units.split(",") if name.strip()]
    blank = {part.strip() for part in (args.blank or "").split(",") if part.strip()}
    slots = [slot for slot, _ in layout.resolve(args.area) if slot not in blank]
    if len(names) > len(slots):
        print(f"[오류] 유닛 {len(names)}개 > 칸 {len(slots)}개")
        return 2

    canvas = screen.Image(
        width=layout.BASE_WIDTH,
        height=layout.BASE_HEIGHT,
        pixels=bytearray(layout.BASE_WIDTH * layout.BASE_HEIGHT * 4),
    )
    failures: list[str] = []
    placed = 0
    for slot, name in zip(slots, names):
        icon_name = None
        image = None
        for candidate in build_templates.icon_candidates(name, {}):
            try:
                image = build_templates.decode_png(
                    build_templates.http_bytes(
                        build_templates.ICON_URL.format(
                            version=build_templates.DDRAGON_VERSION, icon=candidate
                        )
                    )
                )
                icon_name = candidate
                break
            except Exception as exc:  # noqa: BLE001 (아이콘 없음/네트워크 문제 모두 보고)
                last = exc
        if image is None:
            failures.append(f"{name}: {last}")
            continue
        box = dict(layout.resolve(args.area))[slot]
        x, y, width, height = layout.to_pixels(box, canvas.width, canvas.height)
        paste(canvas, scaled(image, width, height), x, y)
        placed += 1
        print(f"[붙임] {slot:<8} {name} ({icon_name}.png)")

    screen.save_bmp(canvas, args.out)
    print(f"\n저장: {args.out} ({placed}칸 배치, {layout.BASE_WIDTH}x{layout.BASE_HEIGHT})")
    print("  -> py -3 -m tftcalc.cli scan --templates data/templates_set18.json "
          f"--in {args.out} --area {args.area} --out data/sim_board.json")
    if failures:
        print(f"실패 {len(failures)}건:")
        for line in failures:
            print(f"  - {line}")
    return 0 if placed else 1


if __name__ == "__main__":
    raise SystemExit(main())
