# 작업 이어하기 가이드 (집에서 이어서)

> 이 문서는 **다른 PC에서 바로 이어서 작업**하기 위한 런북입니다.
> 현재 상태: 커밋 `dacdf41` (main, origin과 동기화) + **미커밋 작업 있음**(아래 §0.5),
> 테스트 **274개** 전부 통과, CLI 13개 명령, 외부 의존성 0개.
> **인식은 아직 실게임에서 안 됩니다** — 좌표 캘리브레이션이 남았습니다(§1).

---

## 0. 집 PC에서 5분 안에 실행 상태 만들기

```powershell
git clone https://github.com/yashiro0504/tat-ev-calculation.git
cd tat-ev-calculation          # (저장소 이름 그대로) 또는 tft-ev-calculator
python -m tftcalc.cli selftest  # 환경/데이터 자기점검
```

**설치할 것이 없습니다.** Python 3.12+ 표준 라이브러리만 씁니다(ctypes 포함). `requirements.txt`를 만들지 마세요 — 무의존성이 이 프로젝트의 장점입니다.

전체 테스트(14개 파일, 274개):
```powershell
python -m unittest discover -s tests -t .      # 가장 간단(274 tests, OK)
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
기대 출력: `Ran 39/18/15/26/16/6/35/30/32/20/8/4/24 tests` + 각각 `OK` (= 274개).

> **함정 1**: 실행기는 PC마다 다르다 — `python` 이 Microsoft Store 스텁이면 `py -3`,
> `py` 런처가 없으면 `python`. 아래 예시는 **`python` 기준**이다.
> **함정 2**: 한글 경로/출력 때문에 깨져 보이면 `cmd /c "set PYTHONIOENCODING=utf-8 && python ..."` 로 실행하세요.

---

## 0.5 직전 세션에서 바뀐 것 (커밋 대상)

| 변경 | 파일 | 이유(실측 근거) |
|---|---|---|
| `MIN_SCORE` 0.5 → **0.85** | `tftcalc/cv/fingerprint.py`, `tests/test_cv.py` | 비아이콘 화면 내용이 최대 0.6494 까지 나와서, 0.5 바닥선에서는 **게임을 켜지 않은 바탕화면**의 상점/벤치 좌표가 Gnar/Kog'Maw 로 '확정'되어 스냅샷을 오염시켰다(재현됨). 서로 다른 아이콘 쌍 최대 0.7438 과 실제 아이콘 0.95~0.97 **사이**에 바닥선을 둔다. |
| `STAR_BAND` 0.76 → **0.84** (지문 경계 아래 + 안전 여유 2%p) | `tftcalc/cv/layout.py`, `tests/test_cv.py` | 별 픽셀이 지문 내부(하단 18% 인셋)에 들어오면 **같은 챔피언이 1성 1.0000 / 3성 0.6341** 로 갈렸다. `MIN_SCORE` 0.85 와 겹치면 2·3성 칸이 통째로 'unknown' 이 된다(`test_three_stars_detected` 가 회귀 고정). |
| `scan --window`, `report --scan-window` 신규 | `tftcalc/cli.py`, `tftcalc/cv/screen.py`(`find_client`/`capture_client`/`_title_score`) | 창모드에서 전체 화면 캡처로는 비율 좌표가 어긋난다. **클라이언트 영역**만 캡처하고, 창 제목은 뒤 공백·대소문자·부분 일치를 허용(실제 TFT 창 제목이 `'TFT  '` 라서 `FindWindowW` 정확 일치가 실패했다). |
| `check_capture --window` 도 클라이언트 영역 | `scripts/check_capture.py` | 캘리브레이션용 좌표가 타이틀바(31px)·테두리(8px)만큼 밀리면 **잘못된 보정값**을 저장하게 된다. |
| **`scan`/`report` 가 좌표 보정 파일을 읽지 않던 버그 수정** + `--layout`/`--scan-layout` 추가 | `tftcalc/cli.py`, `tests/test_scan.py` | 문서(§1)가 안내하는 `data/layout_1920x1080.json` 을 **실사용 경로가 무시**했다(`check_capture` 만 읽었다). 보정을 아무리 해도 `scan` 은 기본 좌표로 인식해 '원인 없는 인식 실패'만 보였다. 회귀 테스트로 고정. |

### 실게임에서 측정한 좌표 (2026-09-23, 창모드 클라이언트 2120x1191)
자동 검출(상점 카드 세로 테두리 / 벤치 금색 분리선) + 눈으로 검증(박스 오버레이 대조):

| 영역 | 클라이언트 픽셀 | 비율(0~1) | 검출 근거 |
|---|---|---|---|
| 상점 5칸 | x = **596 + 223i**, y **1008**, 223x176 | x 0.28113 + 0.10519i, y 0.84635, 0.10519 x 0.14778 | 카드 테두리 검출값이 5장 카드와 정확히 일치 |
| 벤치 9칸 | x = **550 + 130i**, y **807**, 130x122 | x 0.25943 + 0.06132i, y 0.67758, 0.06132 x 0.10244 | 금색 분리선에 후보 박스가 정확히 일치 |

* 이 값은 `data/layout_1920x1080.json`(개인 캘리브레이션, .gitignore)에 저장해 두었다.
  이제 `scan --layout data\layout_1920x1080.json` / `report --scan-layout ...` 로 실사용 경로에서도 적용된다.
* **기존 기본값은 이 UI와 많이 어긋난다**(상점 x 가 약 300px 왼쪽, 벤치 y 가 약 150px 아래).
  기본값을 갱신하려면 **다른 해상도(1920x1080 전체화면 등)에서 한 번 더 측정**해 비율이 해상도 무관한지 확인해야 한다(아직 미확인).

### ✅ 실게임 검증 성공 (2026-09-23, 창모드 2120x1191)

위 좌표 + **게임 화면 크롭 템플릿**으로 실게임에서 인식이 실제로 됐다.

| 실험 | 결과 |
|---|---|
| 같은 라운드 재캡처(1초, 22초) | 상점 카드 픽셀차 **0.0** → 11/11칸 자기 인식 **0.99~1.000 확정** |
| 라운드가 넘어가 상점 교체 | 이전에 크롭한 챔피언이 다시 나오면 **0.985~0.999 로 확정** (Varus 0.985, Yorick 0.986, 조약돌 0.999) |
| 템플릿에 없는 챔피언 / 빈 칸 | 최고 0.72~0.75 로 바닥선 미만 → **`확인 필요`(오인 0)** |
| 벤치 유닛이 바뀐 경우 | 자기 유사도 0.22~0.52 → **`확인 필요`(오인 0)** |

CLI 실측 출력(제품 경로):
```
[좌표] 보정 파일 적용: data\layout_1920x1080.json
인식 확정 1칸 / 확인 필요 13칸 (신뢰도 7%)
  [확정] shop_1    Yorick   1코 1성 (유사도 98.7%)
  [확인 필요] shop_3  코스트 표에 없음(Varus) — data/set18_unit_costs.json 에 추가하면 확정됩니다
  [코스트 미확인] Varus, 조약돌 (data/set18_unit_costs.json 에 추가하세요)
