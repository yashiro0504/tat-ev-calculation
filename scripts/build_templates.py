"""아이콘 템플릿(지문) 생성.

두 가지 모드
------------
1) ``--units`` / ``--from-comps``: Riot Data Dragon 의 챔피언 아이콘(PNG)을 받아 지문 생성.
   TFT 는 일반 챔피언에 LoL 챔피언 아이콘을 그대로 쓰기 때문에 이걸로 커버된다.
   (단, Krug/Pebbles/Cinderling 같은 TFT 전용 유닛은 Data Dragon 에 없다 -> 크롭 모드로 보충)
2) ``--from-crops DIR``: **내 화면에서 딴 크롭 이미지**로 지문 생성. 파일명이 곧 라벨이다
   (예: ``Ahri.bmp``, ``Krug.bmp``).

사용 예
-------
  python scripts/build_templates.py --from-comps data/comps_set18.json
  python scripts/build_templates.py --units ahri,morgana,sett
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tftcalc.cv import fingerprint  # noqa: E402
from tftcalc.cv.screen import Image, load_bmp  # noqa: E402

DDRAGON_VERSION = "16.18.1"
ICON_URL = "https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{icon}.png"

#: 이 값 미만이면 "빈 칸일 수 있다"고 **경고**만 한다(건너뛰지는 않는다).
#: 실측(2026-09-23, 칸 223x176): 빈 상점 칸 132~490 / 실제 카드 1714~4656.
#: 다만 분산은 칸 면적에 비례하므로 벤치(130x122)처럼 작은 칸에는 그대로 못 쓴다 —
#: 그래서 하드 컷이 아니라 경고로 둔다(건너뛰기는 '이름표 그대로' 규칙이 담당).
FLAT_CROP_WARNING = 600.0

#: Data Dragon 아이콘 파일명이 이름과 다른 예외들(전부는 아니며 --map 으로 보충)
ICON_ALIASES = {
    "kogmaw": "KogMaw",
    "reksai": "RekSai",
    "masteryi": "MasterYi",
    "drmundo": "DrMundo",
    "chogath": "Chogath",
    "kaisa": "Kaisa",
    "leblanc": "Leblanc",
    "wukong": "MonkeyKing",
    "jarvaniv": "JarvanIV",
    "leesin": "LeeSin",
    "xinzhao": "XinZhao",
    "aurelionsol": "AurelionSol",
    "velkoz": "Velkoz",
}


def http_bytes(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "tft-ev-calculator/0.1 (personal use, icon fetch)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        import ssl

        context = ssl._create_unverified_context()  # noqa: S323
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return response.read()


def icon_candidates(champion: str, overrides: dict[str, str]) -> list[str]:
    """Data Dragon 아이콘 파일명 후보(대소문자 규칙이 일정하지 않아 여러 개 시도).

    DDragon 은 대소문자를 구분한다(Ahri.png vs ahri.png). 그래서 별칭 -> 단어별 대문자
    -> 원본 순으로 시도한다.
    """
    key = re.sub(r"[^a-z0-9]", "", champion.lower())
    candidates: list[str] = []
    if key in overrides:
        candidates.append(overrides[key])
    if key in ICON_ALIASES:
        candidates.append(ICON_ALIASES[key])
    words = [word for word in re.split(r"[^A-Za-z0-9]+", champion) if word]
    candidates.append("".join(word[:1].upper() + word[1:] for word in words))
    candidates.append(re.sub(r"[^A-Za-z0-9]", "", champion))
    seen: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.append(candidate)
    return seen


def icon_name(champion: str, overrides: dict[str, str]) -> str:
    """첫 번째 후보(표시/로그용). 실제 시도는 icon_candidates 를 쓴다."""
    return icon_candidates(champion, overrides)[0]


def units_from_comps(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for comp in data.get("comps", []):
        for unit in comp.get("units", []):
            champion = str(unit["champion"])
            if champion not in names:
                names.append(champion)
    return names


def build_from_ddragon(
    names: list[str], grid: int, overrides: dict[str, str]
) -> tuple[list[fingerprint.Template], list[str]]:
    templates: list[fingerprint.Template] = []
    failures: list[str] = []
    for name in names:
        last_error = ""
        image = None
        used_icon = ""
        for icon in icon_candidates(name, overrides):
            try:
                image = decode_png(
                    http_bytes(ICON_URL.format(version=DDRAGON_VERSION, icon=icon))
                )
                used_icon = icon
                break
            except (urllib.error.URLError, ValueError) as exc:
                last_error = f"{icon}: {exc}"
        if image is None:
            failures.append(f"{name} ({last_error})")
            continue
        templates.append(
            fingerprint.Template(
                name=name,
                values=fingerprint.fingerprint(image, grid=grid),
            )
        )
        print(f"[OK] {name:<16} <- {used_icon}.png ({image.width}x{image.height})")
    return templates, failures


def build_from_crops(directory: Path, grid: int) -> tuple[list[fingerprint.Template], list[str]]:
    """라벨링된 크롭 BMP 폴더 -> 템플릿. 파일명이 곧 유닛 이름이다.

    **라벨링 안 된 크롭(``shop_3``, ``bench_7`` …)은 건너뛴다.** 실측 회귀(2026-09-23):
    빈 칸 크롭 하나가 ``shop_4`` 라는 이름으로 템플릿이 되어, 다른 빈 칸을 'shop_4' 로
    **오인**했다(빈 칸끼리는 지문이 거의 같다). 이름표 그대로인 파일은 '아직 안 붙였다'는
    신호이므로, 넣지 말고 알려준다.
    """
    unlabeled = re.compile(r"^(shop|bench|board)_\d+$", re.IGNORECASE)
    templates: list[fingerprint.Template] = []
    failures: list[str] = []
    for path in sorted(directory.glob("*.bmp")):
        if unlabeled.match(path.stem):
            failures.append(
                f"{path.name}: 이름표 그대로(라벨링 필요) — 챔피언 이름으로 바꾼 뒤 다시 실행"
            )
            continue
        try:
            image = load_bmp(str(path))
        except ValueError as exc:
            failures.append(f"{path.name}: {exc}")
            continue
        values = fingerprint.fingerprint(image, grid=grid)
        if not any(values):
            failures.append(
                f"{path.name}: 지문이 단조로움(빈 칸/단색으로 보임) — 건너뜀"
            )
            continue
        variance = image.variance()
        if variance < FLAT_CROP_WARNING:
            print(
                f"[주의] {path.name}: 분산 {variance:.0f} 이 낮습니다(빈 칸일 수 있음). "
                "빈 칸 템플릿은 다른 빈 칸과 매칭돼 오인을 만듭니다."
            )
        templates.append(fingerprint.Template(name=path.stem, values=values))
        print(f"[OK] {path.stem:<16} <- {path.name} ({image.width}x{image.height}, 분산 {variance:.0f})")
    return templates, failures


def self_check(template_set: fingerprint.TemplateSet, trials: int = 1) -> dict[str, object]:
    """템플릿 자체 검증: 각 지문이 자기 자신으로 분류되는지 + 평균 마진."""
    correct = 0
    margins: list[float] = []
    ambiguous: list[str] = []
    for template in template_set.templates * trials:
        query = template.values
        scores = sorted(
            (
                (fingerprint.similarity(query, other.values), other.name)
                for other in template_set.templates
            ),
            reverse=True,
        )
        best_score, best_name = scores[0]
        margin = best_score - scores[1][0] if len(scores) > 1 else 1.0
        if best_name == template.name:
            correct += 1
        if margin < 0.05:
            ambiguous.append(f"{template.name}~{scores[1][1]}(마진 {margin:.3f})")
        margins.append(margin)
    total = len(template_set.templates) * trials
    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "mean_margin": sum(margins) / len(margins) if margins else 0.0,
        "ambiguous": ambiguous[:10],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="아이콘 템플릿(지문) 생성")
    parser.add_argument("--units", default=None, help="쉼표 구분 챔피언 이름")
    parser.add_argument("--from-comps", default=None, help="컴프 JSON 에서 챔피언 목록 추출")
    parser.add_argument("--from-crops", default=None, help="라벨링된 BMP 크롭 폴더")
    parser.add_argument("--out", default=str(ROOT / "data" / "templates_set18.json"))
    parser.add_argument("--grid", type=int, default=fingerprint.DEFAULT_GRID)
    parser.add_argument("--map", default=None, help="아이콘 파일명 예외 'name=Icon,...'")
    args = parser.parse_args(argv)

    overrides: dict[str, str] = {}
    if args.map:
        for pair in args.map.split(","):
            key, _, value = pair.partition("=")
            overrides[re.sub(r"[^a-z0-9]", "", key.lower())] = value.strip()

    if args.from_crops:
        templates, failures = build_from_crops(Path(args.from_crops), args.grid)
        source = f"화면 크롭({args.from_crops})"
    else:
        names: list[str] = []
        if args.from_comps:
            names += units_from_comps(Path(args.from_comps))
        if args.units:
            names += [name.strip() for name in args.units.split(",") if name.strip()]
        names = list(dict.fromkeys(names))
        if not names:
            parser.error("--units / --from-comps / --from-crops 중 하나는 필요합니다.")
        templates, failures = build_from_ddragon(names, args.grid, overrides)
        source = f"Riot Data Dragon {DDRAGON_VERSION} 챔피언 아이콘"

    template_set = fingerprint.TemplateSet(
        grid=args.grid,
        templates=templates,
        source=source,
        meta={"out": args.out, "count": len(templates)},
    )
    template_set.save(args.out)
    print(f"\n저장: {args.out} (템플릿 {len(templates)}개, 그리드 {args.grid})")

    report = self_check(template_set)
    print(
        f"[자체 검증] 자기 분류 정확도 {report['accuracy'] * 100:.1f}% / "
        f"평균 마진 {report['mean_margin']:.3f}"
    )
    if report["ambiguous"]:
        print("  마진이 작아 오분류 위험이 있는 쌍:")
        for line in report["ambiguous"]:
            print(f"    - {line}")

    if failures:
        if args.from_crops:
            print(f"\n건너뜀 {len(failures)}건 (크롭 폴더: {args.from_crops}):")
            for line in failures:
                print(f"  - {line}")
            print(
                "  -> 파일명을 챔피언 이름으로 바꾸고 다시 실행하세요. "
                "빈 칸 크롭은 넣지 않습니다(다른 빈 칸과 매칭돼 오인을 만듭니다)."
            )
        else:
            print(f"\n실패/건너뜀 {len(failures)}건 (TFT 전용 유닛은 Data Dragon 에 없습니다):")
            for line in failures:
                print(f"  - {line}")
            print(
                "  -> 이 유닛들은 게임 화면에서 크롭해 data/crops/<이름>.bmp 로 넣고 "
                "`--from-crops data/crops` 로 생성하세요."
            )
    return 0 if templates else 1


def decode_png(data: bytes) -> Image:
    """최소 PNG 디코더(8비트, 컬러타입 0/2/3/6). 외부 라이브러리 없이 아이콘을 읽기 위함."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("PNG 시그니처가 아닙니다.")
    position = 8
    idat = b""
    palette = b""
    width = height = bit_depth = color_type = interlace = None
    while position < len(data):
        (length,) = struct.unpack_from(">I", data, position)
        position += 4
        chunk_type = data[position : position + 4]
        position += 4
        chunk = data[position : position + length]
        position += length + 4  # CRC 건너뜀
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
        elif chunk_type == b"PLTE":
            palette = chunk
        elif chunk_type == b"IDAT":
            idat += chunk
        elif chunk_type == b"IEND":
            break
    if bit_depth != 8:
        raise ValueError(f"{bit_depth}비트 PNG 는 지원하지 않습니다(8비트만).")
    if interlace:
        raise ValueError("인터레이스 PNG 는 지원하지 않습니다.")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise ValueError(f"지원하지 않는 컬러타입: {color_type}")

    raw = zlib.decompress(idat)
    stride = width * channels
    previous = bytearray(stride)
    rows: list[bytearray] = []
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position : position + stride])
        position += stride
        if filter_type == 1:
            for index in range(channels, stride):
                line[index] = (line[index] + line[index - channels]) & 0xFF
        elif filter_type == 2:
            for index in range(stride):
                line[index] = (line[index] + previous[index]) & 0xFF
        elif filter_type == 3:
            for index in range(stride):
                left = line[index - channels] if index >= channels else 0
                line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        elif filter_type == 4:
            for index in range(stride):
                left = line[index - channels] if index >= channels else 0
                up = previous[index]
                upleft = previous[index - channels] if index >= channels else 0
                estimate = left + up - upleft
                pa, pb, pc = abs(estimate - left), abs(estimate - up), abs(estimate - upleft)
                predictor = left if (pa <= pb and pa <= pc) else (up if pb <= pc else upleft)
                line[index] = (line[index] + predictor) & 0xFF
        rows.append(line)
        previous = line

    pixels = bytearray(width * height * 4)
    for row_index, line in enumerate(rows):
        for column in range(width):
            base = column * channels
            if color_type == 3:
                palette_index = line[base] * 3
                red, green, blue = (
                    palette[palette_index],
                    palette[palette_index + 1],
                    palette[palette_index + 2],
                )
            elif color_type in (0, 4):
                red = green = blue = line[base]
            else:
                red, green, blue = line[base], line[base + 1], line[base + 2]
            target = (row_index * width + column) * 4
            pixels[target] = blue
            pixels[target + 1] = green
            pixels[target + 2] = red
            pixels[target + 3] = 255
    return Image(width=width, height=height, pixels=pixels)


if __name__ == "__main__":
    raise SystemExit(main())
