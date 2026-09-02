"""make_deck_charts.py — 덱용 그래프 3종. **덱에 넣지는 않는다. PNG 만 만든다.**

왜 (2026-09-02)
---------------
덱의 성능 서술이 전부 글자다. 심사위원은 21쪽을 3분에 훑는데, 글자로 적힌 숫자는
「읽어야」 하고 그림은 「보면」 된다. 세 가지만 그림으로 바꾼다.

★ 색: 테마(theme1.xml)를 따르지 않는다. 테마는 PowerPoint 기본 파랑(#4472C4)인데
  **덱 본문은 전혀 다른 팔레트를 쓴다**(먹 #1F2421 · 회녹 #44483F · 주황 #D35400 ·
  초록 #2C5F2D). 테마를 따르면 덱과 겉도는 그림이 나온다. 실사용 색을 쓴다.

★ 양식: 흰 배경 · 위/오른쪽 축선 제거 · 가로 그리드만 아주 흐리게 · 제목 없음
  (제목은 슬라이드가 갖는다) · 범례 대신 선 옆 직접 라벨 · 긴 변 1600px

    python scripts/make_deck_charts.py
"""
from __future__ import annotations

import glob
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "img", "deck")

# ── 덱에서 뽑은 실사용 색 ──
INK    = "#1F2421"      # 본문 먹
BODY   = "#44483F"      # 짙은 회녹
MUTED  = "#6B6E6A"      # 보조 회색
ACCENT = "#D35400"      # 주황 — 강조
GREEN  = "#2C5F2D"      # 짙은 초록 — 참값/기준선
FAINT  = "#B9B3A6"      # 아주 흐린 색

DPI = 160               # 10 in * 160 = 1600 px


def setup_font():
    """한글 폰트 — 맑은 고딕. 마이너스 기호 깨짐 방지."""
    for name in ("Malgun Gothic", "맑은 고딕", "MalgunGothic"):
        try:
            font_manager.findfont(name, fallback_to_default=False)
            rcParams["font.family"] = name
            break
        except Exception:
            continue
    rcParams["axes.unicode_minus"] = False      # ★ '−' 가 □ 로 깨지는 것 방지
    rcParams["figure.facecolor"] = "white"
    rcParams["savefig.facecolor"] = "white"
    rcParams["text.color"] = INK
    rcParams["axes.labelcolor"] = BODY
    rcParams["xtick.color"] = MUTED
    rcParams["ytick.color"] = MUTED


