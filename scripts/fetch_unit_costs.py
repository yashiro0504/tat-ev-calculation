"""tft.ninja 유닛 페이지에서 (이름, 코스트, 특성)을 긁어 JSON 으로 저장한다.

왜 스크립트인가
--------------
컴프 JSON 의 ``units[].cost`` 는 **반드시 실제 세트 값**이어야 한다. 손으로 65개를
옮겨 적으면 반드시 틀리고, 세트/패치가 바뀔 때마다 다시 틀린다. 그래서 코스트는
사람이 아니라 이 스크립트가 만들어 ``data/set18_unit_costs.json`` 에 저장한다.

사용법
------
  py -3 scripts/fetch_unit_costs.py --units karma,sentinel,leona
  py -3 scripts/fetch_unit_costs.py --from-comps data/comps_set18.json
  py -3 scripts/fetch_unit_costs.py --units karma --dry-run
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "set18_unit_costs.json"
URL_TEMPLATE = "https://tft.ninja/units/{slug}"
SOURCE = "tft.ninja /units/<slug> (헤더의 '이름 코스트 특성' 파싱)"

HEADER_PATTERN = re.compile(
    r"([A-Z][A-Za-z'\u2019.\- ]{2,26}?)\s+([1-5])\s+"
    r"([A-Za-z'\u2019.\- ]{3,70}?)\s+Patch\s+([0-9][0-9.]*)"
)


def fetch(slug: str, timeout: int = 25) -> str:
    request = urllib.request.Request(
        URL_TEMPLATE.format(slug=slug),
        headers={"User-Agent": "tft-ev-calculator/0.1 (personal use, cost lookup)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "ignore")


def to_text(raw_html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", raw_html, flags=re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def parse_unit(slug: str, text: str) -> dict[str, object]:
    """헤더에서 (이름, 코스트, 특성)을 뽑는다.

    헤더 앞에 내비게이션 단어(Guides/Sign In 등)가 붙어 나오므로,
    슬러그의 토큰 수만큼 **뒤에서 잘라** 이름을 확정한다.
    """
    wanted = normalize(slug)
    token_count = max(1, len(slug.split("-")))
    for match in HEADER_PATTERN.finditer(text):
        raw_name, cost, traits, patch = match.groups()
        words = raw_name.split()
        name = " ".join(words[-token_count:]) if len(words) >= token_count else raw_name
        if normalize(name) != wanted:
            continue
        return {
            "name": name.strip(),
            "cost": int(cost),
            "traits": [trait.strip() for trait in traits.split() if trait.strip()],
            "patch": patch,
            "slug": slug,
            "source": SOURCE,
        }
    raise ValueError(
        f"'{slug}': 슬러그와 일치하는 헤더를 찾지 못했습니다(페이지 구조 변경 가능성). "
        "오프라인 확인 후 필요하면 정규식을 조정하세요."
    )



def load_existing(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("units", {}))


def save(path: Path, units: dict[str, dict[str, object]], patch: str | None) -> None:
    payload = {
        "_readme": [
            "이 파일은 scripts/fetch_unit_costs.py 가 생성한다. 손으로 고치지 말 것.",
            "용도: 컴프 JSON 의 units[].cost 를 채우기 전에 실제 값을 확인하는 근거.",
            "컴프(comps_*.json)의 '구성'은 사람이 검토해 확정한다.",
            "갱신: py -3 scripts/fetch_unit_costs.py --from-comps data/comps_set18.json",
        ],
        "source": SOURCE,
        "patch": patch,
        "units": dict(sorted(units.items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def units_from_comps(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    seen: list[str] = []
    for comp in data.get("comps", []):
        for unit in comp.get("units", []):
            slug = unit.get("slug") or str(unit["champion"]).lower().replace("'", "")
            slug = re.sub(r"[^a-z0-9\-]", "", slug.replace(" ", "-"))
            if slug not in seen:
                seen.append(slug)
    return seen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="유닛 코스트 수집(근거 확보용)")
    parser.add_argument("--units", default=None, help="쉼표 구분 슬러그 목록")
    parser.add_argument("--from-comps", default=None, help="컴프 JSON 에서 슬러그 추출")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--sleep", type=float, default=0.4, help="요청 간 대기(초)")
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 출력만")
    args = parser.parse_args(argv)

    slugs: list[str] = []
    if args.units:
        slugs += [s.strip() for s in args.units.split(",") if s.strip()]
    if args.from_comps:
        slugs += units_from_comps(Path(args.from_comps))
    slugs = list(dict.fromkeys(slugs))
    if not slugs:
        parser.error("--units 또는 --from-comps 중 하나는 필요합니다.")

    out_path = Path(args.out)
    units = load_existing(out_path)
    patch: str | None = None
    failures: list[str] = []

    for index, slug in enumerate(slugs, start=1):
        try:
            entry = parse_unit(slug, to_text(fetch(slug)))
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            failures.append(f"{slug}: {exc}")
            print(f"[{index}/{len(slugs)}] {slug:<14} 실패: {exc}")
            continue
        units[slug] = entry
        patch = str(entry.get("patch") or patch or "") or patch
        print(
            f"[{index}/{len(slugs)}] {slug:<14} -> {entry['name']} "
            f"{entry['cost']}코 | {', '.join(entry['traits'])}"
        )
        time.sleep(args.sleep)

    if args.dry_run:
        print("\n[dry-run] 저장하지 않았습니다.")
    else:
        save(out_path, units, patch)
        print(f"\n저장: {out_path} (유닛 {len(units)}개)")
    if failures:
        print(f"\n실패 {len(failures)}건:")
        for line in failures:
            print(f"  - {line}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
