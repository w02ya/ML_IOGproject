"""생산비/재고비 계산 (문제소개 p23-24, 매뉴얼 Ledger p24 규칙)."""
from config import PRODUCTS, REG_HOURS, REG_RATE, OT_RATE


def labor_cost(makespan: int) -> int:
    hours = int(makespan) // 100
    reg = min(hours, REG_HOURS)
    return reg * REG_RATE + (hours - reg) * OT_RATE


def production_cost(product: str, makespan: int, jobs: int) -> int:
    if jobs <= 0:
        return 0
    return PRODUCTS[product]["setup"] + labor_cost(makespan)


if __name__ == "__main__":
    # 문제소개 p24: 6,680 → 6.6M, 8,850 → 10.6M, 9,466 → 11.8M / 매뉴얼 p24: 9,363 + setup → 16.6M
    assert labor_cost(6680) == 6_600_000
    assert labor_cost(8850) == 10_600_000
    assert labor_cost(9466) == 11_800_000
    assert production_cost("P1", 9363, 154) == 16_600_000
    print("cost_model OK")
