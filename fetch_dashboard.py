"""팀 대시보드(로그인 불필요, GET만)를 읽어 state.yaml과 data/ 수요 파일을 갱신한다.

    py fetch_dashboard.py      # → state.yaml, data/P1_latest.xls, data/P2_latest.xls
    py weekly_plan.py --daily  # 오늘 폼에 넣을 값

폼 입력(Apply)은 하지 않는다.
"""
import re
import sys
import urllib.request

import pandas as pd
import yaml

from config import BOM, LOT, ROOT

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://play.ioground.kr:5005"
TEAM = "DKU/26_DKU_RM/R2602B"
STATE = ROOT / "state.yaml"
DATA = ROOT / "data"


def get(path: str) -> bytes:
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return r.read()


def tables(html: str) -> list[list[list[str]]]:
    """페이지의 모든 <table> → 행 × 셀 텍스트."""
    out = []
    for t in re.findall(r"<table.*?</table>", html, flags=re.S):
        rows = []
        for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, flags=re.S):
            cells = [re.sub(r"<[^>]+>|\s+", " ", c).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)]
            if cells:
                rows.append(cells)
        out.append(rows)
    return out


def find(tbls, first_header: str, col: str | None = None) -> pd.DataFrame:
    """헤더 첫 칸(및 포함 컬럼)으로 표를 찾아 DataFrame으로."""
    for t in tbls:
        if t and t[0][0] == first_header and (col is None or col in t[0]):
            return pd.DataFrame(t[1:], columns=t[0])
    raise ValueError(f"표를 찾지 못함: {first_header} / {col}")


def num(s: str) -> int:
    s = re.sub(r"[,$\s]", "", s)
    return int(float(s)) if s else 0


def board(tab: str) -> tuple[str, list]:
    html = get(f"/plans_{tab}/board/{TEAM}").decode("utf-8", "ignore")
    return html, tables(html)


def save_entered_weeks(prod: pd.DataFrame):
    """Production 표 → output/entered_week_<일요일>.txt. 0 Job만 있는 주(빈 자리표시)는 건너뜀."""
    import numpy as np
    import scheduler
    from config import OUT_DIR
    wd = "월화수목금토일"
    prod = prod.copy()
    prod["d"] = pd.to_datetime(prod["Date"])
    prod["week"] = prod["d"] - pd.to_timedelta((prod["d"].dt.weekday + 1) % 7, unit="D")
    OUT_DIR.mkdir(exist_ok=True)
    for wk, g in prod.groupby("week"):
        if g["Planned #Jobs"].map(num).sum() == 0:
            continue
        lines = [f"# {wk:%Y-%m-%d} ~ {wk + pd.Timedelta(days=6):%m-%d} 주간 생산계획 — 사이트에 실제 입력된 값",
                 f"# 저장 {pd.Timestamp.now():%Y-%m-%d %H:%M} (fetch_dashboard.py 자동)", ""]
        for _, r in g.sort_values(["Product", "d"]).iterrows():
            d = r["d"]
            seq = [int(x) for x in r["Sequence"].split(",") if x.strip()] if r["Algo"] == "CUSTOM" else []
            head = f"[{r['Product']} {d:%m/%d}({wd[d.weekday()]}) {r['Algo']} {num(r['Planned #Jobs'])} jobs, 상태 {r['Status']}"
            if seq:
                ms = int(scheduler.makespan(scheduler.load_times(d.weekday(), r["Product"])[:len(seq)],
                                            np.array(seq, np.int64) - 1))
                head += f", 계산 makespan {ms}"
            if r["Makespan"]:
                head += f", 게임 makespan {r['Makespan']}"
            lines += [head + "]"] + ([",".join(map(str, seq))] if seq else []) + [""]
        (OUT_DIR / f"entered_week_{wk:%Y-%m-%d}.txt").write_text("\n".join(lines), encoding="utf-8")


