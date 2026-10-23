"""IOG 입력값 생성 (fetch_dashboard.py 실행 후).

    py weekly_plan.py                 # 오늘 발주 + 다음 주(일~토) 수요예측·생산계획
    py weekly_plan.py --ig-seconds 30 # 스케줄링 탐색 시간 늘리기

노션 규칙 반영:
- 생산·수요예측은 주간계획(다음 주)만 입력 가능 → 이번 주 생산은 state.locked_production(고정)
- 자재·할인은 일계획(매일 19:30까지)
- 라운드 기간 밖은 운영 안 됨 → state.round_end 이후는 생산·자재 계획에서 제외

출력: 화면 + output/plan_<다음주시작일>.md + output/sequences_<다음주시작일>.txt
"""
import argparse
import sys

import pandas as pd
import yaml

from config import LOT, OUT_DIR, PRODUCTION_WEEKDAYS, PRODUCTS, SERVICE_Q
from cost_model import production_cost
from data_loader import load_demand
from discount import end_of_round_discount
from forecast import forecast
from material_plan import plan_all
from production_plan import plan_product, sequence_for

sys.stdout.reconfigure(encoding="utf-8")
WD = "월화수목금토일"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="state.yaml")
    ap.add_argument("--ig-seconds", type=float, default=30.0)
    ap.add_argument("--daily", action="store_true", help="(호환용, 무시)")
    args = ap.parse_args()

    st = yaml.safe_load(open(args.state, encoding="utf-8"))
    today = pd.Timestamp(st["as_of"])
    plan_start = pd.Timestamp(st.get("plan_start") or today + pd.Timedelta(days=1))
    this_sat = today + pd.Timedelta(days=(5 - today.weekday()) % 7)
    nw_start = this_sat + pd.Timedelta(days=1)                 # 다음 주 일요일
    rend = pd.Timestamp(st["round_end"]) if st.get("round_end") else None
    horizon_end = nw_start + pd.Timedelta(days=13)              # 다음 주 + 그다음 주(잠정)
    if rend is not None:
        horizon_end = min(horizon_end, rend)
    horizon = pd.date_range(plan_start, horizon_end)
    next_week = [d for d in pd.date_range(nw_start, periods=7) if d <= horizon_end]
    locked = {pd.Timestamp(k): v for k, v in (st.get("locked_production") or {}).items()}
    q = SERVICE_Q["weekly"]

    data = load_demand()
    out = [f"# IOG 계획 — 기준일 {today:%m/%d}({WD[today.weekday()]})", ""]
    for p, s in data.items():
        out.append(f"- {p} 최신 데이터: {s.index[-1]:%Y-%m-%d} = {int(s.iloc[-1]):,}")
    if rend is not None:
        out.append(f"- 라운드 마감 {rend:%m/%d}: 이후 생산·자재는 계획에서 제외")

    fc = {}
    for p in ("P1", "P2"):
        f, model, _ = forecast(data[p], p, horizon, quantiles=(0.5, q))
        fc[p] = (f, model)

    # ---------- 생산: 이번 주 고정분 + 다음 주 DP ----------
    plans, seq_lines, prod_out = {}, [], []
    for p in ("P1", "P2"):
        f = fc[p][0]
        # 이번 주 말(토)까지 완제품 재고 추정: 고정 생산 − 예상 수요(중앙값)
        inv = float(st["finished_goods"].get(p, 0))
        for d in pd.date_range(plan_start, this_sat):
            if rend is not None and d > rend:
                break
            inv = max(0.0, inv + locked.get(d, {}).get(p, 0) * LOT - f.loc[d, "q0.5"])
        jobs = pd.Series({d: locked.get(d, {}).get(p, 0) for d in pd.date_range(plan_start, this_sat)
                          if d <= horizon_end}, dtype=int)
        if next_week:
            # 라운드 마지막 날도 같은 분위수 유지: 남는 1개 손해(약 220원) < 모자란 1개 손해(약 310원)
            sale_days = f.loc[nw_start:horizon_end, f"q{q}"]
            prod_days = [d for d in sale_days.index if d.weekday() in PRODUCTION_WEEKDAYS]
            table, _, short = plan_product(p, sale_days, start_inv=inv, prod_days=prod_days)
            jobs = pd.concat([jobs, table["jobs"]])
            prod_out += [f"### {p} (예측분포 {q:.0%} 분위수, 다음 주 시작 재고 추정 {int(inv):,}개)", "",
                         "| 생산일 | Job 수 | 판매 커버 | makespan | 인건비+셋업 |", "|---|---:|---|---:|---:|"]
            for d in next_week:
                r = table.loc[d] if d in table.index else None
                n = int(r.jobs) if r is not None else 0
                if n > 0:
                    seq, ms = sequence_for(d, n, args.ig_seconds, product=p)
                    seq_lines += [f"[{p} {d:%m/%d}({WD[d.weekday()]}) {n} jobs, makespan {ms}]", seq, ""]
                    prod_out.append(f"| {d:%m/%d}({WD[d.weekday()]}) | **{n}** (Job sequence) | {r.covers} | "
                                    f"{ms:,} | {production_cost(p, ms, n):,} |")
                else:
                    prod_out.append(f"| {d:%m/%d}({WD[d.weekday()]}) | 0 (Job qty) | | - | 0 |")
            if short:
                prod_out.append("\n⚠ 커버 불가 예상: " + ", ".join(f"{d:%m/%d} {v:,}개" for d, v in short.items()))
            prod_out.append("")
        plans[p] = jobs

    if next_week:
        out += ["", f"## ① 수요예측 입력 — 다음 주 {nw_start:%m/%d}~ (주간계획, 토 19:30 마감)", "",
                "| 날짜 | P1 | P2 |", "|---|---:|---:|"]
        for d in pd.date_range(nw_start, periods=7):
            if d in fc["P1"][0].index:
                out.append(f"| {d:%m/%d}({WD[d.weekday()]}) | {fc['P1'][0].loc[d, 'q0.5']:,} | "
                           f"{fc['P2'][0].loc[d, 'q0.5']:,} |")
            else:
                out.append(f"| {d:%m/%d}({WD[d.weekday()]}) | 0 (라운드 종료) | 0 (라운드 종료) |")
        out.append(f"\n모델: P1={fc['P1'][1]}, P2={fc['P2'][1]} (중앙값)")
        out += ["", "## ② 생산계획 입력 — 다음 주 (주간계획, 토 19:30 마감)", ""] + prod_out
        for d in pd.date_range(nw_start, periods=7):
            if d > horizon_end:
                out.append(f"- {d:%m/%d}: P1·P2 모두 0 (라운드 종료 후)")
        out.append("Job 순서는 sequences 파일에서 해당 [제품 날짜] 아래 줄을 복사.")

    # ---------- 자재 (일계획) ----------
    order_dates = list(pd.date_range(today, horizon_end))
    # state의 자재 재고는 "오늘 마감" 기준(오늘 입고분 포함) → 오늘 이전·당일 입고 예정은 중복이므로 제외
    future_rc = [r for r in (st.get("scheduled_receipts") or []) if pd.Timestamp(r["date"]) > today]
    orders, shortages, _ = plan_all(plans, st["materials"], future_rc, order_dates,
                                    no_safety_until=this_sat)   # 이번 주 생산은 고정 → 자재 여유 0%
    out += ["", "## ③ 자재 발주 (일계획, 매일 19:30까지)", ""]
    todays = orders[orders.order_date == today] if len(orders) else orders
    if len(todays):
        out += ["**오늘 입력:**", "", "| 자재 | 유형 | 수량 | 입고일 | 커버 생산일 |", "|---|---|---:|---|---|"]
        for _, o in todays.iterrows():
            out.append(f"| {o.material} | {o['mode']} | **{o.qty:,}** | {o.arrival:%m/%d} | {o.covers} |")
    else:
        out.append("**오늘 입력할 발주 없음.**")
    later = orders[orders.order_date > today] if len(orders) else orders
    if len(later):
        out += ["", "이후 예정 (잠정, 그날 다시 계산):", "", "| 발주일 | 자재 | 유형 | 수량 | 입고일 |", "|---|---|---|---:|---|"]
        for _, o in later.sort_values(["order_date", "material"]).iterrows():
            out.append(f"| {o.order_date:%m/%d}({WD[o.order_date.weekday()]}) | {o.material} | {o['mode']} | "
                       f"{o.qty:,} | {o.arrival:%m/%d} |")
    if shortages:
        out.append(f"\n⚠ 자재 부족 예상: {shortages}")

    # ---------- 할인 (일계획) ----------
    out += ["", "## ④ 할인율 (일계획)", ""]
    if rend is not None and today == rend:
        for p in ("P1", "P2"):
            f = fc[p][0]
            dem = f.loc[today, "q0.5"] if today in f.index else 0
            prod_today = locked.get(today, {}).get(p, 0) * LOT
            excess = max(0, st["finished_goods"].get(p, 0) + prod_today - dem)
            d, gain = end_of_round_discount(excess, dem, PRODUCTS[p]["price"]) if dem else (0.0, 0)
            out.append(f"- {p}: 할인율 **{d}** (라운드 마지막 날 남는 재고 약 {int(excess):,}개, 기대 이득 {gain:,.0f}원)")
    else:
        out.append("- P1·P2 모두 0.0 (입력 안 해도 0으로 처리)")

    md = "\n".join(out)
    print(md)
    OUT_DIR.mkdir(exist_ok=True)
    tag = f"{nw_start:%Y-%m-%d}"
    (OUT_DIR / f"plan_{tag}.md").write_text(md, encoding="utf-8")
    if seq_lines:
        (OUT_DIR / f"sequences_{tag}.txt").write_text("\n".join(seq_lines), encoding="utf-8")
    print(f"\n저장: output/plan_{tag}.md" + (f", output/sequences_{tag}.txt" if seq_lines else ""))


if __name__ == "__main__":
    main()
