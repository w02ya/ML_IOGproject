"""보고서용 그림 4개 → ../보고서_그림/*.png

    py report_figures.py
"""
import re
import sys
import urllib.parse
import urllib.request

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import scheduler
from config import ROOT

sys.stdout.reconfigure(encoding="utf-8")
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
OUT = ROOT.parent / "보고서_그림"
OUT.mkdir(exist_ok=True)
BASE = "http://play.ioground.kr:5005"
WD = ["월", "화", "수", "목", "금", "토", "일"]


def labor_cost(ms: int, setup: int) -> int:
    h = ms // 100
    return setup + min(h, 70) * 100_000 + max(h - 70, 0) * 200_000


# 그림 1: 요일별 평균 처리시간 (P1 vs P2)
p1 = [scheduler.load_times(d, "P1").mean() for d in range(7)]
p2 = [scheduler.load_times(d, "P2").mean() for d in range(7)]
x = np.arange(7)
fig, ax = plt.subplots(figsize=(7, 3.4))
ax.bar(x - 0.2, p1, 0.4, label="P1 (t_)", color="#9aa5b1")
ax.bar(x + 0.2, p2, 0.4, label="P2 (t2_)", color="#2f6db5")
for i, v in enumerate(p2):
    ax.text(i + 0.2, v + 1.5, f"{v:.0f}", ha="center", fontsize=9)
ax.set_xticks(x, WD)
ax.set_ylabel("Job·공정당 평균 처리시간")
ax.set_title("요일별 평균 처리시간: P2는 금요일이 가장 짧음")
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig(OUT / "그림1_요일별_처리시간.png", dpi=200)

# 그림 2: 생산 순서 방법별 makespan (P1 화요일 282 Job = 10/6 실제 생산량)
p = scheduler.load_times(1, "P1")[:282]
ms = {"SPT\n(게임 Auto)": int(scheduler.makespan(p, scheduler.spt(p))),
      "NEH": int(scheduler.makespan(p, scheduler.neh(p)))}
_, ms["NEH + IG\n(우리)"] = scheduler.best_schedule(1, 282, 30, "P1")
fig, ax = plt.subplots(figsize=(7, 3.4))
bars = ax.bar(list(ms), list(ms.values()), color=["#c9c9c9", "#9aa5b1", "#2f6db5"], width=0.55)
for b, v in zip(bars, ms.values()):
    ax.text(b.get_x() + b.get_width() / 2, v + 400,
            f"{v:,}\n생산비 {labor_cost(v, 5_000_000) / 1e4:,.0f}만", ha="center", fontsize=9)
ax.set_ylim(0, max(ms.values()) * 1.22)
ax.set_ylabel("Makespan")
ax.set_title("P1 생산 순서별 makespan과 생산비 (화요일, 282 Job)")
fig.tight_layout()
fig.savefig(OUT / "그림2_스케줄링_비교.png", dpi=200)
print("그림2", ms)

# 그림 3: 누적 이익과 순위 추이 (대시보드 장부·순위표 기록)
hist = [("9/30", 2770, None), ("10/2", -9630, None), ("10/4", -16500, 67), ("10/5", -17600, 60),
        ("10/6", -12800, 51), ("10/7", -10100, 19), ("10/9", -12200, 22), ("10/10", -9930, 21),
        ("10/11", -7380, 17), ("10/12", -4240, 15), ("10/13", -8510, 16),
        ("10/14", -4435, 14), ("10/15", -2257, 13), ("10/16", 996, 13)]
fig, ax = plt.subplots(figsize=(7, 3.4))
ax.plot([h[0] for h in hist], [h[1] for h in hist], marker="o", color="#2f6db5")
ax.axhline(0, color="#999", lw=0.8)
ax.axvspan(-0.3, 1.5, color="#f3d6d6", alpha=0.6, label="Auto 운영 구간")
for i, (_, v, r) in enumerate(hist):
    if r:
        ax.annotate(f"{r}위", (i, v), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
ax.set_ylabel("누적 이익 (만 원)")
ax.set_title("누적 이익과 순위 추이 (R2602B, 72팀)")
ax.legend(frameon=False, loc="lower right")
fig.tight_layout()
fig.savefig(OUT / "그림3_누적이익_추이.png", dpi=200)


# 그림 4: 수요예측 순위 vs 이익 순위 (Ranks 페이지 조회, 10/4 이후)
def ranks(kind: str, start: str, end: str = "2026-10-16") -> dict:
    body = urllib.parse.urlencode(dict(start_date=start, end_date=end, university="")).encode()
    html = urllib.request.urlopen(f"{BASE}/iog_rank/{kind}", body, timeout=90).read().decode("utf-8")
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S):
        c = [re.sub(r"<[^>]+>|\s+", " ", t).strip() for t in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
        if len(c) >= 3:
            out.setdefault(c[2], int(c[0]))
    return out


prof, dem = ranks("total_profit", "2026-09-27"), ranks("demand", "2026-10-04")
teams = [t for t in prof if t in dem]
xs, ys = np.array([prof[t] for t in teams]), np.array([dem[t] for t in teams])
rho = np.corrcoef(xs, ys)[0, 1]
fig, ax = plt.subplots(figsize=(5.2, 4.2))
ax.scatter(xs, ys, s=14, color="#9aa5b1")
me = teams.index("26_DKU_RM")
ax.scatter([xs[me]], [ys[me]], s=40, color="#d9534f", zorder=3)
ax.annotate("우리", (xs[me], ys[me]), textcoords="offset points", xytext=(8, -4), color="#d9534f")
ax.set_xlabel("이익(Balance) 순위")
ax.set_ylabel("수요예측 정확도 순위 (10/4~)")
ax.set_title(f"수요예측 순위와 이익 순위 (72팀, ρ = {rho:.2f})")
ax.invert_xaxis()
ax.invert_yaxis()
fig.tight_layout()
fig.savefig(OUT / "그림4_예측순위_vs_이익순위.png", dpi=200)
print(f"그림4 rho={rho:.3f}, n={len(teams)}")
print("저장:", OUT)