def main():
    html, mat_t = board("material")
    today = pd.Timestamp(re.search(r"Today\(AUTO\):\s*(\d{4}-\d{2}-\d{2})", html).group(1))

    # 1) 수요 데이터
    DATA.mkdir(exist_ok=True)
    for p, code in (("P1", "005930"), ("P2", "BTC")):
        (DATA / f"{p}_latest.xls").write_bytes(get(f"/plans_demand/demand_down/{code}"))

    # 2) 재고 / 미입고 발주
    lvl = find(mat_t, "Material type", "Current level")
    materials = {r["Material type"]: num(r["Current level"]) for _, r in lvl.iterrows()}
    # 발주 내역(Material plans)은 로그인 사용자만 보임 → state.yaml의 목록을 유지하고,
    # Material inventory 표에 입고 기록이 생긴 건은 제거
    old = yaml.safe_load(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    inv = find(mat_t, "Material type", "In date")
    arrived = {(r["Material type"], r["In date"], num(r["In qty"]))
               for _, r in inv.iterrows() if r["In date"]}
    receipts = [dict(material=r["material"], date=str(pd.Timestamp(r["date"]).date()), qty=int(r["qty"]))
                for r in (old.get("scheduled_receipts") or [])]
    receipts = [r for r in receipts if (r["material"], r["date"], r["qty"]) not in arrived]
    _, sal_t = board("sales")
    fg = {r["Product"]: num(r["Current level"])
          for _, r in find(sal_t, "Product", "Current level").iterrows()}
    _, led_t = board("ledger")
    ledger = find(led_t, "Date", "Action")
    _, prod_t = board("production")
    prod = find(prod_t, "Date", "Planned #Jobs")

    # 3) 오늘 정산 여부 → 계획 시작일
    settled = (ledger["Date"] == f"{today:%Y-%m-%d}").any()
    note = "오늘 정산 완료 → 대시보드 재고 = 오늘 마감"
    if not settled:
        # 오늘 입고 예정분 반영 (입고 기록이 생길 때까지 state의 목록에는 남겨 둠 → 재실행해도 안전)
        todays = [r for r in receipts if pd.Timestamp(r["date"]) == today]
        for r in todays:
            materials[r["material"]] = materials.get(r["material"], 0) + r["qty"]
        from data_loader import load_demand
        from forecast import forecast
        data = load_demand()
        for p in ("P1", "P2"):
            row = prod[(prod["Date"] == f"{today:%Y-%m-%d}") & (prod["Product"] == p)]
            jobs = num(row["Planned #Jobs"].iloc[0]) if len(row) else 0
            units = jobs * LOT
            for m, q in BOM[p].items():               # 자재 부족 시 생산 가능량으로 제한
                units = min(units, materials.get(m, 0) // q // LOT * LOT)
            for m, q in BOM[p].items():
                materials[m] -= units * q
            if today in data[p].index:                 # 16시 갱신으로 오늘 실수요가 이미 있음
                dem = int(data[p].loc[today])
            else:
                f, _, _ = forecast(data[p], p, [today], quantiles=(0.5,))
                dem = int(f["q0.5"].iloc[0])
            fg[p] = max(0, fg.get(p, 0) + units - dem)
        note = "오늘 정산 전 → 오늘 계획 생산·예상 수요(중앙값)로 마감 재고 추정"
    plan_start = today + pd.Timedelta(days=1)

    # 이번 주(~토요일) 생산은 주간계획 마감으로 이미 고정 → 실제 입력값을 그대로 기록
    this_sat = today + pd.Timedelta(days=(5 - today.weekday()) % 7)
    locked = {}
    for d in pd.date_range(plan_start, this_sat):
        rows = prod[(prod["Date"] == f"{d:%Y-%m-%d}") & (prod["Status"] == "Planned")]
        locked[d] = {p: (num(rows[rows["Product"] == p]["Planned #Jobs"].iloc[0])
                         if (rows["Product"] == p).any() else 0) for p in ("P1", "P2")}
    locked_lines = "\n".join(f"  {d:%Y-%m-%d}: {{P1: {v['P1']}, P2: {v['P2']}}}"
                             for d, v in locked.items()) or "  {}"

    # 4) state.yaml (round_end, order_mode, 미입고 발주 보존)
    rec_lines = "\n".join(f"  - {{material: {r['material']}, date: {r['date']}, qty: {r['qty']}}}"
                          for r in receipts) or "  []"
    STATE.write_text(f"""# fetch_dashboard.py 자동 생성 ({pd.Timestamp.now():%Y-%m-%d %H:%M})
# ※ 새로 발주하면 scheduled_receipts에 직접 추가 (발주 내역은 로그인해야 보여서 자동으로 못 읽음)
# {note}
as_of: {today:%Y-%m-%d}            # 발주 폼의 Order date (게임상 오늘)
plan_start: {plan_start:%Y-%m-%d}       # --daily 계획 시작일
round_end: {old.get('round_end') or ''}

finished_goods:
  P1: {fg.get('P1', 0)}
  P2: {fg.get('P2', 0)}

materials:
  M1: {materials.get('M1', 0)}
  M2: {materials.get('M2', 0)}
  M3: {materials.get('M3', 0)}

scheduled_receipts:
{rec_lines}

locked_production:           # 이번 주 생산계획 (이미 고정, 대시보드에서 읽음)
{locked_lines}

order_mode: {old.get('order_mode', 'daily')}
""", encoding="utf-8")

    print(f"게임 오늘: {today:%Y-%m-%d} ({note})")
    print(f"완제품 {fg} / 자재 {materials}")
    print(f"미입고 발주 {len(receipts)}건: " + ", ".join(f"{r['material']} {r['qty']:,}({r['date'][5:]})" for r in receipts))

    import numpy as np
    import scheduler

    # 5) 실제 입력된 주간 생산계획을 주(일~토)별 파일로 보관 (sequences_*.txt는 재계산 시 덮어써지므로)
    save_entered_weeks(prod)

    # 6) makespan 검증: CUSTOM으로 생산된 행을 처리시간표로 재계산
    done = prod[(prod["Status"] == "Produced") & (prod["Algo"] == "CUSTOM")]
    for _, r in done.iterrows():
        seq = np.array([int(x) - 1 for x in r["Sequence"].split(",") if x.strip()], np.int64)
        d = pd.Timestamp(r["Date"])
        calc = int(scheduler.makespan(scheduler.load_times(d.weekday(), r["Product"])[: len(seq)], seq))
        game = num(r["Makespan"])
        flag = "OK" if abs(calc - game) <= 5 else "⚠ 불일치"
        print(f"makespan 검증 {r['Date']} {r['Product']}: 게임 {game:,} / 계산 {calc:,} {flag}")


if __name__ == "__main__":
    main()