```

**되는 워크플로 (상점 카드는 이름표가 있어 라벨링이 확실하다)**
```powershell
python scripts\check_capture.py --window TFT --out shot.bmp --shop     # 상점 보이는 상태 확인
python scripts\crop_slots.py --in shot.bmp --area shop                 # data\crops\shop_N.bmp
# 카드 이름표를 보고 파일명을 챔피언 이름으로 바꾼다 (shop_3.bmp -> Yorick.bmp)
python scripts\build_templates.py --from-crops data\crops --out data\templates_ingame.json
python -m tftcalc.cli scan --templates data\templates_ingame.json --window TFT --area shop,bench
```
* 챔피언 **하나당 한 번만** 크롭하면, 그 뒤로는 그 챔피언이 상점에 뜰 때마다 인식된다(실측 0.985~0.999).
* 빈 칸 크롭은 **넣지 않는다**(가짜 템플릿이 된다). 분산이 낮은 칸(대략 300 미만)은 빈 칸이다.
* `data\templates_ingame.json` 은 개인 라이브러리라 `.gitignore` 에 있다(쌓이면 실전 인식률이 올라간다).

**남은 병목 (둘 다 데이터 문제, 인식 문제가 아니다)**
1. **코스트 표가 부족하다.** `data/set18_unit_costs.json` 은 patch 18.1 + 메타 컴프 6개 유닛만(36개)이라
   실게임 상점의 상당수가 코스트 미확인이다(실측: Varus·조약돌·바위 게·심술두꺼비 없음).
   → `python scripts\fetch_unit_costs.py --units <슬러그,...>` 로 채우거나, 전체 로스터 파이프라인
   (CommunityDragon, README §7)이 필요하다. 코스트가 없으면 그 유닛은 `확인 필요`로 빠질 뿐
   **0이나 추정값을 넣지 않는다**(풀 계산 오염 방지).
2. **벤치 유닛은 이름표가 없다.** 3D 모델이라 사람이 라벨링해야 한다. 같은 챔피언이 상점에 동시에
   보이면 그 이름을 옮겨 붙이는 방법이 가장 싸다(상점 크롭 = 같은 챔피언의 2D 아트).

### ⚠️ 다섯 번째 발견 — 오버레이가 게임 창을 덮으면 화면 캡처가 오버레이를 찍는다
MetaTFT 컴패니언 오버레이가 게임 창 위에 떠 있을 때, 화면 BitBlt 캡처는 **오버레이 내용**을
가져와 인식이 통째로 실패했다(창은 정상, 좌표도 정상). 게다가 `--window TFT` 의 **부분 일치**가
`MetaTFT Companion App`/MetaTFT 웹페이지를 잡아 '스캔 성공'(전부 '확인 필요')처럼 보였다.

수정:
* `capture_client` 가 먼저 `PrintWindow(PW_RENDERFULLCONTENT)` 로 **창이 스스로 그린 내용**을
  받고(겹친 창 무시), 실패/빈 화면이면 화면 BitBlt 로 폴백한다. 실측: 오버레이가 덮인 상태에서
  게임 화면을 정상 캡처.
* 창 제목 매칭은 **정확 일치 + 양끝 공백/대소문자 무시(점수 ≥ 2)만** 쓰고 부분 일치는 기본 금지.
  못 찾으면 **비슷한 제목을 안내**한다(`screen.near_miss_titles`). 최소화/숨김 창은 건너뛴다.

### ✅ 코스트 표 = 전체 로스터 65개 (2026-09-23)
`tft.ninja/units` 에서 슬러그 65개를 받아 `fetch_unit_costs.py` 로 채웠다(36 -> 65).
한국어 카드 이름도 특성·코스트 대조로 확정했다:

| 카드(한국어) | 코스트 | 특성 | 영어 이름 |
|---|---|---|---|
| 심술두꺼비 | 2 | 협곡아수/적응가 | **Gromp** (Riftbeast, Adaptor) |
| 바위 게 | 2 | 협곡아수/전쟁기계 | **Scuttlecrab** (Riftbeast, Juggernaut) |
| 불타는 묘목 | 1 | 협곡아수/사냥꾼 | **Cinderling** (Riftbeast, Hunter) |
| 조약돌 | 1 | 협곡아수/기원자 | **Pebbles** (Riftbeast, Invoker) |

갱신 절차(요청이 65건이라 **10~11개씩 나눠 병렬 실행 후 병합**):
```powershell
# 슬러그 목록은 tft.ninja/units 에서 /units/<slug> 링크를 긁는다(65개)
python scripts\fetch_unit_costs.py --sleep 0.3 --out $env:TEMP\costs_p1.json --units ahri,akali,...
# ... p6 까지 나눠 실행한 뒤, 각 조각의 units 를 모아 save() 로 병합(형식 유지)
```

### ✅ 벤치는 상점 템플릿으로 못 읽는다 (측정, 2026-09-23)
벤치 9칸을 상점 크롭 템플릿 22개로 분류한 결과: 최고 유사도 **0.39~0.64**, 1·2등 마진 0.002~0.05
→ 전부 `확인 필요`(**오인 0**). 벤치 유닛은 3D 모델, 상점은 2D 카드 아트라 같은 챔피언이어도
지문이 겹치지 않는다. **벤치는 벤치 전용 크롭 + 사람 라벨링이 필요하다.**

라벨링을 싸게 하는 방법:
1. `python %TEMP%\cycle.py` 같은 스크립트로 `data\crops\bench_N.bmp` 를 저장하고,
2. 벤치 9칸을 3x3 으로 이어 붙인 **작은 합성 이미지**를 만들어 눈으로 보고(또는 사용자에게 확인),
3. 파일명을 챔피언 이름으로 바꾼 뒤 `build_templates.py --from-crops` 로 합친다.

### 💡 팁: 이름표만 모은 작은 이미지로 챔피언 이름을 읽는다
상점 카드 5장을 통째로 읽으면 이미지가 커서(수백 KB) 한도에 걸릴 수 있다. 카드 하단 **이름표
30px만** 잘라 5장을 세로로 이어 붙이면 **약 13KB** 라 항상 읽힌다(코드: `cycle.py` 의 `namebars.png`).
챔피언 이름·코스트를 확인하는 데는 이걸로 충분하다.

### 💡 더 좋은 방법: Windows 내장 OCR 로 이름표를 텍스트로 읽는다
이미지 읽기 한도와 무관하게 라벨을 얻을 수 있다(실측 2026-09-23: 한국어 엔진 `ko` 동작).

```powershell
# 1) 상점 크롭 저장 + 이름표 3배 확대 합성 (작은 글씨는 오독하므로 반드시 확대)
python %TEMP%\cycle.py        # data\crops\shop_N.bmp + TEMP\shots\namebars.png
python %TEMP%\mkcrops.py      # 저장된 크롭에서 namebars3x.png 생성(669x510, 18KB)
# 2) OCR (PowerShell + WinRT Windows.Media.Ocr) -> 슬롯 번호와 이름을 텍스트로 출력
powershell -NoProfile -ExecutionPolicy Bypass -File %TEMP%\ocr_names.ps1
```
실측 출력(코스트 숫자도 함께 읽혀 **교차 검증**이 된다):
```
  shop_1  y~9     라칸          (라칸 = Rakan 1코)
  shop_2  y~111   엘리스        +2      (Elise 2코)
  shop_4  y~315   세주아니      +2      (Sejuani 2코)
  shop_5  y~417   릴리아        +4      (Lillia 4코)
