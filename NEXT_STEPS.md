# 작업 이어하기 가이드 (집에서 이어서)

> 이 문서는 **다른 PC에서 바로 이어서 작업**하기 위한 런북입니다.
> 현재 상태: 커밋 `ce27dd5` (main), 테스트 254개 전부 통과, CLI 13개 명령, 외부 의존성 0개.

---

## 0. 집 PC에서 5분 안에 실행 상태 만들기

```powershell
git clone https://github.com/yashiro0504/tat-ev-calculation.git
cd tat-ev-calculation          # (저장소 이름 그대로) 또는 tft-ev-calculator
python -m tftcalc.cli selftest  # 환경/데이터 자기점검
```

**설치할 것이 없습니다.** Python 3.12+ 표준 라이브러리만 씁니다(ctypes 포함). `requirements.txt`를 만들지 마세요 — 무의존성이 이 프로젝트의 장점입니다.

전체 테스트(13개 파일, 254개):
```powershell
python -m unittest discover -s tests -t .      # 가장 간단(254 tests, OK)
```
`tests/__init__.py` 를 추가해 discover 가 동작합니다. 파일별로 돌리려면:

```powershell
(python tests\test_pool_math.py & python tests\test_comp.py & python tests\test_items.py & `
 python tests\test_economy.py & python tests\test_survival.py & python tests\test_report.py & `
 python tests\test_cv.py & python tests\test_scan.py & python tests\test_cli.py & `
 python tests\test_render.py & python tests\test_rules.py & python tests\test_trials_defaults.py & `
 python tests\test_ocr.py) `
 2>&1 | Select-String 'Ran |^OK|FAILED'
```
기대 출력: `Ran 39/18/15/26/16/6/27/26/32/20/8/4/17 tests` + 각각 `OK` (= 254개).

> **함정 1**: 실행기는 PC마다 다르다 — `python` 이 Microsoft Store 스텁이면 `py -3`,
> `py` 런처가 없으면 `python`. 아래 예시는 **`python` 기준**이다.
> **함정 2**: 한글 경로/출력 때문에 깨져 보이면 `cmd /c "set PYTHONIOENCODING=utf-8 && python ..."` 로 실행하세요.

---

## 1. 남은 작업 A — 좌표 캘리브레이션 (게임 켜고 10분, 최우선)

`tftcalc/cv/layout.py`의 좌표는 **공개 UI 배치를 보고 넣은 추정값**입니다. 실제 화면에서 1회만 맞추면 됩니다.

```powershell
# 1) TFT를 창모드(또는 전체화면 창모드)로 띄우고 상점이 보이는 상태에서
python scripts\check_capture.py --out shot.bmp                 # 캡처 + 저장(인식 시험 포함)
python scripts\check_capture.py --window "Teamfight Tactics" --out shot.bmp   # 특정 창만
python scripts\check_capture.py --in shot.bmp --shop           # 저장본으로 상점 5칸 인식
python scripts\check_capture.py --in shot.bmp --no-templates   # 캡처 상태만 확인
```

`--in shot.bmp --shop` 이 출력하는 표를 그대로 쓰면 됩니다(실측 예):
```
        영역              인식      점수      마진  픽셀(x,y,w,h)  판정
    shop_1            Ahri    0.97    0.24   270, 972, 253, 95  확정
    shop_2         Morgana    0.97    0.28   551, 972, 253, 95  확정
    shop_5         unknown    0.00    0.00  1394, 972, 253, 95  확인 필요
