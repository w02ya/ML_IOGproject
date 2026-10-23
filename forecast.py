"""수요예측: 모델 백테스트(rolling origin) + 중앙값/분위수 예측.

모든 모델은 로그 수준에서 동작하고, horizon h = 관측 간격 수
(P1은 거래일 기준, P2는 달력일 기준).
"""
import warnings

import numpy as np
import pandas as pd

from krx_calendar import is_trading_day

warnings.filterwarnings("ignore")
MAX_H = 10


# ---------- 모델: 로그 시계열 y(끝까지) → h=1..H 로그 예측 ----------
def m_naive(y, H):
    return np.full(H, y[-1])


def make_drift(window):
    def f(y, H):
        r = np.diff(y[-window - 1:]).mean()
        return y[-1] + r * np.arange(1, H + 1)
    f.__name__ = f"drift{window}"
    return f


def make_ma(k):
    def f(y, H):
        return np.full(H, y[-k:].mean())
    f.__name__ = f"ma{k}"
    return f


def make_ses(alpha):
    def f(y, H):
        level = y[-60]
        for v in y[-59:]:
            level = alpha * v + (1 - alpha) * level
        return np.full(H, level)
    f.__name__ = f"ses{alpha}"
    return f


def m_arima(y, H):
    from statsmodels.tsa.arima.model import ARIMA
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = ARIMA(y[-250:], order=(1, 1, 1)).fit()
    return np.asarray(res.forecast(H))


MODELS = [m_naive, make_drift(20), make_drift(60), make_ma(3), make_ma(5), make_ma(10),
          make_ses(0.5), make_ses(0.8), m_arima]


def backtest(series: pd.Series, n_origins: int = 250, H: int = MAX_H, models=MODELS):
    """반환: DataFrame[model, h, mape] 와 로그오차(실제-예측) 배열 dict[(model, h)]."""
    y = np.log(series.to_numpy(float))
    rows, errs = [], {}
    origins = range(len(y) - H - n_origins, len(y) - H)
    for f in models:
        n_o = n_origins if f is not m_arima else min(n_origins, 80)   # ARIMA는 느려서 축소
        e = np.full((n_o, H), np.nan)
        for i, t in enumerate(list(origins)[-n_o:]):
            pred = f(y[: t + 1], H)
            e[i] = y[t + 1: t + 1 + H] - pred
        for h in range(H):
            ae = np.abs(np.expm1(e[:, h]))          # |실제/예측 - 1| ≈ APE
            rows.append(dict(model=f.__name__, h=h + 1, mape=100 * ae.mean()))
            errs[(f.__name__, h + 1)] = e[:, h]
    return pd.DataFrame(rows), errs


def choose_model(bt: pd.DataFrame, max_h: int = 8):
    """평균 MAPE 최소 모델. ARIMA는 표본(origin) 수가 달라 비교 불공정 → 자동선택 제외."""
    avg = bt[bt.h <= max_h].groupby("model").mape.mean().sort_values()
    return avg.drop("m_arima", errors="ignore").index[0], avg


def target_dates(product: str, last_obs: pd.Timestamp, dates):
    """예측 대상 날짜 → horizon (P1: 거래일 수, P2: 달력일 수). 비거래일 P1은 None."""
    out = {}
    for d in dates:
        if product == "P1":
            if not is_trading_day(d.date()):
                out[d] = None
                continue
            out[d] = sum(is_trading_day((last_obs + pd.Timedelta(days=k)).date())
                         for k in range(1, (d - last_obs).days + 1))
        else:
            out[d] = (d - last_obs).days
    return out


def forecast(series: pd.Series, product: str, dates, quantiles=(0.5, 0.9),
             model_name: str | None = None, n_origins: int = 250):
    """dates 각각의 예측. 반환 DataFrame[index=date, h, q0.5, q0.9, ...] (단위: 개, 정수)."""
    fast_models = [m for m in MODELS if m is not m_arima]     # ARIMA는 자동선택 제외 → 계산 생략
    bt, errs = backtest(series, n_origins=n_origins, models=fast_models)
    if model_name is None:
        model_name, _ = choose_model(bt)
    f = next(m for m in MODELS if m.__name__ == model_name)
    y = np.log(series.to_numpy(float))
    pred = f(y, 40)
    hs = target_dates(product, series.index[-1], dates)
    rows = []
    for d, h in hs.items():
        row = {"date": d, "h": h}
        for q in quantiles:
            if h is None:
                row[f"q{q}"] = 0
            else:
                e = errs[(model_name, min(h, MAX_H))]
                e = e[~np.isnan(e)]
                scale = np.sqrt(h / MAX_H) if h > MAX_H else 1.0   # random walk: 오차 ∝ √h
                row[f"q{q}"] = int(np.exp(pred[h - 1] + scale * np.quantile(e, q)))
        rows.append(row)
    return pd.DataFrame(rows).set_index("date"), model_name, bt


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    from data_loader import load_demand
    data = load_demand()
    for p, s in data.items():
        bt, _ = backtest(s)
        best, avg = choose_model(bt)
        print(f"== {p}: 평균 MAPE(h=1..8)\n{avg.round(2).to_string()}\n→ 선택: {best}")
        print(bt[bt.model == best].set_index("h").mape.round(2).to_string())