def clean(ax):
    """위/오른쪽 축선 제거 · 가로 그리드만 흐리게."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(FAINT)
    ax.grid(axis="y", color=FAINT, alpha=0.35, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, labelsize=11)


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=DPI, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    from PIL import Image
    w, h = Image.open(p).size
    print("  %-24s %dx%d  %.0f KB" % (name, w, h, os.path.getsize(p) / 1024))


# ══════════════════════════════════════════════════════════════════
def chart_direction():
    """H1 — 방향 추정이 참값으로 수렴하는 과정.

    2026-09-02 재작업: ① 세로 마커 라벨 두 개가 겹쳐 글자가 뭉개졌다 → **아래로 내리고
    위아래로 엇갈려** 배치. ② x축을 이중으로 만들어 **위축에 누적 사망 건수**를 찍는다
    — 「시간이 지나서」가 아니라 「표본이 쌓여서」 수렴한다는 게 이 그림의 논지이기 때문이다.
    """
    import math
    d = json.load(open(os.path.join(ROOT, "results/hw/run_205330.json"), encoding="utf-8"))
    ser = []
    for f in d["frames"]["ours"]:
        e = f.get("est") or {}
        if e.get("dir"):
            a = math.degrees(math.atan2(e["dir"][1], e["dir"][0])) % 360
            ser.append((f["t"], a))
    # ★ 사망시각은 산출물에서 직접 뽑는다(지시서 값과 16/16 일치 확인함)
    death = {}
    for f in d["frames"]["ours"]:
        for n in f["nodes"]:
            if n.get("state") == "DEAD":
                death.setdefault(n["id"], f["t"])
    dts = sorted(death.values())

    GT = 55.48
    xs = [p[0] for p in ser]
    ys = [p[1] for p in ser]

    fig, ax = plt.subplots(figsize=(10, 5.0))
    ax.axhspan(GT - 5, GT + 5, color=GREEN, alpha=0.07, lw=0)
    ax.axhline(GT, color=GREEN, ls=(0, (5, 4)), lw=1.4)
    ax.plot(xs, ys, color=ACCENT, lw=2.0)

    XMAX = 1990
    ax.set_xlim(0, XMAX)
    # ★ y 범위를 50~68 로 고정한다. 아래를 45 까지 열어두면 곡선이 위쪽에 몰려 보인다.
    #   라벨은 축 밖이 아니라 **축 안쪽 아래 여백**(50~53)에 넣는다.
    lo, hi = 50.0, 68.0
    ax.set_ylim(lo, hi)
    ax.text(XMAX - 10, GT - 1.4, "참값 55.48°", color=GREEN, fontsize=11,
            ha="right", va="top")

    # ── 세로 마커: 라벨을 축 안쪽 아래에 엇갈려 두고, **각 세로선까지 유도선을 긋는다** ──
    #   (라벨만 나란히 두면 어느 라벨이 어느 선인지 모호하다 — 실제로 모호했다.)
    for t, lab, ly, ha, dx in (
            (894,  "추정 입력 3건 — 추정 시작", 52.4, "left", 105),
            (1504, "추정 입력 10건 — 참값 ±5° 진입, 이후 이탈 없음", 50.7, "right", -105)):
        ax.axvline(t, color=MUTED, lw=0.9, ls=":")
        ax.annotate(lab, xy=(t, ly), xytext=(t + dx, ly),
                    color=MUTED, fontsize=10.5, ha=ha, va="center",
                    arrowprops=dict(arrowstyle="-", color=FAINT, lw=0.9,
                                    shrinkA=2, shrinkB=0))

    ax.plot([xs[-1]], [ys[-1]], "o", color=ACCENT, ms=6)
    ax.annotate("58.33° (오차 2.85°)", (xs[-1], ys[-1]),
                textcoords="offset points", xytext=(-8, 44), color=ACCENT,
                fontsize=12.5, fontweight="bold", ha="right")

    ax.set_xlabel("런 경과 시각 (초)")
    ax.set_ylabel("추정 화선 방향 (°)")
    clean(ax)

    # ── 위축: 그 시각까지의 누적 사망 건수 ──
    # ★ 위축은 **추정기가 그 프레임에서 입력으로 쓴 사망 건수**다(est.n_deaths).
    #   물리적으로 죽은 노드 수가 아니다 — n03 은 증거 부족으로 추정에서 제외됐고,
    #   그래서 t=1504 에서 물리 사망은 11건이지만 추정 입력은 10건이다.
    used = []
    for f in d["frames"]["ours"]:
        e = f.get("est") or {}
        if e.get("n_deaths") is not None:
            used.append((f["t"], e["n_deaths"]))
    def t_of(k):
        for t, n in used:
            if n >= k:
                return t
        return None
    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim())
    picks = [k for k in (3, 6, 10, 15) if t_of(k) is not None]   # 13 은 뺀다(눈금 과밀)
    ax2.set_xticks([t_of(k) for k in picks])
    ax2.set_xticklabels([str(k) for k in picks])
    ax2.set_xlabel("추정에 쓰인 사망 건수 (개)", labelpad=8)
    for side in ("left", "right", "bottom"):
        ax2.spines[side].set_visible(False)
    ax2.spines["top"].set_color(FAINT)
    ax2.tick_params(length=0, labelsize=11, colors=MUTED)
    ax2.xaxis.label.set_color(BODY)

    save(fig, "chart_direction.png")
    return "사망이 쌓이며 추정 방향이 참값 55.48°로 수렴 — 최종 58.33°(오차 2.85°)"


# ══════════════════════════════════════════════════════════════════
def chart_selfheal():
    """H2 — 중계 노드를 뽑았을 때 메시가 무너졌다 되살아나는 과정.

    2026-09-02 재작업: ① n_peers=0 인 **1샘플 과도값 2개를 선에서 뺀다** — 선이 0까지
    내려가면 「메시가 통째로 죽었다」로 읽힌다(실제로는 이탈 확정 전 순간값이다).
    데이터를 지우는 게 아니라 **회색 X 로 따로 찍고 캡션으로 밝힌다.**
    ② y 눈금은 0·5·10·15 만. 3·14 는 데이터 라벨로만.
    ③ 15.9초 화살표를 붕괴~재구성 **실제 구간에 유도선으로 붙인다**(공중에 뜨지 않게).
    """
    f = sorted(glob.glob(os.path.join(ROOT, "results/hw/mesh_selfheal16_*_pull2.log")))[-1]
    xs, ys, pull_idx = [], [], None
    order = 0
    for raw in open(f, "rb").readlines():
        t = raw.strip()
        if t.startswith(b"# [PULL_CUE]"):
            pull_idx = order
            continue
        try:
            d = json.loads(t.decode("utf-8", "strict"))
        except Exception:
            continue
        if d.get("type") == "TOPO" and isinstance(d.get("n_peers"), int):
            xs.append(d["ms"] / 1000.0)
            ys.append(d["n_peers"])
            order = len(xs)

    t0 = xs[0]
    xs = [x - t0 for x in xs]
    pull_t = xs[pull_idx] if pull_idx is not None and pull_idx < len(xs) else None
    i_col = next(i for i, v in enumerate(ys) if 0 < v <= 3 and xs[i] > (pull_t or 0))
    i_rec = next(i for i, v in enumerate(ys) if v >= 14 and i > i_col)

    # ★ 0 표본은 **선에서 뺀다.** 지우는 게 아니라 따로 찍는다.
    keep = [(x, y) for x, y in zip(xs, ys) if y > 0]
    zx = [x for x, y in zip(xs, ys) if y == 0]
    lx = [p[0] for p in keep]
    ly = [p[1] for p in keep]

    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.step(lx, ly, where="post", color=ACCENT, lw=2.0)

    if pull_t is not None:
        ax.axvline(pull_t, color=INK, lw=1.6)
        ax.text(pull_t + 4, 17.0, "중계 노드 1대 제거", color=INK, fontsize=11,
                ha="left", va="top", fontweight="bold")

    for i, txt, dy in ((0, "15", 0.6), (i_col, "3", -1.6), (i_rec, "14", 0.6)):
        ax.plot([xs[i]], [ys[i]], "o", color=ACCENT, ms=6)
        ax.text(xs[i], ys[i] + dy, txt, color=ACCENT, fontsize=13,
                fontweight="bold", ha="center")

    # ── 15.9초: 실제 구간에 **유도선으로 붙인다** ──
    xa, xb = xs[i_col], xs[i_rec]
    y_a = 8.6
    ax.plot([xa, xa], [ys[i_col] + 0.35, y_a], color=GREEN, lw=0.8, ls=":", zorder=2)
    ax.plot([xb, xb], [y_a, ys[i_rec] - 0.35], color=GREEN, lw=0.8, ls=":", zorder=2)
    ax.annotate("", xy=(xb, y_a), xytext=(xa, y_a),
                arrowprops=dict(arrowstyle="<->", color=GREEN, lw=1.6))
    # ★ 라벨은 화살표 **왼쪽 바깥**에 둔다. 가운데 두면 오른쪽 유도선과 겹친다(실제로 겹쳤다).
    ax.text(xa - 3, y_a, "15.9초", color=GREEN,
            fontsize=13, fontweight="bold", ha="right", va="center")

    # ── 0 표본: 작은 회색 X + 축 밖 캡션 ──
    if zx:
        ax.plot(zx, [0] * len(zx), "x", color=MUTED, ms=7, mew=1.6, zorder=3)
    # ★ 꼬리 절단: 재구성 이후 평탄구간은 시험과 무관하다. 다만 **두 번째 0 표본(t≈176)까지는
    #   남겨야** 한다 — 「0 이 두 번 있었다」를 감추면 그게 은폐다. 그래서 182 초에서 자른다.
    x_cut = max(zx) + 6 if zx else xs[-1] + 4
    ax.set_xlim(-4, x_cut)
    ax.set_ylim(-1.1, 17.8)
    ax.set_yticks([0, 5, 10, 15])
    ax.set_xlabel("관측 경과 시각 (초)")
    ax.set_ylabel("브리지가 본 노드 수 (n_peers)")
    clean(ax)
    fig.text(0.5, -0.02, "× 이탈 확정 전 1샘플 과도값 (선에서 제외)",
             color=MUTED, fontsize=9.5, ha="center")
    save(fig, "chart_selfheal.png")
    return "중계 노드 1대 제거 → peers 15→3 붕괴 → 15.9초 만에 14로 재구성 (재부팅 없음)"


# ══════════════════════════════════════════════════════════════════
def chart_leadtime():
    """H3 — 노드별 「죽기 몇 초 전에 경보를 받았나」. 못 받은 3대도 행으로 남긴다."""
    d = json.load(open(os.path.join(ROOT, "results/hw/run_205330.json"), encoding="utf-8"))
    first_alert, death = {}, {}
    for f in d["frames"]["ours"]:
        t = f["t"]
        for a in (f.get("est") or {}).get("alerts") or []:
            first_alert.setdefault(a["id"], t)
        for n in f["nodes"]:
            if n.get("state") == "DEAD":
                death.setdefault(n["id"], t)

    rows = []
    for i in range(16):
        lead = None
        if i in first_alert and i in death and death[i] > first_alert[i]:
            lead = death[i] - first_alert[i]
        rows.append(("n%02d" % (i + 1), lead))
    # 리드타임 긴 순 → 없는 것은 맨 아래
    rows.sort(key=lambda r: (r[1] is None, -(r[1] or 0)))
    labels = [r[0] for r in rows]
    vals = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(10, 5.4))
    ypos = range(len(rows))
    for y, (lab, v) in zip(ypos, rows):
        if v is None:
            ax.text(8, y, "경보 없음 — 화선이 먼저 닿은 노드", color=MUTED,
                    fontsize=10, va="center")
        else:
            ax.barh(y, v, color=ACCENT, height=0.62)
            ax.text(v + 9, y, "%d초" % round(v), color=BODY, fontsize=10, va="center")

    med = 344
    ax.axvline(med, color=GREEN, ls=(0, (5, 4)), lw=1.4)
    # ★ 라벨을 **맨 위**에 둔다. 아래에 두면 x축 눈금·축이름과 겹친다(실제로 겹쳤다).
    ax.text(med + 8, -0.75, "중앙 344초", color=GREEN, fontsize=11.5,
            va="center", fontweight="bold")

    ax.set_yticks(list(ypos))
    ax.set_yticklabels(labels, fontsize=11)
    ax.set_xlim(0, 620)
    ax.set_ylim(len(rows) - 0.4, -1.3)   # 상단 라벨 자리
    ax.set_xlabel("사망 몇 초 전에 경보를 받았나 (초)")
    clean(ax)
    ax.grid(axis="x", color=FAINT, alpha=0.35, linewidth=0.7)
    ax.grid(axis="y", visible=False)
    save(fig, "chart_leadtime.png")
    return "13/16 노드가 사망 전 경보 수신(중앙 344초). 못 받은 3대도 행으로 남겨 13/16 이 보이게"


# ══════════════════════════════════════════════════════════════════
def chart_selfheal_band():
    """H2-띠 — s10 하단 띠(폭 7.6 in × 높이 1.2 in)에 넣을 **가로로 긴** 판본.

    왜 따로 만드나(2026-09-02): s10 의 빈 자리는 **높이 1.55 in 짜리 하단 띠뿐**이다.
    본 판본(가로세로비 1.9)을 그 높이에 맞추면 폭이 2.4 in 로 줄어 글자를 못 읽는다.
    그림을 줄이는 대신 **띠에 맞는 비율로 다시 그린다.** 데이터는 같다.
    """
    f = sorted(glob.glob(os.path.join(ROOT, "results/hw/mesh_selfheal16_*_pull2.log")))[-1]
    xs, ys, pull_idx, order = [], [], None, 0
    for raw in open(f, "rb").readlines():
        t = raw.strip()
        if t.startswith(b"# [PULL_CUE]"):
            pull_idx = order
            continue
        try:
            d = json.loads(t.decode("utf-8", "strict"))
        except Exception:
            continue
        if d.get("type") == "TOPO" and isinstance(d.get("n_peers"), int):
            xs.append(d["ms"] / 1000.0)
            ys.append(d["n_peers"])
            order = len(xs)
    t0 = xs[0]
    xs = [x - t0 for x in xs]
    pull_t = xs[pull_idx]
    i_col = next(i for i, v in enumerate(ys) if 0 < v <= 3 and xs[i] > pull_t)
    i_rec = next(i for i, v in enumerate(ys) if v >= 14 and i > i_col)
    keep = [(x, y) for x, y in zip(xs, ys) if y > 0]
    zx = [x for x, y in zip(xs, ys) if y == 0]

    fig, ax = plt.subplots(figsize=(12.6, 2.0))
    ax.step([p[0] for p in keep], [p[1] for p in keep], where="post", color=ACCENT, lw=2.2)
    ax.axvline(pull_t, color=INK, lw=1.6)
    ax.text(pull_t + 3, 17.4, "중계 노드 1대 제거", color=INK, fontsize=12,
            ha="left", va="top", fontweight="bold")
    for i, txt, dy in ((0, "15", 0.9), (i_col, "3", -2.4), (i_rec, "14", 0.9)):
        ax.plot([xs[i]], [ys[i]], "o", color=ACCENT, ms=6)
        ax.text(xs[i], ys[i] + dy, txt, color=ACCENT, fontsize=13,
                fontweight="bold", ha="center")
    xa, xb, y_a = xs[i_col], xs[i_rec], 8.6
    ax.plot([xb, xb], [y_a, ys[i_rec] - 0.5], color=GREEN, lw=0.8, ls=":")
    ax.annotate("", xy=(xb, y_a), xytext=(xa, y_a),
                arrowprops=dict(arrowstyle="<->", color=GREEN, lw=1.6))
    ax.text(xa - 3, y_a, "15.9초", color=GREEN, fontsize=13,
            fontweight="bold", ha="right", va="center")
    if zx:
        ax.plot(zx, [0] * len(zx), "x", color=MUTED, ms=7, mew=1.6)
    ax.set_xlim(-4, max(zx) + 6 if zx else xs[-1] + 4)
    ax.set_ylim(-1.6, 18.6)
    ax.set_yticks([0, 5, 10, 15])
    ax.set_xlabel("관측 경과 시각 (초)", fontsize=11)
    ax.set_ylabel("n_peers", fontsize=11)
    clean(ax)
    save(fig, "chart_selfheal_band.png")
    return "s10 하단 띠용 가로 판본"


if __name__ == "__main__":
    setup_font()
    print("덱용 그래프 생성 → docs/img/deck/")
    notes = [chart_direction(), chart_selfheal(), chart_leadtime(), chart_selfheal_band()]
    print()
    for n in notes:
        print("  · " + n)