```
`픽셀(x,y,w,h)` 열이 **보정용 좌표**입니다. `shot.bmp`를 열어 사각형이 아이콘과 어긋나면,
그 차이를 `[0,1]` 비율로 환산해 아래 JSON에 넣으면 됩니다(칸 순서는 왼쪽→오른쪽).

`shot.bmp`를 열어 **오버레이 사각형이 각 칸 아이콘과 정확히 겹치는지** 봅니다.
어긋나면 `data\layout_1920x1080.json`을 만들어 보정합니다(비율 좌표, 0~1):

```json
{
  "bench": [[0.3000, 0.8680, 0.0410, 0.0760], [0.3450, 0.8680, 0.0410, 0.0760], "..."],
  "shop":  [[0.1405, 0.8900, 0.1320, 0.0960], "..."],
  "board": [[0.3155, 0.3620, 0.0450, 0.0800], "..."]
}
```
* **비율 좌표라서 해상도 무관**합니다. 집 모니터가 2560×1440이어도 `[0,1]` 값이면 그대로 동작합니다(정수 픽셀이면 깨집니다).
* 순서는 `layout.BENCH_SLOTS` / `SHOP_SLOTS` / `BOARD_SLOTS` 순서(= 화면 왼쪽→오른쪽)와 같아야 합니다.
* `data/layout_1920x1080.json`은 **개인 캘리브레이션**이라 `.gitignore`에 있습니다. 저장소에 올리려면 `git add -f data/layout_1920x1080.json`.

**확인(게임 아이콘 그대로 인식되는지)**:
```powershell
python -m tftcalc.cli scan --templates data\templates_set18.json --in shot.bmp --area bench,shop
python -m tftcalc.cli scan --templates data\templates_set18.json --in shot.bmp --area bench,shop --out data\my_board.json
python -m tftcalc.cli report --round 4-1 --gold 60 --level 7 --hp 40 --streak -3 `
    --scan --templates data\templates_set18.json --scan-in shot.bmp --scan-out data\my_board.json `
    --snapshot data\lobby.json --comps data\comps_set18.json `
    --odds-file data\set18_shop_odds_assumed.json --components rod:2,gloves
```
* `--scan` 에는 **`--templates` 가 필수**입니다(없으면 오류 메시지로 안내합니다).
* `--snapshot` 은 상대(로비) 정보용입니다. **파일이 없어도 오류 없이** 내 정보만으로 리포트가 나옵니다.
* **스캔은 상점 칸을 `shop` 으로 분리합니다**(보유로 세지 않음). 상점에 보이는 기물은 아직 사지 않은
  것이라, 보유로 세면 판정이 낙관 편향됩니다. 지금 산다고 가정하려면 `--shop-as-owned` 를 붙이세요
  (붙이면 보유로 세고 `[가정]` 이 출력됩니다).
* `--scan-in` 을 빼면 실제 화면을 캡처합니다(게임이 떠 있어야 함).


**통과 기준(게이트)**
1. 벤치/상점 **모든 칸**의 인식 결과가 눈으로 본 것과 일치(칸이 어긋나면 이웃 칸 아이콘이 섞여 들어옵니다).
2. 게임 아이콘이 Data Dragon 아이콘과 달라 유사도가 낮게(예: 70%대) 나오면 → **크롭 템플릿** 경로:
   ```powershell
   python scripts\crop_slots.py --in shot.bmp --area shop,bench --out data\crops
   #   -> data\crops\shop_1.bmp ... bench_7.bmp (칸별 크롭)
   #   파일 이름을 유닛 이름으로 바꾼다 (파일명이 곧 라벨): shop_3.bmp -> Krug.bmp
   python scripts\build_templates.py --from-crops data\crops --out data\templates_set18.json
   ```
   게임 렌더링(비용 테두리·발광)까지 지문에 반영되어 유사도가 95%+로 올라갑니다.
   TFT 전용 유닛(Krug, Pebbles, Cinderling 등 Data Dragon에 없는 것)은 **이 방법이 유일**합니다.

3. 인식 정확도 **99% 이상** 유지(오인식은 골드를 잘못 세게 만듭니다). 애매한 칸은 도구가 알아서 `[확인 필요]`로 빼므로, 그 개수를 줄이는 게 목표입니다.


---

## 2. 남은 작업 B — 성급(별) · 숫자 인식 (✅ 골격 구현 완료)

