"""화면 캡처 확인 + 레이아웃 디버그 도구.

용도
----
1. 이 PC에서 캡처가 동작하는지 확인(검은 화면/권한 문제 판별)
2. 캡처 결과를 BMP로 저장 -> 실제 게임 화면에서 좌표를 눈으로 확인/보정
3. 저장된 BMP 에 대해 유닛 인식(템플릿)을 시험

사용 예
-------
  python scripts/check_capture.py --out shot.bmp                 # 전체 화면 캡처 + 저장
  python scripts/check_capture.py --window "Teamfight Tactics" --out shot.bmp   # 창의 클라이언트 영역
  python scripts/check_capture.py --window TFT --out shot.bmp                  # 창모드(제목 뒤 공백/대소문자 무시)
  python scripts/check_capture.py --region 0,0,1920,1080 --out shot.bmp
  python scripts/check_capture.py --in shot.bmp --shop           # 저장본으로 상점 5칸 인식 시험
  python scripts/check_capture.py --in shot.bmp --layout data/layout_1920x1080.json --shop
  python scripts/check_capture.py --in shot.bmp --no-templates   # 인식 없이 캡처 상태만

기본적으로 data/templates_set18.json 으로 벤치+상점 인식을 시험하고, 칸별 픽셀 좌표를 함께
출력한다 -> 그 좌표가 아이콘과 어긋나면 --layout JSON(비율 0~1)으로 보정한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc.cv import fingerprint, layout, screen  # noqa: E402
from tftcalc.render import pad  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="화면 캡처 확인 / 레이아웃 디버그")
    parser.add_argument("--out", default=None, help="캡처를 BMP 로 저장")
    parser.add_argument("--in", dest="source", default=None, help="BMP 파일을 입력으로 사용")
    parser.add_argument(
        "--window", default=None, help="창 제목(주면 그 창의 클라이언트 영역만 — 창모드 권장)"
    )
    parser.add_argument("--region", default=None, help="영역 캡처 'x,y,w,h'")
    parser.add_argument(
        "--templates",
        default=str(ROOT / "data" / "templates_set18.json"),
        help="템플릿 JSON(있으면 유닛 인식 시험). 기본: data/templates_set18.json",
    )
    parser.add_argument(
        "--no-templates", action="store_true", help="템플릿 인식 시험을 건너뛴다"
    )
    parser.add_argument("--shop", action="store_true", help="상점 5칸만 인식")
    parser.add_argument(
        "--layout", default=None, help="좌표 오버라이드 JSON(기본: data/layout_1920x1080.json)"
    )
    args = parser.parse_args(argv)

    if args.source:
        image = screen.load_bmp(args.source)
        print(f"[입력] {args.source}: {image.width}x{image.height} (BMP)")
    elif args.window:
        image = screen.capture_client(args.window)
        if image is None:
            print(f"[오류] 창을 찾지 못했습니다: {args.window}")
            return 2
        print(f"[캡처] 창 '{args.window}' 클라이언트 영역: {image.width}x{image.height}")
    elif args.region:
        x, y, width, height = (int(value) for value in args.region.split(","))
        image = screen.capture(x, y, width, height)
        print(f"[캡처] 영역 {args.region}: {image.width}x{image.height}")
    else:
        if not screen.is_supported():
            print("[오류] 화면 캡처는 Windows(GDI)에서만 지원됩니다.")
            return 2
        image = screen.capture()
        print(f"[캡처] 전체 화면: {image.width}x{image.height}")

    print(f"  분산(검은 화면 판별): {image.variance():.1f} (0에 가까우면 캡처 실패 의심)")
    print(f"  샘플 픽셀(중앙): {image.pixel(image.width // 2, image.height // 2)}")

    if args.out:
        screen.save_bmp(image, args.out)
        print(f"  저장: {args.out} (BMP - 뷰어로 열어 좌표를 확인하세요)")

    if args.templates and not args.no_templates:
        template_path = Path(args.templates)
        if not template_path.exists():
            print(f"[알림] 템플릿 파일이 없어 인식 시험을 건너뜁니다: {template_path}")
        else:
            template_set = fingerprint.TemplateSet.load(template_path)
            overrides = layout.load_overrides(args.layout)
            print(
                f"[템플릿] {template_path}: {len(template_set.templates)}개 "
                f"(그리드 {template_set.grid}, 출처: {template_set.source})"
            )
            regions = (
                layout.resolve("shop", overrides)
                if args.shop
                else layout.resolve("bench", overrides) + layout.resolve("shop", overrides)
            )
            print(
                f"{pad('영역', 10, '>')}{pad('인식', 16, '>')}"
                f"{pad('점수', 8, '>')}{pad('마진', 8, '>')}  픽셀(x,y,w,h)  판정"
            )
            for name, box in regions:
                x, y, width, height = layout.to_pixels(box, image.width, image.height)
                region = image.crop(x, y, width, height)
                match = fingerprint.classify(region, template_set)
                flag = "확인 필요" if match.needs_review else "확정"
                print(
                    f"{name:>10}{match.name:>16}{match.score:>8.2f}{match.margin:>8.2f}"
                    f"  {x:>4},{y:>4},{width:>4},{height:>3}  {flag}"
                )
    print(
        "\n※ 위 픽셀 좌표가 실제 아이콘과 어긋나면: --layout data/layout_1920x1080.json (비율 0~1) "
        "또는 tftcalc/cv/layout.py 의 비율값을 조정하세요.\n"
        "  (좌표는 비율이라 해상도가 달라도 그대로 환산됩니다)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
