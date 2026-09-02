"""animate.py — matplotlib로 스냅샷 스트림 렌더 (지시서 #1 §9, 1차 시각화).

코어와 분리: 이 파일은 Snapshot(dict) 리스트만 소비한다(같은 데이터를 후속 웹 대시보드도 소비).
  - 노드: ALIVE=초록, DYING=주황, DEAD=검정, Sink=파랑 사각.
  - 링크: 옅은 회색, 현재 라우팅 경로는 굵게 강조(자가치유가 눈에 보이게).
  - 화선: ground-truth 전선(점선) + 추정 방향 화살표(실선) 겹침.
  - 대피경보 노드: 빨강 테두리.
  - 상단 HUD: t, 전달률, 재라우팅 지연, 방향/속도 추정오차.
"""
from __future__ import annotations

import math
import numpy as np


STATE_COLOR = {"ALIVE": "#2ca02c", "DYING": "#ff7f0e", "DEAD": "#111111"}


def _positions(snapshots):
    pts = np.array([nd["pos"] for nd in snapshots[0]["nodes"]])
    return pts


def _bounds(pts, pad=8.0):
    xmin, ymin = pts.min(axis=0) - pad
    xmax, ymax = pts.max(axis=0) + pad
    return xmin, xmax, ymin, ymax


def render(snapshots, cfg, save_path: str | None = None, show: bool = False, fps: int = 10):
    """스냅샷 리스트를 애니메이션으로 렌더. save_path가 있으면 파일 저장, show면 창 표시."""
    import matplotlib
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    # 한글 HUD가 깨지지 않도록 한국어 지원 폰트 폴백(Windows: Malgun Gothic).
    from matplotlib import font_manager
    available = {f.name for f in font_manager.fontManager.ttflist}
    for fam in ("Malgun Gothic", "NanumGothic", "AppleGothic", "Noto Sans CJK KR"):
        if fam in available:
            plt.rcParams["font.family"] = fam
            break
    plt.rcParams["axes.unicode_minus"] = False

    pts = _positions(snapshots)
    xmin, xmax, ymin, ymax = _bounds(pts)
    by_id_pos = {nd["id"]: nd["pos"] for nd in snapshots[0]["nodes"]}

    fig, ax = plt.subplots(figsize=(8, 8))

    def draw(frame_idx):
        ax.clear()
        snap = snapshots[frame_idx]
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_aspect("equal")
        ax.set_facecolor("#fafafa")

        topo = snap["topology"]
        # 전체 링크(옅게)
        for u, v in topo["links"]:
            x = [by_id_pos[u][0], by_id_pos[v][0]]
            y = [by_id_pos[u][1], by_id_pos[v][1]]
            ax.plot(x, y, color="#dddddd", lw=0.8, zorder=1)
        # 현재 라우팅 트리(강조)
        for u, v in topo["route_edges"]:
            x = [by_id_pos[u][0], by_id_pos[v][0]]
            y = [by_id_pos[u][1], by_id_pos[v][1]]
            ax.plot(x, y, color="#1f77b4", lw=1.8, alpha=0.7, zorder=2)

        # 대피경보 노드 id
        alert_ids = set()
        if snap["est"]:
            alert_ids = {a["id"] for a in snap["est"]["alerts"]}

        # 노드
        for nd in snap["nodes"]:
            x, y = nd["pos"]
            if nd["is_sink"]:
                ax.scatter([x], [y], marker="s", s=160, c="#1f77b4",
                           edgecolors="k", zorder=5)
                ax.text(x, y + 1.5, "SINK", ha="center", fontsize=8)
                continue
            c = STATE_COLOR.get(nd["state"], "#888888")
            edge = "red" if nd["id"] in alert_ids else "k"
            lw = 2.2 if nd["id"] in alert_ids else 0.6
            ax.scatter([x], [y], s=110, c=c, edgecolors=edge, linewidths=lw, zorder=4)

        # ground-truth 전선(점선): front_pos를 지나고 n에 수직인 직선
        n = np.array(snap["fire_dir"])
        perp = np.array([-n[1], n[0]])
        fp = np.array(snap["fire_front"])
        L = max(xmax - xmin, ymax - ymin)
        a = fp - perp * L
        b = fp + perp * L
        ax.plot([a[0], b[0]], [a[1], b[1]], "r--", lw=1.5, alpha=0.7,
                zorder=3, label="ground-truth 전선")

        # 추정 방향 화살표(실선)
        if snap["est"] and snap["est"]["dir"] is not None and snap["est"]["front_point"]:
            d = np.array(snap["est"]["dir"])
            c0 = np.array(snap["est"]["front_point"])
            ax.arrow(c0[0], c0[1], d[0] * 10, d[1] * 10, head_width=2.0,
                     head_length=2.5, fc="darkgreen", ec="darkgreen",
                     lw=2, zorder=6, length_includes_head=True)

        # HUD
        hud = snap["hud"]
        de = hud.get("dir_err_deg")
        se = hud.get("speed_err_pct")
        dr = hud.get("delivery_rate")
        txt = (f"t={snap['t']:.1f}s   전달률={dr*100:.0f}%   "
               f"방향오차={de if de is not None else '—'}°   "
               f"속도오차={se if se is not None else '—'}%   "
               f"사망={hud.get('n_dead', 0)}  경보={hud.get('n_alerts', 0)}")
        ax.set_title(txt, fontsize=10)

    anim = FuncAnimation(fig, draw, frames=len(snapshots), interval=1000 / fps)

    if save_path:
        _save(anim, save_path, fps)
        print(f"[viz] saved → {save_path}")
    if show:
        import matplotlib.pyplot as plt
        plt.show()
    return anim


def _save(anim, save_path: str, fps: int):
    import os
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    if save_path.lower().endswith(".gif"):
        try:
            from matplotlib.animation import PillowWriter
            anim.save(save_path, writer=PillowWriter(fps=fps))
            return
        except Exception as e:  # pragma: no cover
            print(f"[viz] gif 저장 실패({e}), mp4로 시도")
    try:
        anim.save(save_path, fps=fps)
    except Exception as e:  # pragma: no cover
        # ffmpeg 없을 때: 마지막 프레임 PNG로 폴백
        png = save_path.rsplit(".", 1)[0] + "_last.png"
        anim._fig.savefig(png, dpi=110)
        print(f"[viz] 동영상 저장기 없음({e}) → 마지막 프레임 PNG 저장: {png}")
