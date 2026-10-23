"""수요 데이터 로딩. 여러 스냅샷 파일을 합치고, 같은 날짜는 가장 최신 파일 값을 쓴다."""
import pandas as pd

from config import DATA_DIRS

P1_SPLIT_DATE = pd.Timestamp("2018-05-04")   # 삼성전자 50:1 액면분할


def _classify(df: pd.DataFrame) -> str:
    """파일명이 애매하므로(demand_data (1).csv) 주말 데이터 유무로 P1/P2 판별."""
    has_weekend = (df["DATE"].dt.weekday >= 5).any()
    return "P2" if has_weekend else "P1"


def load_demand() -> dict[str, pd.Series]:
    """{'P1': Series, 'P2': Series} (DatetimeIndex, 오름차순). P1은 거래일만 포함."""
    frames = {"P1": [], "P2": []}
    files = []
    for d in DATA_DIRS:
        if d.exists():
            files += [f for f in d.iterdir() if f.suffix.lower() in (".csv", ".xls", ".xlsx")]
    for f in sorted(files, key=lambda p: p.stat().st_mtime):
        df = pd.read_csv(f) if f.suffix.lower() == ".csv" else pd.read_excel(f)
        df["DATE"] = pd.to_datetime(df["DATE"])
        df["_mtime"] = f.stat().st_mtime
        frames[_classify(df)].append(df)
    out = {}
    for p, dfs in frames.items():
        if not dfs:
            continue
        df = (pd.concat(dfs).sort_values(["DATE", "_mtime"])
              .drop_duplicates("DATE", keep="last").set_index("DATE"))
        s = df["DEMAND_QTY"].astype(float)
        if p == "P1":
            s = s[s.index >= P1_SPLIT_DATE]
        out[p] = s
    return out


if __name__ == "__main__":
    d = load_demand()
    for p, s in d.items():
        print(p, len(s), s.index.min().date(), "~", s.index.max().date(), "last", int(s.iloc[-1]))
