"""Riot Data Dragon 에서 TFT 아이템 '조합식(부품 2개)'을 수집한다.

왜 스크립트인가
--------------
조합식을 손으로 적으면 반드시 틀리고(세트마다 신규 아이템 추가), 웹 페이지는 조합식을
이미지로만 그려서 텍스트로 안 나온다. 반면 Data Dragon 의 ``tft-item.json`` 에는
제작 가능한 아이템의 ``composition``(부품 id 배열)이 구조화되어 들어 있다.

사용법
------
  py -3 scripts/fetch_item_recipes.py                 # 제작 가능 아이템 전체
  py -3 scripts/fetch_item_recipes.py --only jeweled-gauntlet,blue-buff
  py -3 scripts/fetch_item_recipes.py --check "Jeweled Gauntlet,Blue Buff"
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
DEFAULT_OUT = ROOT / "data" / "set18_item_recipes.json"
VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
ITEMS_URL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/tft-item.json"
SOURCE = "tft.ninja /items/<slug> (부품 이미지 파싱) + Riot Data Dragon tft-item.json(부품명)"

#: 부품 9종 (이 중 2개가 합쳐져 완성 아이템이 된다)
COMPONENT_NAMES = {
    "B.F. Sword",
    "Recurve Bow",
    "Needlessly Large Rod",
    "Tear of the Goddess",
    "Chain Vest",
    "Negatron Cloak",
    "Giant's Belt",
    "Sparring Gloves",
    "Spatula",
}

#: 기본 수집 목록: 컴프 데이터에서 쓰는 아이템 + 자주 쓰이는 나머지
DEFAULT_ITEMS = [
    "Jeweled Gauntlet",
    "Blue Buff",
    "Rabadon's Deathcap",
    "Archangel's Staff",
    "Void Staff",
    "Morellonomicon",
    "Hextech Gunblade",
    "Spear of Shojin",
    "Nashor's Tooth",
    "Giant Slayer",
    "Guinsoo's Rageblade",
    "Deathblade",
    "Infinity Edge",
    "Last Whisper",
    "Red Buff",
    "Kraken's Fury",
    "Warmog's Armor",
    "Spirit Visage",
    "Crownguard",
    "Steadfast Heart",
    "Protector's Vow",
    "Bramble Vest",
    "Dragon's Claw",
    "Sunfire Cape",
    "Gargoyle Stoneplate",
    "Ionic Spark",
    "Adaptive Helm",
    "Evenshroud",
    "Quicksilver",
    "Sterak's Gage",
    "Titan's Resolve",
    "Striker's Flail",
]


def http_json(url: str, timeout: int = 30) -> object:
    request = urllib.request.Request(
        url, headers={"User-Agent": "tft-ev-calculator/0.1 (personal use, item recipes)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "ignore"))
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        # Data Dragon 인증서 체인이 이 PC의 신뢰 저장소에 없을 때의 폴백.
        # 공개 읽기 전용 JSON 이고 인증정보를 보내지 않으므로 검증을 건너뛴다(경고 출력).
        import ssl

        print(f"[경고] 인증서 검증 실패 -> 검증 없이 재시도: {url}")
        context = ssl._create_unverified_context()  # noqa: S323
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return json.loads(response.read().decode("utf-8", "ignore"))


def latest_version() -> str:
    versions = http_json(VERSIONS_URL)
    return str(versions[0])


def build_recipes(version: str) -> dict[str, dict[str, object]]:
    payload = http_json(ITEMS_URL.format(version=version))
    data = payload.get("data", {})
    id_to_name = {key: str(value.get("name", "")) for key, value in data.items()}

    # 부품 id 집합: 이름이 부품명과 일치하는 항목의 id (경로형 키도 함께 포함)
    component_ids: set[str] = set()
    for key, name in id_to_name.items():
        if name in COMPONENT_NAMES:
            component_ids.add(key)
            component_ids.add(str(data[key].get("id", key)))

    recipes: dict[str, dict[str, object]] = {}
    for key, value in data.items():
        composition = [str(component) for component in (value.get("composition") or [])]
        if len(composition) != 2:
            continue
        if not all(component in component_ids for component in composition):
            continue  # 부품 2개 조합이 아닌 것(유물/상징 등)은 제외
        components = [id_to_name.get(component, component) for component in composition]
        if not all(component in COMPONENT_NAMES for component in components):
            continue
        name = str(value.get("name", "")).strip()
        if not name:
            continue
        recipes[name] = {
            "components": sorted(components),
            "component_ids": sorted(composition),
            "id": value.get("id"),
            "source": SOURCE,
            "version": version,
        }
    return recipes


def fetch_html(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": "tft-ev-calculator/0.1 (personal use, item recipes)"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "ignore")


def build_recipes_from_slugs(
    slugs: list[str], sleep: float = 0.2
) -> tuple[dict[str, dict[str, object]], list[str]]:
    """슬러그로 아이템 페이지를 읽어 조합식을 만든다(이름은 페이지 title 에서 추출).

    슬러그를 쓰는 이유: 아이템 이름에는 아포스트로피가 많아 셸 인용이 깨진다.
    """
    recipes: dict[str, dict[str, object]] = {}
    failures: list[str] = []
    for slug in slugs:
        try:
            html = fetch_html(f"https://tft.ninja/items/{slug}")
        except urllib.error.URLError as exc:
            failures.append(f"{slug}: 요청 실패({exc})")
            continue
        title = re.search(r"<title>([^<]+?)\s*TFT", html)
        name = html_module.unescape(title.group(1).strip()) if title else slug
        matches = re.findall(r"DA_Component_([A-Za-z0-9_]+)\.png", html)
        # 같은 부품 2개 조합(예: 눈물+눈물)도 있으므로 '연속한 두 부품'을 찾는다.
        pair: list[str] | None = None
        for index in range(len(matches) - 1):
            if matches[index] in _COMPONENT_SUFFIX_NAMES and (
                matches[index + 1] in _COMPONENT_SUFFIX_NAMES
            ):
                pair = [matches[index], matches[index + 1]]
                break
        if pair is None:
            failures.append(
                f"{slug}({name}): 연속한 부품 2개를 찾지 못함(발견: {matches})"
            )
            continue
        component_names = sorted(_component_names(pair))
        recipes[name] = {
            "components": component_names,
            "source": f"tft.ninja /items/{slug} (부품 이미지 파싱)",
            "slug": slug,
        }
        print(f"[OK] {name:<24} = {' + '.join(component_names)}")
        time.sleep(sleep)
    return recipes, failures


#: DA_Component_* 접미사 -> 실제 부품명 (Data Dragon 과 교차 확인용 기본 매핑)
_COMPONENT_SUFFIX_NAMES = {
    "BFSword": "B.F. Sword",
    "RecurveBow": "Recurve Bow",
    "NeedlesslyLargeRod": "Needlessly Large Rod",
    "TearOfTheGoddess": "Tear of the Goddess",
    "ChainVest": "Chain Vest",
    "NegatronCloak": "Negatron Cloak",
    "GiantsBelt": "Giant's Belt",
    "SparringGloves": "Sparring Gloves",
    "Spatula": "Spatula",
}


def _component_names(suffixes: list[str]) -> list[str]:
    return [
        _COMPONENT_SUFFIX_NAMES.get(suffix, suffix)
        for suffix in suffixes
        if suffix in _COMPONENT_SUFFIX_NAMES
    ]


def slug_variants(name: str) -> list[str]:
    base = name.lower()
    no_apostrophe = base.replace("'", "").replace("\u2019", "")
    variants = [
        re.sub(r"[^a-z0-9]+", "-", no_apostrophe).strip("-"),
        re.sub(r"[^a-z0-9]+", "-", base).strip("-"),
        re.sub(r"[^a-z0-9]+", "", base),
    ]
    return list(dict.fromkeys(v for v in variants if v))


def build_recipes_from_html(
    item_names: list[str],
    id_to_name: dict[str, str],
    sleep: float = 0.4,
) -> tuple[dict[str, dict[str, object]], list[str]]:
    """tft.ninja 아이템 페이지의 구성 이미지(DA_Component_*)로 조합식을 만든다.

    페이지 구조(확인됨): 아이템 아이콘이 몇 번 나온 뒤 **부품 이미지가 연속으로** 나오고
    다시 아이템 아이콘이 나온다. 그래서 '연속된 DA_Component_*' 가 곧 조합식이다.
    """
    recipes: dict[str, dict[str, object]] = {}
    failures: list[str] = []
    for name in item_names:
        found: tuple[str, list[str]] | None = None
        for slug in slug_variants(name):
            try:
                html = fetch_html(f"https://tft.ninja/items/{slug}")
            except urllib.error.URLError as exc:
                failures.append(f"{name}: {slug} 요청 실패({exc})")
                break
            components = list(
                dict.fromkeys(
                    re.findall(r"DA_Component_([A-Za-z0-9_]+)\.png", html)
                )
            )
            names = [
                id_to_name.get(f"DA_Component_{component}", component)
                for component in components
            ]
            names = [n for n in names if n in COMPONENT_NAMES]
            if len(names) == 2:
                found = (slug, sorted(names))
                break
            time.sleep(sleep)
        if found is None:
            failures.append(f"{name}: 조합식(부품 2개)을 찾지 못함")
            continue
        slug, components = found
        recipes[name] = {
            "components": components,
            "source": f"tft.ninja /items/{slug} (DA_Component 이미지 파싱)",
            "slug": slug,
        }
        print(f"[OK] {name:<24} = {' + '.join(components)}")
        time.sleep(sleep)
    return recipes, failures
    """아이템 페이지 HTML 에서 이미지 참조 순서를 보여준다(조합식 위치 확인용)."""
    url = f"https://tft.ninja/items/{slug}"
    html = fetch_html(url)
    matches = re.findall(r"[/\w\-]*?(TFT_Item_[A-Za-z0-9_]+|DA_[A-Za-z0-9_]+)\.png", html)
    print(f"--- {url} : 이미지 {len(matches)}개 ---")
    for index, name in enumerate(matches[:30]):
        print(f"  {index:>2}: {name}")
    return 0
    """항목의 원본 필드를 그대로 보여준다(조합식이 왜 안 잡히는지 진단)."""
    payload = http_json(ITEMS_URL.format(version=version))
    data = payload.get("data", {})
    keys = set()
    for name in names:
        found = [
            (key, value)
            for key, value in data.items()
            if str(value.get("name", "")).strip().lower() == name.strip().lower()
        ]
        print(f"--- {name}: {len(found)}개 항목 ---")
        for key, value in found[:3]:
            print(f"  key={key}")
            for field in ("id", "name", "composition", "categories", "unique"):
                if field in value:
                    print(f"    {field} = {value[field]!r}")
            keys.add(key)
    return 0 if keys else 1


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def save(path: Path, recipes: dict[str, dict[str, object]], version: str) -> None:
    payload = {
        "_readme": [
            "이 파일은 scripts/fetch_item_recipes.py 가 생성한다. 손으로 고치지 말 것.",
            "components = 그 아이템을 만드는 부품 2개. 부품 수급 계산의 기반 데이터.",
            "'부품 2개 조합'이 아닌 아이템(유물/상징/찬란한 등)은 의도적으로 제외된다.",
            "갱신: py -3 scripts/fetch_item_recipes.py",
        ],
        "source": SOURCE,
        "data_dragon_version": version,
        "component_names": sorted(COMPONENT_NAMES),
        "recipes": dict(sorted(recipes.items())),
        "by_slug": {slugify(name): name for name in sorted(recipes)},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")



def load_recipes(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    # 이전 버전이 HTML 엔티티(&#x27;)를 이름에 남긴 경우를 정리한다.
    return {
        html_module.unescape(str(name)): dict(value)
        for name, value in raw.get("recipes", {}).items()
    }


def check(recipes: dict[str, dict[str, object]], wanted: list[str]) -> int:
    """특정 아이템의 조합식을 확인 출력. 없으면 실패 코드를 돌려준다."""
    exit_code = 0
    for item in wanted:
        entry = recipes.get(item) or next(
            (value for key, value in recipes.items() if slugify(key) == slugify(item)),
            None,
        )
        if entry is None:
            print(f"[없음] {item}: 제작 조합식이 없습니다(유물/상징/이름 확인 필요).")
            exit_code = 1
            continue
        print(f"[OK] {item} = {' + '.join(str(c) for c in entry['components'])}")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TFT 아이템 조합식 수집")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--version", default=None, help="Data Dragon 버전(기본: 최신)")
    parser.add_argument("--only", default=None, help="쉼표 구분 아이템 이름(부분 갱신)")
    parser.add_argument("--check", default=None, help="쉼표 구분 아이템 이름(확인만)")
    parser.add_argument("--inspect", default=None, help="쉼표 구분 아이템 이름(원본 필드 진단)")
    parser.add_argument("--inspect-html", default=None, help="아이템 slug(HTML 이미지 순서 진단)")
    parser.add_argument(
        "--slugs", default=None, help="쉼표 구분 아이템 slug (권장: 아포스트로피 문제 없음)"
    )
    args = parser.parse_args(argv)

    out_path = Path(args.out)
    if args.inspect_html:
        return inspect_html(args.inspect_html)
    if args.inspect:
        version = args.version or latest_version()
        return inspect(version, [s.strip() for s in args.inspect.split(",") if s.strip()])
    if args.check:
        wanted = [s.strip() for s in args.check.split(",") if s.strip()]
        return check(load_recipes(out_path), wanted)

    version = args.version or latest_version()

    if args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
        fresh, failures = build_recipes_from_slugs(slugs)
    else:
        payload = http_json(ITEMS_URL.format(version=version))
        data = payload.get("data", {})
        id_to_name = {key: str(value.get("name", "")) for key, value in data.items()}
        id_to_name.update(
            {str(value.get("id")): str(value.get("name", "")) for value in data.values()}
        )
        if args.only:
            item_names = [s.strip() for s in args.only.split(",") if s.strip()]
        else:
            item_names = DEFAULT_ITEMS
            print(f"기본 목록 {len(item_names)}개 아이템의 조합식을 수집합니다.")
        fresh, failures = build_recipes_from_html(item_names, id_to_name)

    recipes = load_recipes(out_path)
    recipes.update(fresh)
    save(out_path, recipes, version)
    print(f"저장: {out_path} (아이템 {len(recipes)}개, 이번 추가 {len(fresh)}개)")
    if failures:
        print(f"실패 {len(failures)}건:")
        for line in failures:
            print(f"  - {line}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
