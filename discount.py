"""할인율 결정.

할인 d → 판매단가 p(1-d), 수요 D(1+d) (매뉴얼 Sales 예: 6% 할인 → 판매 6% 증가).
- 평소: 남는 재고는 다음날 정가로 팔리므로 할인은 -p·d·D 만큼 손해 → 0 권장.
- 라운드 종료 직전: 남은 재고는 가치 0 → 재고 소진 이득이 할인 손실보다 크면 할인.
"""
import numpy as np


def end_of_round_discount(excess: float, demand: float, price: float, hold: float = 30,
                          days_left: int = 0, grid=np.arange(0, 0.51, 0.01)):
    """excess: 마지막 판매일 수요(D)를 채우고도 남을 재고. 반환 (d, 기대 이득)."""
    best_d, best_gain = 0.0, 0.0
    for d in grid:
        extra = min(d * demand, excess)
        gain = -price * d * demand + price * (1 - d) * extra + hold * days_left * extra
        if gain > best_gain:
            best_d, best_gain = float(round(d, 2)), gain
    return best_d, best_gain
