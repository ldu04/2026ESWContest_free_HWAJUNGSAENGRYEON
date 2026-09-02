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
    """H1 — 방향 추정이 참값으로 수렴하는 과정."""
    import math
    d = json.load(open(os.path.join(ROOT, "results/hw/run_205330.json"), encoding="utf-8"))
    ser = []
    for f in d["frames"]["ours"]:
        e = f.get("est") or {}
        if e.get("dir"):
            a = math.degrees(math.atan2(e["dir"][1], e["dir"][0])) % 360
            ser.append((f["t"], a))
    GT = 55.48
    xs = [p[0] for p in ser]
    ys = [p[1] for p in ser]

    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.axhspan(GT - 5, GT + 5, color=GREEN, alpha=0.07, lw=0)          # ±5° 띠
    ax.axhline(GT, color=GREEN, ls=(0, (5, 4)), lw=1.4)
    ax.text(xs[-1], GT - 1.6, "참값 55.48°", color=GREEN, fontsize=11,
            ha="right", va="top")
    ax.plot(xs, ys, color=ACCENT, lw=2.0)

    # ★ 주석은 **가로로 상단에** 둔다. 세로로 세우면 그래프를 가로질러 선을 가린다.
    ylo, yhi = ax.get_ylim()
    ax.set_ylim(ylo, yhi + 2.6)                    # 라벨 놓을 여백
    for t, lab, ha in ((894, "사망 3건 · 추정 개시", "left"),
                       (1504, "±5° 진입 · 이후 이탈 없음", "right")):
        ax.axvline(t, color=MUTED, lw=0.9, ls=":")
        ax.text(t + (12 if ha == "left" else -12), yhi + 1.6, lab,
                color=MUTED, fontsize=10.5, ha=ha, va="center")

    ax.plot([xs[-1]], [ys[-1]], "o", color=ACCENT, ms=6)
    ax.annotate("58.33°", (xs[-1], ys[-1]), textcoords="offset points",
                xytext=(-6, 12), color=ACCENT, fontsize=13, fontweight="bold", ha="right")

    ax.set_xlim(0, 1990)
    ax.set_xlabel("런 경과 시각 (초)")
    ax.set_ylabel("추정 화선 방향 (°)")
    clean(ax)
    save(fig, "chart_direction.png")
    return "사망이 쌓이며 추정 방향이 참값 55.48°로 수렴 — 최종 58.33°(오차 2.85°)"


# ══════════════════════════════════════════════════════════════════
def chart_selfheal():
    """H2 — 중계 노드를 뽑았을 때 메시가 무너졌다 되살아나는 과정."""
    f = sorted(glob.glob(os.path.join(ROOT, "results/hw/mesh_selfheal16_*_pull2.log")))[-1]
    xs, ys, pull_idx = [], [], None
    lines = open(f, "rb").readlines()
    order = 0
    for raw in lines:
        s = raw.strip()
        if s.startswith(b"# [PULL_CUE]"):
            pull_idx = order
            continue
        try:
            d = json.loads(s.decode("utf-8", "strict"))
        except Exception:
            continue
        if d.get("type") == "TOPO" and isinstance(d.get("n_peers"), int):
            xs.append(d["ms"] / 1000.0)
            ys.append(d["n_peers"])
            order = len(xs)

    t0 = xs[0]
    xs = [x - t0 for x in xs]
    pull_t = xs[pull_idx] if pull_idx is not None and pull_idx < len(xs) else None
    # 붕괴점(첫 3) 과 회복점(첫 14)
    i_col = next(i for i, v in enumerate(ys) if v <= 3 and xs[i] > (pull_t or 0))
    i_rec = next(i for i, v in enumerate(ys) if v >= 14 and i > i_col)

    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.step(xs, ys, where="post", color=ACCENT, lw=2.0)
    if pull_t is not None:
        ax.axvline(pull_t, color=INK, lw=1.6)
        ax.text(pull_t + 4, 16.6, "중계 노드 1대 제거", color=INK, fontsize=11,
                ha="left", va="top", fontweight="bold")

    for i, txt, dy in ((0, "15", 0.7), (i_col, "3", -1.5), (i_rec, "14", 0.7)):
        ax.plot([xs[i]], [ys[i]], "o", color=ACCENT, ms=6)
        ax.text(xs[i], ys[i] + dy, txt, color=ACCENT, fontsize=13,
                fontweight="bold", ha="center")

    # 붕괴~재구성 화살표
    y_a = 7.4
    ax.annotate("", xy=(xs[i_rec], y_a), xytext=(xs[i_col], y_a),
                arrowprops=dict(arrowstyle="<->", color=GREEN, lw=1.6))
    ax.text((xs[i_col] + xs[i_rec]) / 2, y_a + 0.5, "15.9초", color=GREEN,
            fontsize=13, fontweight="bold", ha="center")

    # ★ 0 으로 순간 떨어진 1샘플짜리 점이 둘 있다(뽑는 순간 · 관측 말미).
    #   **지우지 않는다** — 데이터를 손대면 안 된다. 대신 무엇인지 밝힌다.
    zeros = [(x, y) for x, y in zip(xs, ys) if y == 0]
    if zeros:
        for zx, _ in zeros:
            ax.plot([zx], [0], "o", color=FAINT, ms=5, zorder=3)
        ax.text(xs[-1], 1.5, "○ 순간값(1샘플) — 이탈 확정 전 과도상태",
                color=MUTED, fontsize=9.5, ha="right", va="bottom")

    ax.set_ylim(-0.6, 17.4)
    ax.set_yticks([0, 3, 5, 10, 14, 15])
    ax.set_xlabel("관측 경과 시각 (초)")
    ax.set_ylabel("브리지가 본 노드 수 (n_peers)")
    clean(ax)
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


if __name__ == "__main__":
    setup_font()
    print("덱용 그래프 생성 → docs/img/deck/")
    notes = [chart_direction(), chart_selfheal(), chart_leadtime()]
    print()
    for n in notes:
        print("  · " + n)
