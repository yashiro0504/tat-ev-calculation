"""화면 캡처 확인 + 레이아웃 디버그 도구.

용도
----
1. 이 PC에서 캡처가 동작하는지 확인(검은 화면/권한 문제 판별)
2. 캡처 결과를 BMP로 저장 -> 실제 게임 화면에서 좌표를 눈으로 확인/보정
3. 저장된 BMP 에 대해 유닛 인식(템플릿)을 시험

사용 예
-------
  py -3 scripts/check_capture.py --out shot.bmp
  py -3 scripts/check_capture.py --window "League of Legends (TM) Client" --out lol.bmp
  py -3 scripts/check_capture.py --in shot.bmp --templates data/templates_set18.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc.cv import fingerprint, layout, screen  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="화면 캡처 확인 / 레이아웃 디버그")
    parser.add_argument("--out", default=None, help="캡처를 BMP 로 저장")
    parser.add_argument("--in", dest="source", default=None, help="BMP 파일을 입력으로 사용")
    parser.add_argument("--window", default=None, help="창 제목(주면 그 창 영역만)")
    parser.add_argument("--region", default=None, help="영역 캡처 'x,y,w,h'")
    parser.add_argument("--templates", default=None, help="템플릿 JSON(있으면 유닛 인식 시험)")
    parser.add_argument("--shop", action="store_true", help="상점 5칸만 인식")
    args = parser.parse_args(argv)

    if args.source:
        image = screen.load_bmp(args.source)
        print(f"[입력] {args.source}: {image.width}x{image.height} (BMP)")
    elif args.window:
        image = screen.capture_window(args.window)
        if image is None:
            print(f"[오류] 창을 찾지 못했습니다: {args.window}")
            return 2
        print(f"[캡처] 창 '{args.window}': {image.width}x{image.height}")
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

    if args.templates:
        template_set = fingerprint.TemplateSet.load(args.templates)
        print(f"[템플릿] {args.templates}: {len(template_set.templates)}개 (그리드 {template_set.grid})")
        regions = (
            layout.SHOP_SLOTS if args.shop else layout.BENCH_SLOTS + layout.SHOP_SLOTS
        )
        print(f"{'영역':>10}{'인식':>16}{'점수':>8}{'마진':>8}  판정")
        for name, box in regions:
            region = image.crop(*box)
            match = fingerprint.classify(region, template_set)
            flag = "확인 필요" if match.needs_review else "확정"
            print(
                f"{name:>10}{match.name:>16}{match.score:>8.2f}{match.margin:>8.2f}  {flag}"
            )
    print(
        "\n※ 좌표가 어긋나면 tftcalc/cv/layout.py 의 비율값을 조정하세요 "
        "(1920x1080 기준으로 정의되어 있고, 다른 해상도는 비율로 환산됩니다)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
