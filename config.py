"""IOG ㈜K-Bottle 게임 상수 (대회소개 PDF 기준). 금액 단위: 원."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIRS = [ROOT.parent / "9월17일까지데이터", ROOT.parent / "10월2일까지데이터", ROOT / "data"]
# 테스트 시 환경변수로 교체 가능 (가짜 처리시간표가 실제 캐시를 오염시키지 않도록)
PROC_DIR = Path(os.environ.get("IOG_PROC_DIR", ROOT / "ProcessingTimeTable_P1_P2"))
# 제품별 처리시간표 접두어 (대시보드 SPT makespan과 대조해 확인: P2는 t2_ 표)
TABLE_PREFIX = {"P1": "t", "P2": "t2"}
OUT_DIR = Path(os.environ.get("IOG_OUT_DIR", ROOT / "output"))

# ---- 제품 ----
PRODUCTS = {
    "P1": dict(name="아메리카노", price=250, hold=30, stockout=250, setup=5_000_000),
    "P2": dict(name="카푸치노",   price=350, hold=30, stockout=250, setup=4_000_000),  # Ledger 실측 (PDF는 2M)
}
LOT = 1000          # 1 Job = 1,000개
MAX_JOBS = 500

# ---- 인건비 (Makespan 100시간 = 인건비 1시간, 소수점 버림) ----
REG_HOURS = 70       # 정규시간 기준 Makespan 7,000 → 70시간
REG_RATE = 100_000   # 원/시간
OT_RATE = 200_000

# ---- BOM ----
BOM = {"P1": {"M1": 1, "M2": 2}, "P2": {"M2": 2, "M3": 1}}

# ---- 자재 ----
MATERIALS = {
    "M1": dict(order_cost=1_000_000, hold=1, modes={"NORMAL": dict(price=30, lead=3)}),
    "M2": dict(order_cost=3_000_000, hold=1, modes={"NORMAL": dict(price=25, lead=8),
                                                     "URGENT": dict(price=50, lead=2)}),
    "M3": dict(order_cost=2_000_000, hold=2, modes={"NORMAL": dict(price=50, lead=5)}),
}

# ---- 생산 기준 분위수 (simulate.compare 백테스트로 튜닝: 8/2~10/3, 9주) ----
# 주 1회 계획은 잔여재고가 며칠씩 남으므로 낮게, 매일 재계획은 1일 예측이라 높게.
SERVICE_Q = {"weekly": 0.55, "daily": 0.75}

# ---- 대시보드(26_DKU_RM, 10/2)로 확인한 값 ----
SALE_LAG_DAYS = 0          # 당일 생산분 당일 판매 (Sales: 10/2 생산 P2 → 10/2 80,173개 판매)
PRODUCTION_WEEKDAYS = {0, 1, 2, 3, 4, 5, 6}   # 주말 생산 가능 (9/27 일요일 P2 생산 기록)
# 주말(sat/sun) 처리시간표도 ProcessingTimeTable_P1_P2에 있음
