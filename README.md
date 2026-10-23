# IOG ㈜K-Bottle 운영 도구

대회 사이트(팀 대시보드)를 읽어서 **매일 넣을 자재 발주**와 **다음 주 수요예측·생산계획(Job 순서 포함)**을 계산합니다.
사이트 입력(Apply)은 사람이 직접 합니다.

---

## 1. 설치 (처음 한 번)

1. 파이썬 3.10 이상 설치 (python.org)
2. 처리시간표를 받아 **`iog` 안에** 넣기 (t_*.csv = P1, t2_*.csv = P2, 월~일 14개)
   - 대회 제공 자료라 저장소에는 포함하지 않았습니다. 게임 사이트 Production 탭 → Create production plans → "Processing time table (download)"에서 받습니다.
   ```
   iog/
   ├── ProcessingTimeTable_P1_P2/   ← 여기 바로 csv 14개
   ├── weekly_plan.py
   └── ...
   ```
   - 폴더 이름은 정확히 `ProcessingTimeTable_P1_P2` (압축 풀 때 폴더가 한 겹 더 생기지 않게 주의)
3. 패키지 설치
   ```
   cd iog
   py -m pip install -r requirements.txt
   ```
   (`py`가 안 되면 `python`으로 바꿔서 실행)

---

## 2. 매일 루틴 (16:00 ~ 19:30)

수요 데이터는 매일 16시에 갱신되고, 입력 마감은 19:30입니다.

```
cd iog
py fetch_dashboard.py     # ① 사이트 읽기 → state.yaml, data/ 갱신
py weekly_plan.py         # ② 입력값 계산 → 화면 + output/plan_*.md
```

**순서를 꼭 지킬 것** — `weekly_plan.py`는 `fetch_dashboard.py`가 갱신한 `state.yaml`을 읽습니다.

### 결과 보는 법
| 출력 항목 | 할 일 |
|---|---|
| **③ 자재 발주 → "오늘 입력"** | Material 폼에 입력 (없으면 "오늘 입력할 발주 없음") |
| ③ "이후 예정" | 미리보기. 그날 다시 실행해서 확정 |
| ① 수요예측, ② 생산계획 | 다음 주 계획. **금·토에 입력** (아래 3번) |
| ④ 할인율 | 보통 0 → 입력 안 해도 됨 |
| makespan 검증 ... OK | 생산이 계산대로 됐다는 뜻. **"⚠ 불일치"가 나오면 확인 필요** |

### ⚠ 발주를 넣은 날은 반드시 state.yaml에 추가
발주 내역(Material plans)은 로그인해야 보여서 프로그램이 못 읽습니다.
발주 후 `state.yaml`의 `scheduled_receipts:` 아래에 한 줄 추가하세요.
```yaml
scheduled_receipts:
  - {material: M1, date: 2026-10-15, qty: 460000}
```
- `date` = **입고 예정일** (발주 폼의 "Leadtime (Arrival date)" 괄호 안 날짜)
- `qty` = 쉼표 없이 숫자만
- 줄 앞은 **스페이스 2칸** (Tab 금지)
- 입고되면 `fetch_dashboard.py`가 자동으로 지움

추가하지 않으면 다음 계산 때 **같은 발주를 또 하라고** 나옵니다.

---

## 3. 주간 루틴 (금·토, 마감 토 19:30)

생산계획·수요예측은 **다음 주(일~토) 것만** 입력할 수 있고, 그 주가 시작되면 수정할 수 없습니다.

1. `py fetch_dashboard.py` → `py weekly_plan.py` (생산 순서 계산 때문에 **약 5분**)
2. **Demand 폼:** ① 수요예측 표의 값 입력
3. **Production 폼:** ② 생산계획 표대로 입력
   - "Job sequence" 선택 → `output/sequences_<다음주 일요일>.txt`에서 `[제품 날짜 …]` **아래 숫자 줄 전체**를 복사해 붙여넣기
   - "0 (Job qty)"인 날은 Job qty에 0
4. 입력 후 `py fetch_dashboard.py` 한 번 더 → 실제 입력본이 `output/entered_week_<일요일>.txt`로 저장됨

---

## 4. 새 라운드 시작할 때

| 파일 | 바꿀 곳 | 예 (R2602C) |
|---|---|---|
| `fetch_dashboard.py` | `TEAM = "DKU/26_DKU_RM/R2602B"` | `R2602C` |
| `state.yaml` | `round_end:` | `2026-12-04` |
| `state.yaml` | `scheduled_receipts:` | 이전 라운드 것 지우기 |