```
* 한국어 이름 -> 영어 이름 매핑은 사람이 한다(코스트 표의 이름과 **정확히** 같아야 코스트가 붙는다).
* OCR 은 가끔 오독한다(`일리스`=엘리스, `라간`=라칸). **코스트 숫자가 맞는지로 교차 확인**하고,
  애매하면 그 칸은 넣지 않는다(틀린 라벨은 조용한 오분류를 만든다).
* 스크립트는 저장소 밖(`%TEMP%`)에 있다 — 필요하면 `scripts/` 로 승격해도 된다(Windows 전용).

### 📦 크롭 라이브러리 현황 (2026-09-23, 32개)
Ahri·Akali·Alistar·Amumu·Azir·Camille·Cassiopeia·Cinderling·Diana·Elise·Ezreal·Gromp·Karma·Kayle·
Kobuko·Kog'Maw·LeBlanc·Leona·Lillia·Pebbles·Rakan·Rammus·Scuttlecrab·Sejuani·Tristana·Varus·Veigar·
Warwick·Xayah·Yorick·Yunara + 떠돌이(6코, 코스트 표에 없음)
실게임 인식 실적: 신규 크롭 직후부터 **93~100%** 로 확정, 미등록·빈 칸은 확인 필요(오인 0).

### ⚠️ 네 번째 발견 — 진단 문구가 사용자를 엉뚱한 곳으로 보냈다

### ⚠️ 네 번째 발견 — 진단 문구가 사용자를 엉뚱한 곳으로 보냈다
코스트 표에 없는 유닛을 `reason` 없이 `review` 에 넣어서 요약이
`모호(Varus vs 심술두꺼비, 마진 0.259)` 로 출력됐다. 실제 원인은 '코스트 표에 없음'인데
사용자는 `REVIEW_MARGIN`/문턱을 의심하게 된다. → 이유를 명시하고 회귀 테스트를 추가했다
(`tests/test_scan.py::TestScan::test_missing_cost_is_reported_not_guessed`).

### ⚠️ 세 번째 발견 — Data Dragon 정사각 아이콘은 게임 카드 아트와 안 맞는다
좌표를 정확히 맞춘 뒤 실게임에서 측정한 결과:

| 대상 | 유사도 |
|---|---|
| 상점 카드(실제 챔피언) vs DDragon 템플릿 | **0.53~0.63** |
| **빈 상점 칸** vs DDragon 템플릿 | **0.72** (내용이 없는데 더 높다!) |
| 벤치 유닛(3D 모델) vs DDragon 템플릿 | **0.48~0.67** |

* 즉 **바닥선 0.85 로는 절대 인식되지 않는다.** 좌표보다 이 문제가 더 크다.
* 같은 화면에서 크롭을 서로 대조하면:
  * 한 라운드 안에서 상점 카드는 **완전히 정적**(0.4초 간격 자기 유사도 **1.000**, 픽셀 차이 ~0)
  * 벤치는 대체로 정적(0.97~0.999), 유닛이 움직이는 칸은 0.76~0.88
* 따라서 다음 단계는 **게임 화면 크롭 템플릿**(`scripts/crop_slots.py` → `build_templates.py --from-crops`)이다.
  Data Dragon 은 "게임에 없는 유닛 보충"이 아니라 **보조**로만 쓴다.
* 함정: 아이템/증강 **"하나 선택" 화면 등에서는 상점·벤치가 아예 없다**(그때 크롭하면 경기장 바닥이 저장된다).
  크롭 전에 `check_capture.py --in shot.bmp --shop` 으로 상점 칸 분산이 2000 이상인지 확인할 것.


**실게임 1회 측정(창모드, 클라이언트 2120x1191)** — 도구가 값을 만들어내지 않는지 확인:
```powershell
python -m tftcalc.cli scan --templates data\templates_set18.json --window TFT --area shop,bench
```
```
[캡처] 창 'TFT' 클라이언트 영역 2120x1191
인식 확정 0칸 / 확인 필요 14칸 (신뢰도 0%)     <- 상점·벤치 14칸 점수 0.49~0.73 (바닥선 미만)
  [정보] 골드 ? / 레벨 ? / HP ? / 라운드 ?   ('?' = 못 읽음 → 손 입력)
