"""Permutation flow shop 스케줄링 (n jobs × 20 machines, makespan 최소화).

- makespan: 순서 → 완료시간
- spt: 시스템 Auto와 동일 (지정 설비 처리시간 오름차순)
- neh: Nawaz-Enscore-Ham (Taillard 가속)
- iterated_greedy: Ruiz & Stützle (2007) IG, NEH에서 출발해 destroy/reconstruct + 국소탐색
"""
import json
import time

import numpy as np
import pandas as pd
from numba import njit

from config import PROC_DIR, OUT_DIR, TABLE_PREFIX

WEEKDAY_FILE = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}


def load_times(weekday: int, product: str = "P1") -> np.ndarray:
    """제품·요일별 처리시간표 → (500, 20) int 배열. 행 i = JobID i+1."""
    f = PROC_DIR / f"{TABLE_PREFIX[product]}_500_20_{WEEKDAY_FILE[weekday]}.csv"
    df = pd.read_csv(f).sort_values("JobID")
    return np.ascontiguousarray(df.filter(regex=r"^M\d+$").to_numpy(np.int64))


@njit(cache=True)
def makespan(p, seq):
    m = p.shape[1]
    c = np.zeros(m, np.int64)
    for j in seq:
        c[0] += p[j, 0]
        for k in range(1, m):
            c[k] = max(c[k], c[k - 1]) + p[j, k]
    return c[m - 1]


@njit(cache=True)
def _best_insertion(p, seq, k, job):
    """seq[:k]에 job을 넣을 최적 위치와 그때의 makespan (Taillard 가속, O(k·m))."""
    m = p.shape[1]
    e = np.zeros((k + 1, m), np.int64)   # e[i]: seq[:i] 의 head (완료시각)
    q = np.zeros((k + 2, m), np.int64)   # q[i]: seq[i:k] 의 tail
    for i in range(k):
        j = seq[i]
        for r in range(m):
            prev = e[i + 1, r - 1] if r > 0 else 0
            e[i + 1, r] = max(e[i, r], prev) + p[j, r]
    for i in range(k - 1, -1, -1):
        j = seq[i]
        for r in range(m - 1, -1, -1):
            nxt = q[i, r + 1] if r < m - 1 else 0
            q[i, r] = max(q[i + 1, r], nxt) + p[j, r]
    best_pos, best_val = 0, np.int64(1) << 62
    f = np.zeros(m, np.int64)
    for pos in range(k + 1):
        for r in range(m):
            prev = f[r - 1] if r > 0 else 0
            f[r] = max(e[pos, r], prev) + p[job, r]
        val = 0
        for r in range(m):
            v = f[r] + q[pos, r]
            if v > val:
                val = v
        if val < best_val:
            best_val, best_pos = val, pos
    return best_pos, best_val


@njit(cache=True)
def _insert(seq, k, pos, job):
    for i in range(k, pos, -1):
        seq[i] = seq[i - 1]
    seq[pos] = job


@njit(cache=True)
def _remove(seq, k, pos):
    for i in range(pos, k - 1):
        seq[i] = seq[i + 1]


@njit(cache=True)
def _neh_from_order(p, order):
    n = order.shape[0]
    seq = np.empty(n, np.int64)
    seq[0] = order[0]
    for k in range(1, n):
        pos, _ = _best_insertion(p, seq, k, order[k])
        _insert(seq, k, pos, order[k])
    return seq


def neh(p: np.ndarray) -> np.ndarray:
    order = np.argsort(-p.sum(axis=1), kind="stable").astype(np.int64)
    return _neh_from_order(p, order)


@njit(cache=True)
def _local_search(p, seq, cur):
    """Insertion local search: 각 job을 빼서 최적 위치에 재삽입, 개선 없을 때까지."""
    n = seq.shape[0]
    improved = True
    while improved:
        improved = False
        perm = np.random.permutation(n)
        for t in range(n):
            job = seq[perm[t] % n]
            idx = 0
            for i in range(n):
                if seq[i] == job:
                    idx = i
                    break
            _remove(seq, n, idx)
            pos, val = _best_insertion(p, seq, n - 1, job)
            _insert(seq, n - 1, pos, job)
            if val < cur:
                cur = val
                improved = True
    return cur


@njit(cache=True)
def _ig(p, seq, iters, d, temp, seed):
    np.random.seed(seed)
    n = seq.shape[0]
    cur = _local_search(p, seq, makespan(p, seq))
    best = seq.copy()
    best_val = cur
    work = np.empty(n, np.int64)
    removed = np.empty(d, np.int64)
    for _ in range(iters):
        work[:] = seq
        k = n
        for t in range(d):                      # destroy
            pos = np.random.randint(k)
            removed[t] = work[pos]
            _remove(work, k, pos)
            k -= 1
        for t in range(d):                      # reconstruct
            pos, _ = _best_insertion(p, work, k, removed[t])
            _insert(work, k, pos, removed[t])
            k += 1
        val = _local_search(p, work, makespan(p, work))
        if val < cur or np.random.random() < np.exp(-(val - cur) / temp):
            seq[:] = work
            cur = val
            if val < best_val:
                best[:] = work
                best_val = val
    return best, best_val


def iterated_greedy(p: np.ndarray, time_limit: float = 10.0, d: int = 4, seed: int = 0):
    """시간 제한 내 IG. 반환: (0-based 순서, makespan)."""
    n = p.shape[0]
    seq = neh(p)
    if n <= 2:
        return seq, makespan(p, seq)
    d = min(d, n - 1)
    temp = 0.4 * p.sum() / (n * p.shape[1] * 10)   # Ruiz & Stützle 온도
    best, best_val = seq.copy(), makespan(p, seq)
    t0, chunk, s = time.time(), 20, seed
    while time.time() - t0 < time_limit:
        cand, val = _ig(p, best.copy(), chunk, d, temp, s)
        s += 1
        if val < best_val:
            best, best_val = cand, val
    return best, int(best_val)


def spt(p: np.ndarray, machine: int = 0) -> np.ndarray:
    return np.argsort(p[:, machine], kind="stable").astype(np.int64)


def to_job_string(seq0: np.ndarray) -> str:
    """0-based → 폼 입력용 '3,5,4,2,1' 문자열 (JobID는 1부터)."""
    return ",".join(str(int(j) + 1) for j in seq0)


# ---------- 캐시: (요일, n) → 최적 순서 ----------
CACHE_FILE = OUT_DIR / "schedule_cache.json"


def _load_cache():
    return json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}


def best_schedule(weekday: int, n: int, time_limit: float = 20.0, product: str = "P1"):
    """요일·Job 수에 대한 최적 순서(캐시). 반환 (seq0, makespan)."""
    if n <= 0:
        return np.array([], np.int64), 0
    cache = _load_cache()
    key = f"{product}:{weekday}:{n}"
    if key in cache:
        return np.array(cache[key]["seq"], np.int64), cache[key]["makespan"]
    p = load_times(weekday, product)[:n]
    seq, val = iterated_greedy(p, time_limit=time_limit)
    cache[key] = {"seq": [int(x) for x in seq], "makespan": int(val)}
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache))
    return seq, int(val)


def neh_makespan(weekday: int, n: int, product: str = "P1") -> int:
    """빠른 근사 (계획 단계 비용 추정용)."""
    if n <= 0:
        return 0
    p = load_times(weekday, product)[:n]
    return int(makespan(p, neh(p)))
