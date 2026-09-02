"""run_2l_b.py — 2.L §4 · **타원 전선** 곡률 정량화 + 추정 성능.

왜: 현재 곡률 케이스(S2a10/S2a20)는 **인위적으로 만든 것**이다. S2a20은 τ=0에서도 방향오차
10.58°인데([D-047]), 이게 τ가 아니라 **평면 적합의 곡률 한계**다. 문제는 **실제 산불 전선이
그만큼 굽는지를 우리가 모른다**는 것 — 안 굽으면 무시해도 될 한계고, 그만큼 굽으면 진짜 구멍이다.

★ 범위 한정: 물리 확산 모델(Rothermel 계열)은 **하지 않는다.** 연료·수분·지형 가정이 무더기로
  들어가고 "그 화재 모델은 검증했냐"가 τ 곡선 때처럼 되돌아온다. **문헌에 정착된 형상 모델만** 쓴다.

═══════════════════════════════════════════════════════════════════════════════
문헌 (4-1, 구현 전 확인 완료)
═══════════════════════════════════════════════════════════════════════════════
 · Alexander, M.E. (1985) "Estimating the length-to-breadth ratio of elliptical forest fire
   patterns", Proc. 8th Conf. Fire and Forest Meteorology, 287-304.
     **L/B = 1.0 + 0.00120·W^2.154**  (W = 10 m 개활지 풍속 km/h, 적용상한 50 km/h → L/B ≈ 6.5)
     관측 18건과 r = 0.865. 우리 구현에서 W=50 → L/B=6.480 으로 재현됨(검산 완료).
 · 발화점 위치: **타원의 뒤쪽 초점(rear focus)** — Alexander(1985) 이래의 표준 가정.
     ※ FARSITE 기술문서는 "초점을 발화점으로 쓰면 **후미(backing) 확산을 과소예측**할 수 있다"는
       이견도 함께 적고 있다. 우리는 표준 가정을 따르되 이 한계를 명시한다.
 · 타원 형상 자체의 계보: Peet(1965), McArthur(1966), Van Wagner(1969) → Anderson et al.(1982),
   Alexander(1985). 이중타원·렘니스케이트·물방울 등 대안도 있으나(Richards 1995),
   **단순 타원이 장시간 자유 확산을 충분히 기술**한다는 것이 정착된 평가다.
 · FARSITE/FlamMap은 Alexander가 아니라 **Anderson(1983)** 식을 쓴다(midflame wind를 쓰기 때문).
   우리는 풍속을 10 m 개활지 기준으로 다루므로 Alexander 쪽이 맞다.
 ⚠ **Cowork 기억과의 대조:** "바람이 있으면 대략 타원, 발화점은 초점 근처" — **문헌과 일치**했다.
   기억이 틀린 부분은 없었다. 다만 **정확한 회귀식과 적용상한(50 km/h)은 기억에 없던 정보**다.

★ 강령: `sim/estimator.py` 불변. `fire_shape="line"`이면 기존과 **비트 동일**(회귀로 확인).
  결론 문장 없음 — 원자료·곡률표·플래그만.

★ 핵심 산출물(4-3): 타원 전선의 **노드 스케일 곡률**을 S2a10/S2a20과 **같은 척도**로 비교.
  척도 = **도착시각 등시선(isochrone)의 곡률 κ × 노드간격 h** (= 노드 한 칸 지나는 동안 전선
  법선이 도는 각, 라디안). 이게 평면 적합이 실제로 겪는 양이다. 부위별(선단/측면)로 낸다.
"""
import argparse
import csv
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sim.config import Config
from sim.engine import Engine
from sim.fire import Fire
from sim.metrics import angle_deg
from scripts.run_2e3_diagnose import TrueFront
from scripts._par import pmap, n_workers

OUTDIR = os.path.join("results", "stress")