```
즉 좌표가 아직 안 맞아 **정직하게 실패**한다(0칸 확정, 14칸 확인 필요). 다음 할 일은 §1 이다.
주의: "하나 선택"(아이템/증강) 화면에서는 상점·벤치가 없으므로 **일반 인게임 상태**에서 측정해야 한다.

---

## 1. 남은 작업 A — 템플릿 라이브러리 늘리기 + OCR 캘리브레이션

좌표·인식·코스트 표는 끝났다(§0.5: 크롭 템플릿 0.985~1.000 확정, 오인 0, 코스트 65개 전체 로스터).
남은 것은 **라이브러리를 늘리는 일**과 **OCR 캘리브레이션**이다.

1. **크롭 템플릿 라이브러리** (현재 16개: Ahri·Amumu·Cassiopeia·Cinderling·Ezreal·Gromp·Kobuko·
   Kog'Maw·Pebbles·Scuttlecrab·Tristana·Varus·Veigar·Warwick·Xayah·Yorick)
   ```powershell
   python scripts\check_capture.py --window TFT --out shot.bmp --shop   # 상점 보이는지 확인(분산 2000+)
   python scripts\crop_slots.py --in shot.bmp --area shop               # data\crops\shop_N.bmp
   # 카드 이름표를 보고 파일명을 코스트 표의 이름으로 바꾼다(shop_3.bmp -> Yorick.bmp)
   python scripts\build_templates.py --from-crops data\crops --out data\templates_ingame.json
   python -m tftcalc.cli scan --templates data\templates_ingame.json --window TFT --area shop,bench
   ```
   * 빈 칸 크롭은 **넣지 않는다**(분산 300 미만이면 빈 칸). 아이템/증강 선택 화면에서는 상점이 아예 없다.
   * 파일명은 **코스트 표의 이름과 정확히 같아야** 코스트까지 붙는다(예: `Kog'Maw.bmp`, `Pebbles.bmp`).
   * 한국어 카드 이름은 §0.5 표처럼 특성+코스트로 영어 이름을 확정해서 붙인다.
   * 실측: 한 라운드 안에서 상점 카드는 정적(자기 유사도 1.000), 챔피언당 한 번 크롭이면 이후 계속 인식된다.
