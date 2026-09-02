"""run_2m_c.py — 2.M §2 · **곡률 / 굶주림 분리** 재측정.

문제(2.L §4): 타원 곡률 κ·h(0.024~0.486)가 S2a20(0.0071)보다 3.38~68.48배 급하다고 나왔는데,
**앞뒤가 안 맞는다** — head W10은 κ·h≈0.024인데 방향오차 1.99°로 멀쩡하고,
S2a20은 κ·h=0.0071로 **더 완만한데** 10.58°다. 곡률만으로 설명되지 않는다.
원인 후보 둘(곡률 / 표본 굶주림)이 풍속·확산속도라는 **같은 축에 묶여** 분리되지 않았다.

★ 실험 조작: `dt_window`를 **이웃 사망 간격에 비례해 키운다** → 굶주림을 제거하고 곡률만 남긴다.
  ⚠ **이건 dt_window를 '좋아 보이게' 바꾸는 게 아니다.** 교란변수를 제거하기 위한 실험 조작이며,
     **배포 기본값(8.0 s)은 건드리지 않는다.** 이 스크립트 안에서만 스케일링한다.

★ 스케일 규칙 (결과 보기 전에 고정)
      dt_window_exp = max(기본 8.0 s, 3.0 × 이웃 사망 간격 중앙값)
  · 계수 3.0 근거: 격자 4-이웃을 전부 포함하려면 창이 최대 이웃 |ΔT|(≈간격) 이상이어야 하고,
    대각 이웃과 여유까지 보면 3배면 충분하다. **결과를 보고 고른 값이 아니다.**
  · `max(8.0, …)`로 둬서 창이 기본값보다 **좁아지는 일은 없다** — 조작이 표본을 **추가만** 하도록
    해서 "굶주림 제거"라는 해석이 성립하게 한다.

★ 창을 키운 대가도 함께 잰다(지시서 요구): 먼 시간대 이웃이 섞이면 평면 모델이 덜 맞으므로
  잔차 σ̂_t 가 커진다. n_obs·σ̂_t·adequacy 등급을 같이 낸다.

결론 문장 없음 — 원자료·표·플래그만.
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
from sim.adequacy import diagnose, local_adequacy, DEGRADED, INSUFFICIENT
from scripts.run_2e3_diagnose import TrueFront
from scripts.run_2l_b import (ellipse_cfg, plan_tmax, grid_positions,
                              isochrone_curvature, robust_kh, WINDS_KMH, IGNITION_D, GEOMS)
from scripts._par import pmap, n_workers

OUTDIR = os.path.join("results", "stress")
WINDOW_SCALE = 3.0            # ★ 결과 보기 전 고정
BASE_WINDOW = 8.0             # 배포 기본값 — 건드리지 않는다
BASELINES = [("straight_S1", {}), ("curved_S2a10", {"wind_noise_deg": 10.0}),
             ("curved_S2a20", {"wind_noise_deg": 20.0})]
TAU = 0.0                     # 곡률만 보려고 τ=0 고정(τ 효과는 2.J/2.K에서 이미 쟀다)


def neighbor_gap_from_T(T_at, cfg):
    """인접 이웃 쌍의 |ΔT| 중앙값 — 참 도착시각장에서."""
    pts = grid_positions(cfg)
    T = {}
    for p in pts:
        v = T_at(p)
        if v is not None and np.isfinite(v):
            T[p] = v
    s = cfg.spacing_m
    gaps = []
    for p in T:
        for q in T:
            if p is q:
                continue
            d = math.hypot(p[0] - q[0], p[1] - q[1])
            if abs(d - s) < 1e-6:
                gaps.append(abs(T[p] - T[q]))
    return float(np.median(gaps)) if gaps else None


def curvature_and_gap(kind, key, seed=1):
    """조건의 κ·h(중앙값)와 이웃 간격을 참 도착시각장에서 산출."""
    if kind == "ellipse":
        geom, w, d = key
        cfg = ellipse_cfg(w, d, geom=geom, tau=TAU, seed=seed, t_max=plan_tmax(w, d, geom))
        fire = Fire(cfg, None)
        T_at = fire.T_true
    else:
        cfg = Config(mode="ours", seed=seed, sensor_tau_s=TAU, **dict(key))
        eng = Engine(cfg)
        for _ in eng.stream():
            pass
        tf = TrueFront(eng.fire)
        T_at = lambda p, _tf=tf: (_tf.arrival(p) if _tf.arrival(p) is not None else float("nan"))
    ks = [isochrone_curvature(T_at, p, h=0.5) for p in grid_positions(cfg)]
    med, p95, _n = robust_kh(ks, cfg.spacing_m)
    return med, p95, neighbor_gap_from_T(T_at, cfg), cfg


def job(a):
    kind, key, window_mode, dtw, seed = a
    if kind == "ellipse":
        geom, w, d = key
        cfg = ellipse_cfg(w, d, geom=geom, tau=TAU, seed=seed, t_max=plan_tmax(w, d, geom))
        cfg.dt_window = dtw
    else:
        cfg = Config(mode="ours", seed=seed, sensor_tau_s=TAU, dt_window=dtw, **dict(key))
    eng = Engine(cfg)
    for _ in eng.stream():
        pass
    est_dir = eng.estimator.dir_global
    err = None
    if est_dir is not None:
        if kind == "ellipse":
            dv = []
            for nd in eng.nodes:
                if nd.is_sink or nd.death_t is None:
                    continue
                g = eng.fire._ellipse_gradT(nd.pos)
                ng = float(np.linalg.norm(g))
                if ng > 1e-12:
                    dv.append(g / ng)
            if dv:
                m = np.mean(dv, axis=0)
                if float(np.linalg.norm(m)) > 1e-9:
                    err = angle_deg(est_dir, tuple(m / np.linalg.norm(m)))
        else:
            err = angle_deg(est_dir, cfg.direction())
    diag = diagnose(eng.estimator, cfg)
    loc = list(diag["local"].values())
    n_ns = sum(1 for nd in eng.nodes if not nd.is_sink)
    return {"dir_err": err, "estimable": int(est_dir is not None),
            "grade": diag["global"]["grade"],
            "n_local": diag["global"]["n_local"],
            "per_node_frac": round(diag["global"]["n_local"] / n_ns * 100, 1) if n_ns else None,
            "n_obs_mean": round(float(np.mean([r["n_obs"] for r in loc])), 2) if loc else None,
            "sigma_t_mean": (round(float(np.mean([r["sigma_t"] for r in loc
                                                  if r["sigma_t"] is not None])), 4)
                             if any(r["sigma_t"] is not None for r in loc) else None),
            "s2_med": (round(float(np.median([r["s2"] for r in loc if r["s2"] is not None])), 4)
                       if any(r["s2"] is not None for r in loc) else None)}


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


def plot(rows, outdir):
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

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.2))
    for ax, mode, ttl in ((axes[0], "base", "(a) 배포 기본 창 8 s — 굶주림 **포함**"),
                          (axes[1], "scaled", "(b) 창 확대 — 굶주림 **제거**, 곡률만")):
        sub = [r for r in rows if r["window_mode"] == mode and r["dir_err_mean"] is not None]
        for st, mk, col in (("ellipse_head", "o", "#c0392b"), ("ellipse_flank", "s", "#8e44ad"),
                            ("baseline", "^", "#2980b9")):
            s = [r for r in sub if r["group"] == st]
            if s:
                ax.scatter([r["kappa_h_med"] for r in s], [r["dir_err_mean"] for r in s],
                           marker=mk, s=46, color=col, alpha=0.8, label=st)
        for r in sub:
            if r["group"] == "baseline":
                ax.annotate(r["label"].replace("curved_", "").replace("straight_", ""),
                            (r["kappa_h_med"], r["dir_err_mean"]), fontsize=7,
                            xytext=(4, 3), textcoords="offset points")
        ax.axhline(5.0, color="k", ls=":", lw=1.4)
        ax.text(ax.get_xlim()[0], 5.6, "실용선 5°", fontsize=8)
        ax.set_xscale("log"); ax.set_yscale("symlog", linthresh=1.0)
        ax.set_xlabel("등시선 곡률 |κ·h| (중앙값, rad/노드)")
        ax.set_ylabel("방향오차 (°)")
        ax.set_title(ttl, fontsize=11)
        ax.grid(alpha=0.3, which="both"); ax.legend(fontsize=8)
    fig.suptitle("2.M-C  곡률 vs 굶주림 분리 — 창을 키워 굶주림을 제거하면 곡률만 남는다", fontsize=12)
    fig.tight_layout()
    p = os.path.join(outdir, "curve_2m_c_curvature_vs_starvation.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    print(f"  [png] {p}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=15)
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))
    W = args.workers or n_workers()

    print("=" * 108)
    print("2.M §2 · 곡률 / 굶주림 분리 재측정")
    print("=" * 108)
    print(f"  실험 조작: dt_window = max({BASE_WINDOW:.0f} s, {WINDOW_SCALE:.1f} × 이웃 사망 간격 중앙값)")
    print(f"  ⚠ 배포 기본값 {BASE_WINDOW:.0f} s 는 **건드리지 않는다** — 이 스크립트 안에서만 스케일링")
    print(f"  τ={TAU:.0f} 고정(곡률만 보려고) · 시드 {args.seeds} · 워커 {W}\n")

    conds = ([("ellipse", (g, w, d)) for g in GEOMS for w in WINDS_KMH for d in IGNITION_D]
             + [("base", tuple(ov.items())) for _n, ov in BASELINES])

    print("  조건별 κ·h 와 이웃 간격 산출 중...", flush=True)
    meta = {}
    for kind, key in conds:
        med, p95, gap, cfg = curvature_and_gap(kind, key)
        dtw = max(BASE_WINDOW, WINDOW_SCALE * gap) if gap else BASE_WINDOW
        if kind == "ellipse":
            g, w, d = key
            label = f"타원[{g}] W{w:.0f} d{d:.0f}"
            group = f"ellipse_{g}"
        else:
            label = next(n for n, o in BASELINES if tuple(o.items()) == key)
            group = "baseline"
        meta[(kind, key)] = {"label": label, "group": group, "kappa_h_med": med,
                             "kappa_h_p95": p95, "gap_s": round(gap, 2) if gap else None,
                             "dtw_scaled": round(dtw, 2)}

    jobs = []
    for kind, key in conds:
        m = meta[(kind, key)]
        jobs += [(kind, key, "base", BASE_WINDOW, sd) for sd in seeds]
        jobs += [(kind, key, "scaled", m["dtw_scaled"], sd) for sd in seeds]
    print(f"  스윕 {len(jobs)} 런", flush=True)
    res = pmap(job, jobs, workers=W, label="2m-c")

    rows, raw, idx = [], [], 0
    for kind, key in conds:
        m = meta[(kind, key)]
        for mode, dtw in (("base", BASE_WINDOW), ("scaled", m["dtw_scaled"])):
            rs = res[idx:idx + len(seeds)]
            idx += len(seeds)
            for i, r in enumerate(rs):
                raw.append({**m, "window_mode": mode, "dt_window": dtw,
                            "seed": seeds[i], **r})
            de = [r["dir_err"] for r in rs if r["dir_err"] is not None]
            f = lambda k: ([r[k] for r in rs if r[k] is not None])
            rows.append({**m, "window_mode": mode, "dt_window": dtw, "n_seeds": len(seeds),
                         "dir_err_mean": round(float(np.mean(de)), 3) if de else None,
                         "dir_err_std": round(float(np.std(de)), 3) if de else None,
                         "estimable_pct": round(float(np.mean([r["estimable"] for r in rs])) * 100, 1),
                         "per_node_frac": round(float(np.mean(f("per_node_frac"))), 1) if f("per_node_frac") else None,
                         "n_obs_mean": round(float(np.mean(f("n_obs_mean"))), 2) if f("n_obs_mean") else None,
                         "sigma_t_mean": round(float(np.mean(f("sigma_t_mean"))), 4) if f("sigma_t_mean") else None,
                         "s2_med": round(float(np.mean(f("s2_med"))), 4) if f("s2_med") else None,
                         "flagged_pct": round(sum(1 for r in rs if r["grade"] in (DEGRADED, INSUFFICIENT)) / len(rs) * 100, 1)})
    write_csv(os.path.join(args.outdir, "raw_2m_c_separation.csv"), raw)
    write_csv(os.path.join(args.outdir, "summary_2m_c_separation.csv"), rows)
    plot(rows, args.outdir)

    # ── 표 ──
    print("\n" + "=" * 118)
    print("★ 굶주림 제거 전/후 — 같은 축(κ·h) 위에 기존 케이스와 나란히")
    print("=" * 118)
    print(f"  {'조건':26s} {'κ·h':>8s} {'간격s':>7s} {'창s':>7s} "
          f"{'오차(기본)':>11s} {'오차(확대)':>11s} {'Δ오차':>9s} "
          f"{'표본(기본→확대)':>16s} {'σ̂(기본→확대)':>16s}")
    for kind, key in conds:
        m = meta[(kind, key)]
        b = next(r for r in rows if r["label"] == m["label"] and r["window_mode"] == "base")
        s = next(r for r in rows if r["label"] == m["label"] and r["window_mode"] == "scaled")
        fmt = lambda v, n=2: (f"{v:.{n}f}" if v is not None else "  -")
        d = (s["dir_err_mean"] - b["dir_err_mean"]) if (s["dir_err_mean"] is not None
                                                        and b["dir_err_mean"] is not None) else None
        print(f"  {m['label']:26s} {m['kappa_h_med']:8.4f} {(m['gap_s'] or 0):7.1f} "
              f"{s['dt_window']:7.1f} {fmt(b['dir_err_mean']):>11s} {fmt(s['dir_err_mean']):>11s} "
              f"{(f'{d:+.2f}' if d is not None else '  -'):>9s} "
              f"{fmt(b['n_obs_mean'])+' → '+fmt(s['n_obs_mean']):>16s} "
              f"{fmt(b['sigma_t_mean'],3)+' → '+fmt(s['sigma_t_mean'],3):>16s}")

    print("\n" + "=" * 118)
    print("★ 창 확대의 대가 — 표본은 늘지만 평면 모델이 덜 맞는다(σ̂_t 증가)")
    print("=" * 118)
    ok = [(b, s) for kind, key in conds
          for b in [next(r for r in rows if r["label"] == meta[(kind, key)]["label"]
                         and r["window_mode"] == "base")]
          for s in [next(r for r in rows if r["label"] == meta[(kind, key)]["label"]
                         and r["window_mode"] == "scaled")]
          if b["sigma_t_mean"] is not None and s["sigma_t_mean"] is not None]
    if ok:
        dn = [s["n_obs_mean"] - b["n_obs_mean"] for b, s in ok
              if b["n_obs_mean"] is not None and s["n_obs_mean"] is not None]
        ds = [s["sigma_t_mean"] - b["sigma_t_mean"] for b, s in ok]
        print(f"  표본수 평균 변화 {np.mean(dn):+.2f}개 · 잔차 σ̂_t 평균 변화 {np.mean(ds):+.3f} s")
        print(f"  σ̂_t 가 증가한 조건 {sum(1 for x in ds if x > 0)}/{len(ds)}")

    print("\n" + "=" * 118)
    print("★ 곡률만 남은 조건에서 κ·h → 방향오차 (상관)")
    print("=" * 118)
    for mode, lab in (("base", "기본 창(굶주림 포함)"), ("scaled", "확대 창(굶주림 제거)")):
        s = [r for r in rows if r["window_mode"] == mode and r["dir_err_mean"] is not None
             and r["kappa_h_med"] is not None and r["kappa_h_med"] > 0]
        if len(s) > 2:
            x = np.log10([r["kappa_h_med"] for r in s])
            y = np.array([r["dir_err_mean"] for r in s])
            rho = float(np.corrcoef(x, y)[0, 1])
            print(f"  {lab:22s} n={len(s):2d}  corr(log κ·h, 오차) = {rho:+.3f}")


if __name__ == "__main__":
    main()