### 구현한 것
| 파일 | 내용 |
|---|---|
| `tftcalc/cv/ocr.py` (신규) | `star_ratio`/`stars_from_ratio`/`count_stars` — 별 개수를 **밝은 픽셀 면적 비율**로 센다(분류 아님). `star_is_ambiguous` 로 **경계·과대 비율을 걸러낸다**. `split_digits`(열 방향 투영) + `read_number`(자릿수별 지문 분류, **하나라도 애매하면 `None`**) |
| `tftcalc/cv/layout.py` | `STAR_BAND`(칸 안 상대 비율) + `star_band(slot_box)` — 해상도 무관 |
| `tftcalc/cv/scan.py` | `ScanReport.info`(`gold`/`level`/`my_hp`/`stage_round`), 성급 우선순위(**지정 > 인식 > 기본값**), 미인식 고지 |
| `tftcalc/cli.py` | `--star-ocr`(켜기), `--digits`(숫자 지문 JSON) — `scan`/`report` 공통 |
| `tests/test_ocr.py` (신규) | 합성 이미지 검증: 별 0~3 · 경계 거부 · 자릿수 분리 · 숫자(7/42/105) · 미인식 `None` |

### ⚠️ 발견한 것 — 별 인식은 **기본 꺼짐**으로 바꿨다 (계획은 "기본 켜기"였음)
**실측**: 실제 Data Dragon 아이콘을 칸에 채운 합성 화면에서 별 영역의 밝은 비율이 **별 1개 면적의 약 12배**로 나왔다. 아이콘 자체의 밝은 픽셀이 별 영역에 섞이기 때문이다. 그 값을 그대로 쓰면 **3성(풀 소모 9장)** 으로 잡혀 계산이 조용히 **3배** 틀어진다.

그래서:
* 기본은 `detect_stars=False` → 기존대로 **1성 + 고지**(안전 기본값).
* `--star-ocr` 로 켜되, **애매하거나 과대 비율이면 그 칸을 스냅샷에서 빼고 `[확인 필요]`** 로 보고한다(추정 금지).
* 켜서 제대로 쓰려면 `ocr.STAR_BRIGHTNESS` / `ocr.STAR_AREA_RATIO` / `layout.STAR_BAND` 를 실게임 화면에 맞춰야 한다.

숫자도 마찬가지로 **`--digits` 가 없으면 아무것도 읽지 않고 전부 `None` + '손 입력 필요'** 다(0으로 추정하지 않음). `stage_round`('4-2')는 구분자 처리 미구현이라 읽지 않는다.

### 남은 것
* 실게임 별 영역 캘리브레이션(`check_capture.py --out shot.bmp` 로 별 위치/밝기 확인).
* `data/digits_1920x1080.json` — 실게임 숫자를 크롭해 0~9 지문 생성(개인 캘리브레이션, `.gitignore`).
* `stage_round` 구분자 파싱.

**통과 기준(게이트)**
1. 내 보드 성급 인식이 **수동 대조와 100% 일치**(20판 표본). 틀린 칸은 조용히 넘기지 말고 "확인 필요"로.
2. 골드/레벨/HP 숫자 오인식 **0건**(한 자리라도 틀리면 골드 계획이 통째로 틀어짐). 실패 시 그냥 `None`.
3. 기존 254개 테스트 전부 통과.

> 원칙 유지: 숫자/성급을 못 읽으면 **0이나 추정값을 넣지 말고 `None` + 경고**. "모르면 모른다고 말한다"가 이 프로젝트의 핵심 자산입니다.

---

## 3. 그 밖에 남은 것 (우선순위 낮음)

