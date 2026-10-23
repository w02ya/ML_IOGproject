"""생산계획: 언제, 몇 Job을 생산할지 (Wagner-Whitin 변형 DP).

- 판매일 k의 수요는 생산일 d (d + SALE_LAG_DAYS <= k) 에서 만든 재고로 충당.
- 생산비 = 셋업비 + 인건비(makespan 기반, 잔업 반영), 재고비 = 30원 × 보유일수.
- 목표 수요 = newsvendor 분위수 예측 (forecast.py).
"""
import json
import math

import numpy as np
import pandas as pd

import scheduler
from config import (BOM, LOT, MATERIALS, MAX_JOBS, OUT_DIR, PRODUCTION_WEEKDAYS,
                    PRODUCTS, SALE_LAG_DAYS, OT_RATE)
from cost_model import production_cost

GRID_FILE = OUT_DIR / "makespan_grid.json"
GRID_STEP = 10


# ---------- makespan 추정 (요일별 NEH 그리드 + 선형보간) ----------
def _grid(weekday: int, product: str) -> np.ndarray:
    cache = json.loads(GRID_FILE.read_text()) if GRID_FILE.exists() else {}
    key = f"{product}:{weekday}"
    if key not in cache:
        ns = list(range(GRID_STEP, MAX_JOBS + 1, GRID_STEP))
        cache[key] = [0] + [scheduler.neh_makespan(weekday, n, product) for n in ns]
        GRID_FILE.parent.mkdir(exist_ok=True)
        GRID_FILE.write_text(json.dumps(cache))
    return np.array(cache[key], float)


def est_makespan(weekday: int, jobs: int, product: str = "P1") -> int:
    if jobs <= 0:
        return 0
    g = _grid(weekday, product)
    return int(np.interp(jobs, np.arange(0, MAX_JOBS + 1, GRID_STEP), g))


# ---------- newsvendor 분위수 ----------
def critical_ratio(product: str, weekday: int = 2, ref_jobs: int = 250) -> float:
    """Cu = 가격 + 품절비 - 한계원가, Co = 하루 보유비. 한계 인건비는 잔업 기준 추정."""
    pr = PRODUCTS[product]
    mat = sum(q * MATERIALS[m]["modes"]["NORMAL"]["price"] for m, q in BOM[product].items())
    per_job = (est_makespan(weekday, ref_jobs + 20, product) - est_makespan(weekday, ref_jobs, product)) / 20
    labor = per_job / 100 * OT_RATE / LOT
    cu = pr["price"] + pr["stockout"] - (mat + labor)
    co = pr["hold"]
    return cu / (cu + co)


# ---------- DP ----------
def plan_product(product: str, demand: pd.Series, start_inv: int = 0,
                 prod_days: list | None = None):
    """demand: 판매일별 목표수요 (DatetimeIndex 연속 일자). start_inv: 첫 판매일 시작 재고.
    prod_days: 생산 가능 날짜 목록 (기본: demand 기간 중 PRODUCTION_WEEKDAYS).
    반환: (DataFrame[date, jobs, units, est_makespan, est_cost, covers], 총비용, {품절일: 수량})"""
    days = list(demand.index)
    need = demand.to_numpy(float).copy()
    # 시작 재고로 앞쪽 수요부터 차감
    inv = float(start_inv)
    for i in range(len(need)):
        use = min(inv, need[i])
        need[i] -= use
        inv -= use
    if prod_days is None:
        prod_days = [d - pd.Timedelta(days=SALE_LAG_DAYS) for d in days]
        prod_days = [d for d in prod_days if d.weekday() in PRODUCTION_WEEKDAYS]
    prod_days = sorted(set(prod_days))
    lag = pd.Timedelta(days=SALE_LAG_DAYS)
    # 각 생산일이 처음 공급할 수 있는 판매일 index
    first = [next((i for i, s in enumerate(days) if s >= d + lag), None) for d in prod_days]
    keep = [i for i, f in enumerate(first) if f is not None]
    prod_days, first = [prod_days[i] for i in keep], [first[i] for i in keep]
    K, N = len(days), len(prod_days)
    hold = PRODUCTS[product]["hold"]
    lost = PRODUCTS[product]["stockout"] + PRODUCTS[product]["price"]   # 품절 1개당 손실
    INF = float("inf")
    # f[i][k]: 판매일 0..k-1 처리 완료, 다음 사용 가능한 생산일이 i 일 때 최소비용
    f = [[INF] * (K + 1) for _ in range(N + 1)]
    back = [[None] * (K + 1) for _ in range(N + 1)]
    f[0][0] = 0.0
    for i in range(N + 1):
        for k in range(K + 1):
            cur = f[i][k]
            if cur == INF:
                continue
            if k < K:                                   # 판매일 k 품절 처리 (또는 수요 0)
                c = cur + lost * need[k]
                if c < f[i][k + 1]:
                    f[i][k + 1], back[i][k + 1] = c, ("short", i, k)
            if i == N:
                continue
            if cur < f[i + 1][k]:                       # 생산일 i 건너뜀
                f[i + 1][k], back[i + 1][k] = cur, ("idle", i, k)
            if k < first[i] or k == K:
                continue
            d = prod_days[i]                            # 생산일 i 가 판매일 k..j-1 커버
            units = hold_cost = 0.0
            for j in range(k, K):
                units += need[j]
                hold_cost += hold * need[j] * (days[j] - d).days
                jobs = math.ceil(units / LOT)
                if jobs > MAX_JOBS:
                    break
                c = cur + production_cost(product, est_makespan(d.weekday(), jobs, product), jobs) + hold_cost
                if c < f[i + 1][j + 1]:
                    f[i + 1][j + 1], back[i + 1][j + 1] = c, ("prod", i, k)
    # 역추적
    plan, shortage = {}, {}
    i, k = N, K
    while (i, k) != (0, 0):
        kind, pi, pk = back[i][k]
        if kind == "prod" and need[pk:k].sum() > 0:
            units = need[pk:k].sum()
            plan[prod_days[pi]] = dict(units=units, jobs=math.ceil(units / LOT),
                                       covers=f"{days[pk]:%m/%d}~{days[k - 1]:%m/%d}")
        elif kind == "short" and need[pk] > 0:
            shortage[days[pk]] = int(need[pk])
        i, k = pi, pk
    rows = []
    for d in prod_days:
        p = plan.get(d, dict(units=0, jobs=0, covers=""))
        ms = est_makespan(d.weekday(), p["jobs"], product)
        rows.append(dict(date=d, jobs=p["jobs"], units=int(p["units"]), est_makespan=ms,
                         est_cost=production_cost(product, ms, p["jobs"]), covers=p["covers"]))
    cols = ["date", "jobs", "units", "est_makespan", "est_cost", "covers"]
    return pd.DataFrame(rows, columns=cols).set_index("date"), f[N][K], shortage


def sequence_for(date: pd.Timestamp, jobs: int, time_limit: float = 15.0, product: str = "P1"):
    """폼 입력용 Job 순서 문자열과 IG makespan."""
    seq, ms = scheduler.best_schedule(date.weekday(), jobs, time_limit=time_limit, product=product)
    return scheduler.to_job_string(seq), ms
