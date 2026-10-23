"""자재 구매계획: MRP 전개 + 리드타임 고려 lot-sizing DP.

- 생산일 d에 필요한 자재 = Job 수 × 1000 × BOM. 당일 입고분은 당일 생산 투입 가능.
- 발주일 t + 리드타임 L = 입고일. 주말·공휴일도 리드타임에 포함.
- 비용: 주문비(회당) + 구매단가 + 보관비(개·일). M2는 일반(8일) / 긴급(2일, 단가 2배) 선택.
"""
import pandas as pd

from config import BOM, LOT, MATERIALS

SAFETY = 0.10    # 소요량 대비 안전여유 (자재 보관비 1~2원 ≪ 품절 시 생산 손실)


def requirements(prod_plans: dict) -> pd.DataFrame:
    """prod_plans: {'P1': Series(date→jobs), 'P2': ...} → DataFrame(date × M1..M3) 소요량."""
    req = {}
    for p, jobs in prod_plans.items():
        for d, n in jobs.items():
            for m, q in BOM[p].items():
                req.setdefault(d, {}).setdefault(m, 0)
                req[d][m] += int(n) * LOT * q
    return pd.DataFrame(req).T.fillna(0).sort_index()


def plan_material(m: str, need: pd.Series, on_hand: int, receipts: dict,
                  order_dates: list, safety: float = SAFETY, no_safety_until=None):
    """need: 생산일별 소요량. receipts: {date: qty} 입고예정. order_dates: 발주 가능일.
    반환: (orders DataFrame, shortage dict, 총비용)"""
    info = MATERIALS[m]
    days = sorted(set(need.index) | set(receipts))
    # 순소요량: 현재고 + 입고예정으로 먼저 충당 (입고예정은 해당 일자부터 사용 가능)
    stock, net = float(on_hand), {}
    for d in days:
        stock += receipts.get(d, 0)
        r = float(need.get(d, 0))
        use = min(stock, r)
        stock -= use
        if r - use > 0:
            # 생산계획이 이미 고정된 날은 소요량이 확정 → 안전여유 불필요
            s = 0.0 if (no_safety_until is not None and d <= no_safety_until) else safety
            net[d] = (r - use) * (1 + s)
    rdays = sorted(net)
    K = len(rdays)
    opps = []   # (입고일, 발주일, mode, 단가, 리드타임)
    for t in order_dates:
        for mode, mi in info["modes"].items():
            opps.append((t + pd.Timedelta(days=mi["lead"]), t, mode, mi["price"], mi["lead"]))
    opps.sort()
    N = len(opps)
    INF = float("inf")
    f = [[INF] * (K + 1) for _ in range(N + 1)]
    back = [[None] * (K + 1) for _ in range(N + 1)]
    f[0][0] = 0.0
    BIG = 10_000      # 자재 부족 1개당 페널티 (생산 불가 → 제품 품절)
    for i in range(N + 1):
        for k in range(K + 1):
            cur = f[i][k]
            if cur == INF:
                continue
            if k < K and cur + BIG * net[rdays[k]] < f[i][k + 1]:
                f[i][k + 1], back[i][k + 1] = cur + BIG * net[rdays[k]], ("short", i, k)
            if i == N:
                continue
            if cur < f[i + 1][k]:
                f[i + 1][k], back[i + 1][k] = cur, ("idle", i, k)
            arr, _, _, price, _ = opps[i]
            if k == K or rdays[k] < arr:
                continue
            qty = hold = 0.0
            for j in range(k, K):
                qty += net[rdays[j]]
                hold += info["hold"] * net[rdays[j]] * (rdays[j] - arr).days
                c = cur + info["order_cost"] + price * qty + hold
                if c < f[i + 1][j + 1]:
                    f[i + 1][j + 1], back[i + 1][j + 1] = c, ("order", i, k)
    orders, short = [], {}
    i, k = N, K
    while (i, k) != (0, 0):
        kind, pi, pk = back[i][k]
        if kind == "order":
            arr, t, mode, price, lead = opps[pi]
            qty = int(-(-sum(net[rdays[j]] for j in range(pk, k)) // 1000) * 1000)   # 천 단위 올림
            orders.append(dict(material=m, order_date=t, mode=mode, qty=qty, arrival=arr,
                               covers=f"{rdays[pk]:%m/%d}~{rdays[k - 1]:%m/%d}"))
        elif kind == "short":
            short[rdays[pk]] = int(net[rdays[pk]])
        i, k = pi, pk
    return pd.DataFrame(orders[::-1]), short, f[N][K]


def plan_all(prod_plans: dict, on_hand: dict, receipts: list, order_dates: list, no_safety_until=None):
    """receipts: [{'material','date','qty'}]. 반환: (orders DataFrame, {material: shortage})."""
    req = requirements(prod_plans)
    all_orders, shortages = [], {}
    for m in MATERIALS:
        need = req[m] if m in req else pd.Series(dtype=float)
        rc = {}
        for r in receipts:
            if r["material"] == m:
                rc[pd.Timestamp(r["date"])] = rc.get(pd.Timestamp(r["date"]), 0) + r["qty"]
        o, s, _ = plan_material(m, need, on_hand.get(m, 0), rc, order_dates, no_safety_until=no_safety_until)
        if len(o):
            all_orders.append(o)
        if s:
            shortages[m] = s
    orders = pd.concat(all_orders, ignore_index=True) if all_orders else pd.DataFrame()
    return orders, shortages, req