TAUS = (0.0, 11.0, 78.5)                    # 지시서 최소 요건
WINDS_KMH = (10.0, 20.0, 30.0, 50.0)        # Alexander 적용범위 안
IGNITION_D = (30.0, 60.0, 120.0)            # 격자 가장자리에서 발화점까지 거리(m)
# ★ 지시서 4-3: "곡률은 부위(선단 vs 측면)마다 다르므로 부위별로 낼 것.
#   노드 격자가 전선의 **측면**을 지나는 경우가 최악일 수 있음."
#   → 발화점을 격자 **풍상축**에 두면 격자는 선단 영역에만 놓인다(측면 표본 0개).
#     측면을 재려면 발화점을 **가로로** 물려 격자가 타원 옆구리를 지나게 해야 한다.
GEOMS = ("head", "flank")
BASELINES = [                                # 대조군(기존)
    ("straight_S1",  {}),
    ("curved_S2a10", {"wind_noise_deg": 10.0}),
    ("curved_S2a20", {"wind_noise_deg": 20.0}),
]


# ───────────────────── 공통 곡률 척도 ─────────────────────
def isochrone_curvature(T_at, p, h=1.0):
    """도착시각장 T의 **등시선 곡률** κ = div(∇T/|∇T|) (중심차분).

    κ > 0 = 전선이 진행방향으로 볼록(선단형), κ < 0 = 오목.
    반환 단위 1/m. κ·(노드간격)이 '노드 한 칸당 법선 회전각(rad)'.
    """
    x, y = float(p[0]), float(p[1])
    f = lambda a, b: T_at((a, b))
    Tx = (f(x + h, y) - f(x - h, y)) / (2 * h)
    Ty = (f(x, y + h) - f(x, y - h)) / (2 * h)
    Txx = (f(x + h, y) - 2 * f(x, y) + f(x - h, y)) / (h * h)
    Tyy = (f(x, y + h) - 2 * f(x, y) + f(x, y - h)) / (h * h)
    Txy = (f(x + h, y + h) - f(x + h, y - h) - f(x - h, y + h) + f(x - h, y - h)) / (4 * h * h)
    g2 = Tx * Tx + Ty * Ty
    if g2 < 1e-18:
        return None
    return float((Txx * Ty * Ty - 2 * Tx * Ty * Txy + Tyy * Tx * Tx) / (g2 ** 1.5))


def grid_positions(cfg):
    return [(c * cfg.spacing_m, r * cfg.spacing_m)
            for r in range(cfg.grid_rows) for c in range(cfg.grid_cols)]


def ellipse_cfg(wind_kmh, ign_d, geom="head", tau=0.0, seed=1, t_max=None):
    """타원 전선 Config.

    geom="head"  : 발화점을 격자 **풍상축**으로 ign_d 물림 → 격자가 타원 **선단**을 지난다.
    geom="flank" : 발화점을 격자 **가로**로 ign_d 물림   → 격자가 타원 **옆구리**를 지난다.
    """
    base = Config()
    n = np.array(base.direction())
    m = np.array([-n[1], n[0]])                     # 풍향 수직
    pts = np.array(grid_positions(base))
    if geom == "head":
        anchor = pts[int(np.argmin(pts @ n))]       # 진행방향 투영 최소 노드
        start = tuple(anchor - n * ign_d)
    else:
        anchor = pts[int(np.argmin(pts @ m))]       # 가로방향 최소 노드
        # 가로로 물리고, 풍하로도 격자 중앙쯤 오게 축을 맞춘다(옆구리가 격자를 지나도록)
        start = tuple(anchor - m * ign_d - n * float(np.ptp(pts @ n)) * 0.5)
    kw = dict(mode="ours", seed=seed, fire_shape="ellipse", wind_kmh=wind_kmh,
              fire_start=start, sensor_tau_s=tau)
    if t_max is not None:
        kw["t_max"] = t_max
    return Config(**kw)


def plan_tmax(wind_kmh, ign_d, geom="head"):
    """모든 노드가 실제로 도달될 만큼 t_max를 잡는다(절단 아티팩트 방지, 2.J-A와 같은 취지)."""
    cfg = ellipse_cfg(wind_kmh, ign_d, geom=geom, t_max=1e6)
    fire = Fire(cfg, None)
    ts = [fire.T_true(p) for p in grid_positions(cfg)]
    return float(max(ts)) * 1.15 + 20.0