| 항목 | 내용 | 참고 |
|---|---|---|
| 별/숫자 캘리브레이션 | 실게임에서 `layout.STAR_BAND`·`ocr` 임계값 맞추고, 숫자 크롭으로 `data/digits_1920x1080.json` 생성 | NEXT_STEPS §2 |
| 상점 확률표 | `data/set18_shop_odds.json` 스켈레톤의 **null 52칸**을 인게임 값으로 채우기. 격자·검증·자동 로드는 완료 — **값만 입력하면 된다** | `python -m tftcalc.cli odds` 에서 `미채움 0` / README §6 W2 |
| 승률 캘리브레이션 | `--win-rate`를 실측으로 교체 → 교환비율(1%p당 골드) 산출 | README §6 W3 |
| Overwolf GEP 스파이크 | `opponent_board_pieces`가 8명인지 1명인지 30분 확인 | README §6 W5 |
| 세트 교체 대비 | 아이콘/카탈로그 **자동 수집 파이프라인**(CommunityDragon) | README §7 — 지속가능성의 전제조건 |
| README 영문판 | 지금은 한국어 단일 | 선택 |

---

## 4. 작업 규칙 (지키면 되돌리기 쉬움)

1. **커밋 전**: 해당 테스트 파일 실행 → 전체 254개 `OK` 확인. 깨진 채로 커밋하지 않습니다.
2. **미지 데이터 추정 금지**: 모르면 `UnknownOddsError` / `InvalidOddsError` / `UnknownRecipeError`
   / `UnknownLevelError` / `UnknownIncomeError` / `unknown` / `None`.
3. **4축 분리 유지**: 유닛(풀) · 아이템(부품) · 골드(시간) · 체력(생존)을 하나의 점수로 합치지 않습니다(차원 오류).
4. **의존성 추가 금지**: 표준 라이브러리만. (`ctypes` GDI 캡처, 직접 쓴 PNG 디코더/BMP I/O)
5. **커밋/푸시**:
   ```powershell
   git add -A
   git commit -m "한 줄 요약" -m "무엇을/왜 바꿨는지 + 검증 방법"
   git push
   ```
   `data/layout_1920x1080.json`, `*.bmp`, `data/my_board.json`, `data/crops/`는 `.gitignore`로 제외돼 있습니다(개인 캘리브레이션/산출물). 필요하면 `git add -f`.
6. **실행기**: 예시는 `python` 기준. Store 스텁이면 `py -3`, `py` 가 없으면 `python`.
   한글 깨지면 `cmd /c "set PYTHONIOENCODING=utf-8 && python ..."`.

---

## 5. 현재 상태 (2026-09-23 기준)

| 항목 | 값 |
|---|---|
| 최신 커밋 | `ce27dd5` (main) — 코드 리뷰 지적사항 전체 수정(버그 8 + 저우선순위 10) |
| 테스트 | **254개 전부 통과** — pool 39 / comp 18 / items 15 / economy 26 / survival 16 / report 6 / cv 27 / scan 26 / cli 32 / render 20 / rules 8 / trials_defaults 4 / ocr 17 |
| CLI 명령 | **13개** — `odds selftest unit lobby outlook items plan survive report scan comp sensitivity robustness` |
| 모듈 | `pool_math` `comp` `items` `economy` `survival` `lobby` `odds` `decision` `set_data` `trials` `render` `rules` `cli` + `cv/{screen,fingerprint,layout,scan,ocr}` |
| 스크립트 | `build_templates` `check_capture` `crop_slots` `fetch_unit_costs` `fetch_item_recipes` `simulate_scan` |
| 데이터 | 메타 덱 6 · 유닛 코스트 36 · 아이템 조합식 31 · 아이콘 지문 28 |
| 의존성 | **0개** (Python 3.12+ 표준 라이브러리) |

**CV 현재 수준**
* 캡처(1920×1080 실측) → 지문 분류 → 코스트 조회 → 스냅샷 → 리포트까지 **전 구간 동작**.
* 실제 Data Dragon 아이콘으로 끝까지 검증: **유사도 95~97%, 이름·코스트 정확**, 빈 칸 자동 분리.
* `scripts\simulate_scan.py`로 게임 없이 언제든 재현 가능(회귀 테스트로 쓰세요).
* **미구현**: 성급(별), 숫자(골드/레벨/HP) → 위 §2.