2. **성급(별)·숫자(골드/레벨/HP/라운드) 캘리브레이션** (§2) — 실게임 크롭으로 임계값/지문 파일을 만든다.
3. **벤치 유닛 라벨링** — 이름표가 없어(3D 모델) 사람이 붙여야 한다. 같은 챔피언이 상점에 동시에
   보이면 그 이름을 옮기는 게 가장 싸다.

**게이트(통과 기준)**
1. 상점 5칸 중 템플릿이 있는 챔피언은 **유사도 0.95 이상으로 확정**(실측 0.985~1.000).
2. 템플릿에 없는 챔피언·빈 칸은 **확정되지 않는다**(실측 0.72~0.75 → 확인 필요).
3. 기존 274개 테스트 전부 통과.

```powershell
# 1) TFT를 창모드(또는 전체화면 창모드)로 띄우고 상점이 보이는 상태에서
python scripts\check_capture.py --out shot.bmp                 # 캡처 + 저장(인식 시험 포함)
python scripts\check_capture.py --window TFT --out shot.bmp    # 창모드: 클라이언트 영역만
python scripts\check_capture.py --in shot.bmp --shop           # 저장본으로 상점 5칸 인식
python scripts\check_capture.py --in shot.bmp --no-templates   # 캡처 상태만 확인
```
> 창모드면 **반드시 `--window TFT`** 를 쓰세요. 전체 화면 캡처는 게임이 화면 일부만 차지해
> 비율 좌표가 어긋납니다(창 제목은 `TFT` 로 충분 — 뒤 공백/대소문자/부분 일치 허용).