def robust_kh(ks, h):
    """|κ|·h 의 **중앙값·P95**. 평균은 |∇T|≈0 부근의 폭주에 오염되므로 쓰지 않는다.

    (초판이 실제로 그렇게 오염됐다: S2a20 평균 0.855 > P95 0.178 이라는 모순이 나왔다.)
    """
    a = np.abs(np.asarray([k for k in ks if k is not None and np.isfinite(k)], dtype=float))
    if a.size == 0:
        return None, None, 0
    return (round(float(np.median(a)) * h, 4), round(float(np.percentile(a, 95)) * h, 4), a.size)


# ───────────────────── 4-3 곡률 ─────────────────────
def curvature_rows():
    base = Config()
    h = base.spacing_m
    rows = []

    # (a) 타원 — 기하(선단/측면) × 풍속 × 발화거리
    for geom in GEOMS:
        for w in WINDS_KMH:
            for d in IGNITION_D:
                cfg = ellipse_cfg(w, d, geom=geom, t_max=1e6)
                fire = Fire(cfg, None)
                n = np.array(cfg.direction())
                recs = []
                for p in grid_positions(cfg):
                    k = isochrone_curvature(fire.T_true, p, h=0.5)
                    if k is None or not np.isfinite(k):
                        continue
                    v = np.array(p) - fire.start
                    r = float(np.linalg.norm(v))
                    ang = (math.degrees(math.acos(np.clip(float(v @ n) / r, -1, 1)))
                           if r > 1e-9 else 0.0)
                    recs.append((ang, k))
                med, p95, n_all = robust_kh([k for _a, k in recs], h)
                hmed, _hp, n_h = robust_kh([k for a, k in recs if a <= 45.0], h)
                fmed, _fp, n_f = robust_kh([k for a, k in recs if a > 45.0], h)
                rows.append({
                    "model": "ellipse", "geom": geom, "wind_kmh": w,
                    "LB": round(cfg.lb_ratio(), 3), "ignition_d_m": d,
                    "kappa_h_med": med, "kappa_h_p95": p95,
                    "kappa_h_head": hmed, "kappa_h_flank": fmed,
                    "n_all": n_all, "n_head": n_h, "n_flank": n_f})

    # (b) 대조군: 직선/요동 — 등시선 곡률을 **같은 방법**으로 잰다.
    #     주의: 이 모델은 매 순간 전선이 '직선'이지만 법선이 시간에 따라 돌기 때문에
    #     도착시각장의 등시선은 굽는다. 평면 적합이 겪는 건 후자다.
    for name, ov in BASELINES:
        ks = []
        for seed in range(1, 31):
            cfg = Config(mode="ours", seed=seed, **ov)
            eng = Engine(cfg)
            for _ in eng.stream():
                pass
            tf = TrueFront(eng.fire)

            def T_at(p, _tf=tf):
                v = _tf.arrival(p)
                return v if v is not None else float("nan")

            for p in grid_positions(cfg):
                k = isochrone_curvature(T_at, p, h=0.5)
                if k is not None and np.isfinite(k):
                    ks.append(k)
        med, p95, n_all = robust_kh(ks, h)
        rows.append({"model": name, "geom": "-", "wind_kmh": None, "LB": None,
                     "ignition_d_m": None, "kappa_h_med": med, "kappa_h_p95": p95,
                     "kappa_h_head": None, "kappa_h_flank": None,
                     "n_all": n_all, "n_head": 0, "n_flank": 0})
    return rows


