"""과거 데이터로 전략 비교 시뮬레이션 (제품 측면만; 자재는 충분하다고 가정).

매주 토요일: 그 주 금요일까지 데이터로 예측 → 다음 주 생산계획 → 실제 수요로 판매/재고/품절 정산.
"""
import numpy as np
import pandas as pd

import scheduler
from config import BOM, LOT, MATERIALS, PRODUCTION_WEEKDAYS, PRODUCTS, SALE_LAG_DAYS
from cost_model import production_cost
from forecast import forecast
from krx_calendar import is_trading_day
from production_plan import est_makespan, plan_product

_spt_cache = {}


def spt_makespan(weekday, jobs, product="P1"):
    key = (product, weekday, jobs)
    if key not in _spt_cache:
        p = scheduler.load_times(weekday, product)[:jobs]
        _spt_cache[key] = int(scheduler.makespan(p, scheduler.spt(p)))
    return _spt_cache[key]


def actual_demand(series: pd.Series, product: str, dates) -> pd.Series:
    out = []
    for d in dates:
        if product == "P1" and not is_trading_day(d.date()):
            out.append(0.0)
        else:
            out.append(float(series.get(d, np.nan)))
    return pd.Series(out, index=dates)


def run(series: pd.Series, product: str, start: str, weeks: int, q: float = 0.5,
        model: str | None = None, seq: str = "neh", replan: str = "weekly", start_inv=0):
    """q: 생산 기준 분위수, model: None=백테스트 최적 / 'ma5'=게임 Auto,
    seq: 'spt'(게임 Auto) | 'neh', replan: 'weekly'(토요일 1회) | 'daily'(매일 재계획)."""
    pr = PRODUCTS[product]
    inv_batches = []                    # [(available_date, qty)]
    inv = float(start_inv)
    log = []
    ws0 = pd.Timestamp(start)
    table = None
    for d in pd.date_range(ws0, periods=7 * weeks):
        if replan == "daily" or d.weekday() == 6:          # 일요일 = 주간 계획 시작
            # 주간: 금요일까지 데이터 / 일간: 전날까지 데이터
            cutoff = d - pd.Timedelta(days=1 if replan == "daily" else 2)
            hist = series[series.index <= cutoff]
            horizon = pd.date_range(d, periods=14)
            f, _, _ = forecast(hist, product, horizon, quantiles=(q,), model_name=model,
                               n_origins=60 if model == "ma5" else 250)
            # 미래 생산일까지 포함해 계획하고, 실행은 이번 주(주간) / 오늘(일간)분만
            prod_days = [x - pd.Timedelta(days=SALE_LAG_DAYS) for x in horizon]
            prod_days = [x for x in prod_days if x >= d and x.weekday() in PRODUCTION_WEEKDAYS]
            pending = inv + sum(qq for a, qq in inv_batches)
            table, _, _ = plan_product(product, f[f"q{q}"], start_inv=pending, prod_days=prod_days)
        if table is not None and d in table.index and table.loc[d, "jobs"] > 0:
            jobs = int(table.loc[d, "jobs"])
            ms = spt_makespan(d.weekday(), jobs, product) if seq == "spt" else est_makespan(d.weekday(), jobs, product)
            log.append(dict(date=d, kind="prod", jobs=jobs, cost=production_cost(product, ms, jobs)))
            inv_batches.append((d + pd.Timedelta(days=SALE_LAG_DAYS), jobs * LOT))
        inv += sum(qq for a, qq in inv_batches if a <= d)          # 판매 가능해진 물량
        inv_batches = [(a, qq) for a, qq in inv_batches if a > d]
        dem = actual_demand(series, product, [d]).iloc[0]
        if np.isnan(dem):
            continue
        sold = min(inv, dem)
        inv -= sold
        log.append(dict(date=d, kind="day", demand=dem, sold=sold, short=dem - sold,
                        end_inv=inv + sum(qq for a, qq in inv_batches)))
    df = pd.DataFrame(log)
    days = df[df.kind == "day"]
    revenue = days.sold.sum() * pr["price"]
    hold = days.end_inv.sum() * pr["hold"]
    short = days.short.sum() * pr["stockout"]
    prod = df[df.kind == "prod"].cost.sum()
    mat_unit = sum(q * MATERIALS[m]["modes"]["NORMAL"]["price"] for m, q in BOM[product].items())
    mat = df[df.kind == "prod"].jobs.sum() * LOT * mat_unit
    return dict(revenue=revenue, production=prod, material=mat, holding=hold,
                stockout_cost=short, profit=revenue - prod - mat - hold - short,
                fill_rate=days.sold.sum() / days.demand.sum()), df


STRATEGIES = {   # 이름: run() 인자
    "게임 Auto (MA5+SPT)": dict(model="ma5", seq="spt", q=0.5),
    "최적예측+NEH": dict(q=0.5),
}


def compare(data: dict, start: str, weeks: int, qs=(0.5, 0.6, 0.7, 0.8, 0.9)):
    """전략 × 분위수 × 재계획주기 비교표 (단위: 원)."""
    rows = []
    for p, s in data.items():
        for name, kw in STRATEGIES.items():
            r, _ = run(s, p, start, weeks, **kw)
            rows.append(dict(product=p, strategy=name, replan="weekly", q=kw["q"], **r))
        for replan in ("weekly", "daily"):
            for q in qs:
                r, _ = run(s, p, start, weeks, q=q, replan=replan)
                rows.append(dict(product=p, strategy="최적예측+NEH", replan=replan, q=q, **r))
    return pd.DataFrame(rows).drop_duplicates(["product", "strategy", "replan", "q"])