`--in shot.bmp --shop` 이 출력하는 표를 그대로 쓰면 됩니다(실측 예 — 좌표는 1920x1080 기준):
```
        영역              인식      점수      마진  픽셀(x,y,w,h)  판정
    shop_1            Ahri    0.97    0.24   270, 972, 253, 95  확정
    shop_2         Morgana    0.97    0.28   551, 972, 253, 95  확정
    shop_5         unknown    0.00    0.00  1394, 972, 253, 95  확인 필요
```
> 위 표는 **합성 화면(Data Dragon 아이콘을 좌표에 붙임)** 에서의 값이다. 실게임 카드 아트로는
> 0.53~0.72 밖에 안 나온다(§0.5 세 번째 발견). 실게임에서 "확정"이 하나도 없으면 그건 정상이고,
> 다음 단계는 크롭 템플릿이다.

`픽셀(x,y,w,h)` 열이 **보정용 좌표**입니다. `shot.bmp`를 열어 사각형이 아이콘과 어긋나면,
그 차이를 `[0,1]` 비율로 환산해 아래 JSON에 넣으면 됩니다(칸 순서는 왼쪽→오른쪽).

**실게임 측정값이 이미 있다**(§0.5): 창모드 클라이언트 2120x1191 기준
상점 `x=596+223i, y=1008, 223x176` / 벤치 `x=550+130i, y=807, 130x122`.
그 비율이 `data\layout_1920x1080.json` 에 들어 있고, 이제 `scan`/`report` 도 읽는다.

```json
{
  "bench": [[0.2594, 0.6776, 0.0613, 0.1024], ["...", 9칸]],
  "shop":  [[0.2811, 0.8463, 0.1052, 0.1478], ["...", 5칸]]
}
```
* **비율 좌표라서 해상도 무관**합니다. 집 모니터가 2560×1440이어도 `[0,1]` 값이면 그대로 동작합니다(정수 픽셀이면 깨집니다).
* 순서는 `layout.BENCH_SLOTS` / `SHOP_SLOTS` / `BOARD_SLOTS` 순서(= 화면 왼쪽→오른쪽)와 같아야 합니다.
* `data/layout_1920x1080.json`은 **개인 캘리브레이션**이라 `.gitignore`에 있습니다. 저장소에 올리려면 `git add -f data/layout_1920x1080.json`.
* **주의(수정됨)**: 예전에는 `scan`/`report` 가 이 파일을 읽지 않아 보정이 무효였다. 지금은 `--layout`(scan) /
  `--scan-layout`(report) 로 지정하거나, 생략하면 기본 경로(`data/layout_1920x1080.json`)를 자동으로 읽는다.