# ───────────────────── 4-4 추정 성능 ─────────────────────
def job(a):
    kind, key, tau, seed = a
    if kind == "ellipse":
        w, d, geom = key
        cfg = ellipse_cfg(w, d, geom=geom, tau=tau, seed=seed,
                          t_max=plan_tmax(w, d, geom))
    else:
        cfg = Config(mode="ours", seed=seed, sensor_tau_s=tau, t_max=400.0, **dict(key))
    eng = Engine(cfg)
    for _ in eng.stream():
        pass

    n_ns = sum(1 for nd in eng.nodes if not nd.is_sink)
    n_died = sum(1 for nd in eng.nodes if (not nd.is_sink) and nd.death_t is not None)
    est_dir = eng.estimator.dir_global
    est_sp = eng.estimator.speed_global

    # 참값 기준 두 가지 — 곡선 전선에서는 '명목'과 '국소 참'이 다르다(둘 다 낸다)
    dir_nom = angle_deg(est_dir, cfg.direction()) if est_dir else None
    dir_loc = sp_true_loc = None
    if kind == "ellipse" and est_dir:
        dv, sv = [], []
        for nd in eng.nodes:
            if nd.is_sink or nd.death_t is None:
                continue
            g = eng.fire._ellipse_gradT(nd.pos)
            ng = float(np.linalg.norm(g))
            if ng > 1e-12:
                dv.append(g / ng)
                sv.append(1.0 / ng)
        if dv:
            m = np.mean(dv, axis=0)
            if float(np.linalg.norm(m)) > 1e-9:
                dir_loc = angle_deg(est_dir, tuple(m / np.linalg.norm(m)))
            sp_true_loc = float(np.mean(sv))
    return {"dir_err_nominal": dir_nom, "dir_err_local": dir_loc,
            "speed_est": est_sp,
            "speed_err_nominal_pct": ((est_sp - cfg.speed_true) / cfg.speed_true * 100.0)
                                     if est_sp else None,
            "speed_err_local_pct": ((est_sp - sp_true_loc) / sp_true_loc * 100.0)
                                   if (est_sp and sp_true_loc) else None,
            "speed_true_local": sp_true_loc,
            "estimable": 1 if est_dir else 0,
            "n_nonsink": n_ns, "n_died": n_died, "t_max": cfg.t_max}


def write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  [csv] {path} ({len(rows)} rows)", flush=True)