- 계획 입력은 **라운드 시작 1주일 전부터** 가능 → 첫 주 계획과 자재를 미리 넣기
- 각 탭의 **Auto는 전부 OFF** (켜 두면 SPT·재주문점 방식으로 덮어씀)
- 새 라운드의 **초기재고·처리시간표가 바뀌었는지** 확인

---

## 5. 게임 규칙 요약 (코드에 반영된 값)

| 항목 | 값 |
|---|---|
| 수요 | P1 = 삼성전자 종가(휴장일 0), P2 = BTC 종가(매일) |
| 판매 | 생산한 날 바로 판매 |
| 생산 | 1 Job = 1,000개, 최대 500 Job. P1 주말 생산 불가, P2 주말 가능 |
| 생산비 | 셋업(P1 500만, P2 400만) + 인건비: makespan÷100(버림)시간, 70시간까지 10만/시간, 초과분 20만/시간 |
| 처리시간표 | P1 = `t_`, P2 = `t2_` (요일별로 다름. P2는 금요일이 가장 쌈) |
| 자재 | M1 3일 / M2 일반 8일·긴급 2일 / M3 5일. **입고일에 구매비 전액 비용 처리** |
| 재고비·품절비 | 완제품 30원/개·일, 품절 250원/개 |
| 라운드 밖 | 운영 안 됨 (마감 후 생산·도착 자재 없음) |

---

## 6. 자주 나는 오류

| 메시지 | 원인 | 해결 |
|---|---|---|
| `No such file ... state.yaml` | `iog` 폴더가 아닌 곳에서 실행 | `cd iog` 후 다시 |
| `'py'은(는) ... 인식되지 않습니다` | 파이썬 실행 명령 | `python`으로 바꿔서 |
| `ModuleNotFoundError` | 패키지 미설치 | `py -m pip install -r requirements.txt` |
| `FileNotFoundError ... t2_500_20_...csv` | 처리시간표 폴더 위치·이름 | `ProcessingTimeTable_P1_P2`를 `iog` 안에 두기 (폴더 안에 바로 csv가 있어야 함) |
| `yaml ... ScannerError` | `state.yaml` 들여쓰기 오류 | 줄 앞 스페이스 2칸, 하이픈 뒤 한 칸 |
| 사이트 접속 오류 (URLError) | 인터넷·사이트 점검 | 잠시 후 다시 |

VS Code 실행 버튼(▷)은 실행 폴더가 달라 오류가 날 수 있으니 **터미널에서 실행**하세요.

---

## 7. 파일 구성

| 파일 | 역할 |
|---|---|
| `fetch_dashboard.py` | 사이트 읽기 (재고, 생산 기록, 장부, 수요 데이터) → `state.yaml`, `data/`, `output/entered_week_*.txt` |
| `weekly_plan.py` | **메인.** 오늘 발주 + 다음 주 수요예측·생산계획 계산 |
| `state.yaml` | 현재 상태 (재고, 입고 예정, 이번 주 고정 생산, 라운드 마감일) |
| `config.py` | 게임 상수, 생산 기준 분위수(`SERVICE_Q`), 처리시간표 위치 |
| `forecast.py` | 수요예측 (모델 백테스트 후 자동 선택: P1 Drift, P2 Naive 등) |
| `production_plan.py` | 생산량·생산일 결정 (Newsvendor 55% + 동적계획법) |
| `scheduler.py` | 생산 순서 최적화 (NEH + Iterated Greedy, 30초) |
| `material_plan.py` | 자재 발주 (MRP + 동적계획법, M2 일반·긴급 선택) |
| `cost_model.py` | 생산비 계산 |
| `data_loader.py`, `krx_calendar.py` | 수요 데이터 로딩, 한국 증시 휴장일 |
| `discount.py` | 라운드 마지막 날 할인 계산 |
| `simulate.py`, `analysis.ipynb` | 백테스트, 보고서용 분석 |
| `output/entered_week_*.txt` | **실제 사이트에 입력된** 주간 생산계획 기록 (보고서용) |
| `output/plan_*.md`, `sequences_*.txt` | 계산 결과 (실행할 때마다 덮어씀) |
| `output/schedule_cache.json`, `makespan_grid.json` | 생산 순서 계산 캐시. **지우지 말 것** (지우면 첫 실행이 매우 오래 걸림) |
| `ProcessingTimeTable_P1_P2/` | 처리시간표 (P1 `t_`, P2 `t2_`, 월~일) |
| `data/` | 수요 데이터 (`fetch_dashboard.py`가 매일 갱신) |