**확인(게임 아이콘 그대로 인식되는지)**:
```powershell
python -m tftcalc.cli scan --templates data\templates_set18.json --in shot.bmp --area bench,shop
python -m tftcalc.cli scan --templates data\templates_set18.json --window TFT --area bench,shop --out data\my_board.json
python -m tftcalc.cli report --round 4-1 --gold 60 --level 7 --hp 40 --streak -3 `
    --scan --templates data\templates_set18.json --scan-window TFT --scan-out data\my_board.json `
    --snapshot data\lobby.json --comps data\comps_set18.json `
    --odds-file data\set18_shop_odds_assumed.json --components rod:2,gloves
```
* `--scan` 에는 **`--templates` 가 필수**입니다(없으면 오류 메시지로 안내합니다).
* `--snapshot` 은 상대(로비) 정보용입니다. **파일이 없어도 오류 없이** 내 정보만으로 리포트가 나옵니다.
* **스캔은 상점 칸을 `shop` 으로 분리합니다**(보유로 세지 않음). 상점에 보이는 기물은 아직 사지 않은
  것이라, 보유로 세면 판정이 낙관 편향됩니다. 지금 산다고 가정하려면 `--shop-as-owned` 를 붙이세요
  (붙이면 보유로 세고 `[가정]` 이 출력됩니다).
* `--scan-in` 을 빼면 실제 화면을 캡처합니다(게임이 떠 있어야 함). **창모드면 `--scan-window TFT`**
  를 쓰세요 — 그 창의 클라이언트 영역만 잘라 비율 좌표가 그대로 통합니다(창 제목은 `TFT` 면 충분).


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
| `tftcalc/cv/layout.py` | `STAR_BAND`(칸 안 상대 비율) + `star_band(slot_box)` — 해상도 무관. **지문이 잘라내는 하단 경계 아래에서 시작**해야 한다(아래 ⚠️) |
| `tftcalc/cv/scan.py` | `ScanReport.info`(`gold`/`level`/`my_hp`) + `stage_round`, 성급 우선순위(**지정 > 인식 > 기본값**), 미인식 고지 |
| `tftcalc/cli.py` | `--star-ocr`(켜기), `--digits`(숫자 지문 JSON) — `scan`/`report` 공통 |
| `tests/test_ocr.py` (신규) | 합성 이미지 검증: 별 0~3 · 경계 거부 · 자릿수 분리 · 숫자(7/42/105) · **라운드('4-2')와 거부 케이스** · 미인식 `None` |
| `tests/fixtures.py` (신규) | 합성 이미지 픽스처(문자 아트·사각형). `test_ocr`/`test_scan` 이 공유 |

### ⚠️ 발견한 것 — 별 인식은 **기본 꺼짐**으로 바꿨다 (계획은 "기본 켜기"였음)
**실측**: 실제 Data Dragon 아이콘을 칸에 채운 합성 화면에서 별 영역의 밝은 비율이 **별 1개 면적의 약 12배**로 나왔다. 아이콘 자체의 밝은 픽셀이 별 영역에 섞이기 때문이다. 그 값을 그대로 쓰면 **3성(풀 소모 9장)** 으로 잡혀 계산이 조용히 **3배** 틀어진다.

그래서:
* 기본은 `detect_stars=False` → 기존대로 **1성 + 고지**(안전 기본값).
* `--star-ocr` 로 켜되, **애매하거나 과대 비율이면 그 칸을 스냅샷에서 빼고 `[확인 필요]`** 로 보고한다(추정 금지).
* 켜서 제대로 쓰려면 `ocr.STAR_BRIGHTNESS` / `ocr.STAR_AREA_RATIO` / `layout.STAR_BAND` 를 실게임 화면에 맞춰야 한다.

### ⚠️ 두 번째 발견 — 별 띠가 지문 영역과 겹치면 2·3성이 통째로 날아간다
`STAR_BAND` 가 0.76 부터라 지문(`fingerprint`, 위아래 18% 인셋 = 경계 0.82)과 **6%p 겹쳤다**.
그래서 별 픽셀이 지문에 섞여 **같은 챔피언인데도** 1성 1.0000 / 3성 0.6341 로 갈렸고,
`MIN_SCORE` 를 0.85 로 올린 뒤에는 2·3성 칸이 통째로 'unknown' 이 됐다
(`tests/test_scan.py::TestStarOcr.test_three_stars_detected` 가 그 회귀를 고정한다).

* 수정: `STAR_BAND` 시작선을 `1 - fingerprint.DEFAULT_INSET + STAR_BAND_INSET_MARGIN(0.02)` 로
  내려(현재 **0.84**) 별 픽셀이 지문에 **절대** 들어가지 않게 했다. 정수 픽셀 여유 1px 까지 고려한 값이다.
* 별이 실제로는 이 띠보다 위에 찍히면 개수가 0으로 읽히고, 그 칸은 조용히 3배 틀리는 대신
  "별을 못 봄 + 1성" + 고지로 떨어진다(안전한 실패). **실게임 별 위치는 여전히 미검증**이다.
* 띠 기하를 바꾸면 `test_ambiguous_star_is_excluded_not_guessed` 의 `star_side` 값도 다시 골라야 한다(실측 스윕 주석 있음).

숫자도 마찬가지로 **`--digits` 가 없으면 아무것도 읽지 않고 전부 `None` + '손 입력 필요'** 다(0 으로 추정하지 않음). 라운드 표기('4-2')도 같은 템플릿으로 읽으며, **조각이 3개(숫자·구분자·숫자)이고 범위(1~9 / 1~7) 안일 때만** 확정한다(라운드가 틀리면 골드 계획 전체가 어긋나므로).

### 남은 것
* 실게임 별 영역 캘리브레이션(`check_capture.py --out shot.bmp` 로 별 위치/밝기 확인).
* `data/digits_1920x1080.json` — 실게임 숫자를 크롭해 0~9 지문 생성(개인 캘리브레이션, `.gitignore`).

**통과 기준(게이트)**
1. 내 보드 성급 인식이 **수동 대조와 100% 일치**(20판 표본). 틀린 칸은 조용히 넘기지 말고 "확인 필요"로.
2. 골드/레벨/HP 숫자 오인식 **0건**(한 자리라도 틀리면 골드 계획이 통째로 틀어짐). 실패 시 그냥 `None`.
3. 기존 274개 테스트 전부 통과.

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

1. **커밋 전**: 해당 테스트 파일 실행 → 전체 274개 `OK` 확인. 깨진 채로 커밋하지 않습니다.
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
| 최신 커밋 | `dacdf41` (main, origin과 동기화) + §0.5 의 미커밋 작업 |
| 테스트 | **274개 전부 통과** — pool 39 / comp 18 / items 15 / economy 26 / survival 16 / report 6 / cv 36 / scan 30 / cli 32 / render 20 / rules 8 / trials_defaults 4 / ocr 24 |
| CLI 명령 | **13개** — `odds selftest unit lobby outlook items plan survive report scan comp sensitivity robustness` |
| 모듈 | `pool_math` `comp` `items` `economy` `survival` `lobby` `odds` `decision` `set_data` `trials` `render` `rules` `cli` + `cv/{screen,fingerprint,layout,scan,ocr}` |
| 스크립트 | `build_templates` `check_capture` `crop_slots` `fetch_unit_costs` `fetch_item_recipes` `simulate_scan` |
| 데이터 | 메타 덱 6 · 유닛 코스트 36 · 아이템 조합식 31 · 아이콘 지문 28 |
| 의존성 | **0개** (Python 3.12+ 표준 라이브러리) |

**CV 현재 수준**
* 캡처(1920×1080 실측) → 지문 분류 → 코스트 조회 → 스냅샷 → 리포트까지 **전 구간 동작**.
* 합성 화면(Data Dragon 아이콘을 좌표에 붙임)에서는 **유사도 95~97%, 이름·코스트 정확**, 빈 칸 자동 분리.
* `scripts\simulate_scan.py`로 게임 없이 언제든 재현 가능(회귀 테스트로 쓰세요).
* 창모드 캡처(`--window TFT`) 동작 확인: 클라이언트 2120×1191 캡처 성공.
* **실게임에서는 아직 인식 0칸** — 상점·벤치 14칸 점수 0.49~0.73(바닥선 0.85 미만) → 좌표 캘리브레이션(§1)이 다음 할 일.
  부수적으로 **게임 카드 아트 ≠ Data Dragon 정사각 아이콘** 문제도 확인 필요(70%대 유사도의 원인 후보).
* **미구현**: 실게임 좌표 캘리브레이션(§1), 성급(별)·숫자 실게임 캘리브레이션(§2).