def plot(curv, perf, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    avail = {f.name for f in font_manager.fontManager.ttflist}
    for fam in ("Malgun Gothic", "NanumGothic", "AppleGothic", "Noto Sans CJK KR"):
        if fam in avail:
            plt.rcParams["font.family"] = fam
            break
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(1, 3, figsize=(17.0, 5.0))

    ax = axes[0]                      # 타원 형상
    base = Config()
    for w in WINDS_KMH:
        cfg = ellipse_cfg(w, 60.0, geom="head", t_max=1e6)
        k = cfg.lb_ratio()
        a, b = 1.0, 1.0 / k
        c = math.sqrt(max(0.0, 1 - 1 / k ** 2))
        th = np.linspace(0, 2 * np.pi, 400)
        n = np.array(cfg.direction()); m = np.array([-n[1], n[0]])
        pts = np.array([cfg.fire_start + (c + a * math.cos(t)) * n * 60 + b * math.sin(t) * m * 60
                        for t in th])
        ax.plot(pts[:, 0], pts[:, 1], lw=1.8, label=f"W={w:.0f} km/h  L/B={k:.2f}")
    ax.plot(*zip(*grid_positions(base)), "ks", ms=5, label="노드 4×4")
    ax.plot(*cfg.fire_start, "r*", ms=14, label="발화점(뒤쪽 초점)")
    ax.set_aspect("equal"); ax.grid(alpha=0.3); ax.legend(fontsize=7)
    ax.set_title("(a) Alexander(1985) 타원 · 발화점 60 m", fontsize=11)

    ax = axes[1]                      # 곡률 비교
    for d, mk in zip(IGNITION_D, ("o", "s", "^")):
        for g, ls in (("head", "-"), ("flank", "--")):
            s = sorted([r for r in curv if r["model"] == "ellipse" and r["ignition_d_m"] == d
                        and r["geom"] == g and r["kappa_h_med"] is not None],
                       key=lambda r: r["LB"])
            if s:
                ax.plot([r["LB"] for r in s], [r["kappa_h_med"] for r in s], ls + mk,
                        lw=1.7, label=f"타원 {g} (발화 {d:.0f} m)")
    for name, col in (("curved_S2a10", "#2980b9"), ("curved_S2a20", "#c0392b"),
                      ("straight_S1", "#7f8c8d")):
        r = next((x for x in curv if x["model"] == name), None)
        if r:
            ax.axhline(r["kappa_h_med"], color=col, ls=":", lw=1.8,
                       label=f"{name} (중앙값 |κ·h|)")
    ax.set_yscale("log")
    ax.set_xlabel("장단축비 L/B"); ax.set_ylabel("|κ·h|  (노드 한 칸당 법선 회전, rad)")
    ax.set_title("(b) ★ 노드 스케일 곡률 — 같은 척도 비교", fontsize=11)
    ax.grid(alpha=0.3, which="both"); ax.legend(fontsize=6.5)

    ax = axes[2]                      # 방향오차
    for d, mk in zip(IGNITION_D, ("o", "s", "^")):
        for tau, ls in ((0.0, "-"), (78.5, "--")):
            s = sorted([r for r in perf if r["model"] == "ellipse" and r["ignition_d_m"] == d
                        and r["geom"] == "head" and r["tau_s"] == tau
                        and r["dir_err_local_mean"] is not None], key=lambda r: r["LB"])
            if s:
                ax.plot([r["LB"] for r in s], [r["dir_err_local_mean"] for r in s], ls + mk,
                        lw=1.6, label=f"head 발화{d:.0f}m τ={tau:.0f}")
    for name, col in (("curved_S2a20", "#c0392b"), ("curved_S2a10", "#2980b9")):
        r = next((x for x in perf if x["model"] == name and x["tau_s"] == 0.0), None)
        if r:
            ax.axhline(r["dir_err_nominal_mean"], color=col, ls=":", lw=1.8,
                       label=f"{name} τ=0")
    ax.axhline(5.0, color="k", ls="-.", lw=1.2)
    ax.text(1.2, 5.3, "실용선 5°", fontsize=8)
    ax.set_xlabel("장단축비 L/B"); ax.set_ylabel("방향오차 (°, 국소 참 법선 대비)")
    ax.set_title("(c) 타원 전선에서의 방향오차", fontsize=11)
    ax.grid(alpha=0.3); ax.legend(fontsize=6.5)

    fig.suptitle("2.L-B  타원 전선(Alexander 1985) — 곡률 한계가 실제 문제인가", fontsize=12)
    fig.tight_layout()
    p = os.path.join(outdir, "curve_2l_b_ellipse.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    print(f"  [png] {p}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))
    W = args.workers or n_workers()
    base = Config()

    print("=" * 112)
    print("2.L §4 · 타원 전선(Alexander 1985) — 곡률 정량화 + 추정 성능")
    print("=" * 112)
    print("  L/B = 1.0 + 0.00120·W^2.154   [Alexander 1985, 적용상한 W=50 km/h]")
    print(f"  {'W(km/h)':>9s} {'L/B':>7s} {'선단:후미':>10s} {'측면속도/선단':>14s}")
    for w in WINDS_KMH:
        k = Config(wind_kmh=w).lb_ratio()
        a, b = 1.0, 1.0 / k
        c = math.sqrt(max(0.0, 1 - 1 / k ** 2))
        print(f"  {w:9.0f} {k:7.3f} {(a+c)/(a-c):9.1f}:1 {(b*b/a)/(a+c):14.4f}")
    print(f"\n  노드 4×4 · 간격 {base.spacing_m:.0f} m · 발화점 거리 {IGNITION_D} m · τ {TAUS} s")
    print(f"  시드 {args.seeds} · 워커 {W}\n")

    # ---------- 4-3 곡률 ----------
    print("  [4-3] 곡률 산출 중...", flush=True)
    curv = curvature_rows()
    write_csv(os.path.join(args.outdir, "summary_2l_b_curvature.csv"), curv)

    print("\n" + "=" * 112)
    print("★★ 4-3 핵심 — 노드 스케일 곡률 |κ·h| (노드 한 칸당 법선 회전, rad)")
    print("   같은 척도: 도착시각 등시선의 곡률 × 노드간격 10 m")
    print("=" * 112)
    print("   통계는 |κ|의 **중앙값·P95** (평균은 |∇T|≈0 부근 폭주에 오염되므로 쓰지 않는다)")
    print(f"  {'모델':14s} {'기하':7s} {'W':>5s} {'L/B':>7s} {'발화m':>7s} "
          f"{'중앙값':>9s} {'P95':>9s} {'선단':>9s} {'측면':>9s} {'n(선단/측면)':>13s}")
    fm = lambda v: (f"{v:9.4f}" if v is not None else f"{'-':>9s}")
    for r in curv:
        if r["model"] != "ellipse":
            continue
        print(f"  {'타원':14s} {r['geom']:7s} {r['wind_kmh']:5.0f} {r['LB']:7.3f} "
              f"{r['ignition_d_m']:7.0f} {fm(r['kappa_h_med'])} {fm(r['kappa_h_p95'])} "
              f"{fm(r['kappa_h_head'])} {fm(r['kappa_h_flank'])} "
              f"{str(r['n_head'])+'/'+str(r['n_flank']):>13s}")
    print("  " + "-" * 106)
    for r in curv:
        if r["model"] == "ellipse":
            continue
        print(f"  {r['model']:14s} {'-':7s} {'-':>5s} {'-':>7s} {'-':>7s} "
              f"{fm(r['kappa_h_med'])} {fm(r['kappa_h_p95'])} {'-':>9s} {'-':>9s} "
              f"{str(r['n_all']):>13s}")

    # 위치 판정
    s10 = next((r for r in curv if r["model"] == "curved_S2a10"), None)
    s20 = next((r for r in curv if r["model"] == "curved_S2a20"), None)
    if s10 and s20:
        print("\n" + "=" * 112)
        print("★★ '타원 곡률은 S2a10과 S2a20 사이 어디인가' — 수치 답 (지시서 4-3 핵심 질문)")
        print(f"   기준(중앙값 |κ·h|): S2a10 = {s10['kappa_h_med']:.4f} / "
              f"S2a20 = {s20['kappa_h_med']:.4f}   [직선 S1 = {next(r for r in curv if r['model']=='straight_S1')['kappa_h_med']:.4f}]")
        print("=" * 112)
        lo, hi = sorted([s10["kappa_h_med"], s20["kappa_h_med"]])
        print(f"  {'기하':7s} {'W':>5s} {'L/B':>7s} {'발화m':>7s} {'|κ·h| 중앙값':>13s} "
              f"{'S2a20 대비':>12s} {'위치':>22s}")
        for r in curv:
            if r["model"] != "ellipse" or r["kappa_h_med"] is None:
                continue
            v = r["kappa_h_med"]
            loc = ("S2a10보다 완만" if v < lo else
                   ("S2a10~S2a20 사이" if v <= hi else "★S2a20보다 급함"))
            print(f"  {r['geom']:7s} {r['wind_kmh']:5.0f} {r['LB']:7.3f} {r['ignition_d_m']:7.0f} "
                  f"{v:13.4f} {v/hi:11.2f}배 {loc:>22s}")

    # ---------- 4-4 성능 ----------
    print("\n  [4-4] 추정 성능 스윕 중...", flush=True)
    ell_keys = [(w, d, g) for g in GEOMS for w in WINDS_KMH for d in IGNITION_D]
    jobs = ([("ellipse", k, tau, sd) for k in ell_keys for tau in TAUS for sd in seeds] +
            [("base", tuple(ov.items()), tau, sd) for _n, ov in BASELINES
             for tau in TAUS for sd in seeds])
    print(f"    {len(jobs)} 런", flush=True)
    res = pmap(job, jobs, workers=W, label="2l-b")

    perf, raw, idx = [], [], 0
    def agg(rs, key):
        v = [r[key] for r in rs if r[key] is not None]
        return (round(float(np.mean(v)), 4), round(float(np.std(v)), 4)) if v else (None, None)

    for k in ell_keys:
        for tau in TAUS:
            rs = res[idx:idx + len(seeds)]; idx += len(seeds)
            for i, r in enumerate(rs):
                raw.append({"model": "ellipse", "geom": k[2], "wind_kmh": k[0],
                            "ignition_d_m": k[1], "tau_s": tau, "seed": seeds[i], **r})
            rec = {"model": "ellipse", "geom": k[2], "wind_kmh": k[0],
                   "LB": round(Config(wind_kmh=k[0]).lb_ratio(), 3),
                   "ignition_d_m": k[1], "tau_s": tau,
                   "estimable_pct": round(float(np.mean([r["estimable"] for r in rs])) * 100, 1),
                   "died_frac": round(float(np.mean([r["n_died"] / r["n_nonsink"] for r in rs])) * 100, 1)}
            for key in ("dir_err_nominal", "dir_err_local", "speed_err_nominal_pct",
                        "speed_err_local_pct", "speed_true_local"):
                rec[f"{key}_mean"], rec[f"{key}_std"] = agg(rs, key)
            perf.append(rec)
    for name, ov in BASELINES:
        for tau in TAUS:
            rs = res[idx:idx + len(seeds)]; idx += len(seeds)
            for i, r in enumerate(rs):
                raw.append({"model": name, "geom": "-", "tau_s": tau, "seed": seeds[i], **r})
            rec = {"model": name, "geom": "-", "wind_kmh": None, "LB": None,
                   "ignition_d_m": None, "tau_s": tau,
                   "estimable_pct": round(float(np.mean([r["estimable"] for r in rs])) * 100, 1),
                   "died_frac": round(float(np.mean([r["n_died"] / r["n_nonsink"] for r in rs])) * 100, 1)}
            for key in ("dir_err_nominal", "dir_err_local", "speed_err_nominal_pct",
                        "speed_err_local_pct", "speed_true_local"):
                rec[f"{key}_mean"], rec[f"{key}_std"] = agg(rs, key)
            perf.append(rec)
    write_csv(os.path.join(args.outdir, "raw_2l_b_ellipse.csv"), raw)
    write_csv(os.path.join(args.outdir, "summary_2l_b_ellipse.csv"), perf)
    plot(curv, perf, args.outdir)

    print("\n" + "=" * 112)
    print("★ 4-4 추정 성능 — 타원과 기존 케이스를 **같은 표에**")
    print("   방향오차 두 기준: (명목) = 바람 방향 대비 / (국소) = 사망 노드의 참 법선 평균 대비")
    print("   ※ 곡선 전선에서 '명목'은 사과-오렌지 비교다. 곡률 판정에는 **국소**를 볼 것.")
    print("=" * 112)
    print(f"  {'모델':26s} {'τ':>6s} {'방향(명목)':>16s} {'방향(국소)':>16s} "
          f"{'속도(명목%)':>16s} {'속도(국소%)':>16s} {'추정가능':>9s} {'사망률':>8s}")
    for r in perf:
        lab = (f"타원[{r['geom']}] W{r['wind_kmh']:.0f} LB{r['LB']:.2f} d{r['ignition_d_m']:.0f}"
               if r["model"] == "ellipse" else r["model"])
        f = lambda a, b: (f"{r[a]:8.2f}±{r[b]:<6.2f}" if r[a] is not None else f"{'-':>15s}")
        print(f"  {lab:26s} {r['tau_s']:6.1f} {f('dir_err_nominal_mean','dir_err_nominal_std'):>16s} "
              f"{f('dir_err_local_mean','dir_err_local_std'):>16s} "
              f"{f('speed_err_nominal_pct_mean','speed_err_nominal_pct_std'):>16s} "
              f"{f('speed_err_local_pct_mean','speed_err_local_pct_std'):>16s} "
              f"{r['estimable_pct']:8.0f}% {r['died_frac']:7.0f}%")

    # 예측 대조
    print("\n" + "=" * 112)
    print("★ 사전등록 예측 대조 (해석 없이 일치/불일치만)")
    print("=" * 112)
    s20p = next((r for r in perf if r["model"] == "curved_S2a20" and r["tau_s"] == 0.0), None)
    if s20p:
        ref = s20p["dir_err_nominal_mean"]
        print(f"  예측: 타원 노드-스케일 곡률은 S2a20보다 완만 → 방향오차 < {ref:.2f}° (τ=0)")
        n_ok = n_all = 0
        for r in perf:
            if r["model"] != "ellipse" or r["tau_s"] != 0.0 or r["dir_err_local_mean"] is None:
                continue
            n_all += 1
            ok = r["dir_err_local_mean"] < ref
            n_ok += ok
            print(f"    [{r['geom']:5s}] W{r['wind_kmh']:3.0f} LB{r['LB']:5.2f} d{r['ignition_d_m']:4.0f} → "
                  f"국소 {r['dir_err_local_mean']:7.2f}°  {'일치' if ok else '★불일치'}")
        print(f"  → {n_ok}/{n_all} 셀 일치")


if __name__ == "__main__":
    main()
