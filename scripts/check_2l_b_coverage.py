"""check_2l_b_coverage.py — 2.L §4 보조 · 타원 조건에서 **국소적합 표본이 실제로 잡히는가**.

왜 필요한가(정직 기록): `run_2l_b.py`의 '추정가능(%)'은 `dir_global is not None`만 본다.
그런데 측면(flank) 기하에서 방향오차가 72~86°(국소 참 대비)로 나왔고, 그 원인을 보니
**추정이 불가능해서가 아니라 표본이 굶어서 나온 값**이었다:

  이웃 사망 간격 ≈ 노드간격 / 국소 법선속도  가 `dt_window`(8 s)를 넘으면
  `estimator._fit_local`이 이웃을 하나도 못 넣어 per_node가 거의 비고,
  살아남은 소수 적합으로 방향이 계산된다 → **'추정 가능'으로 보고되지만 값이 틀린다.**
  (2.K §5 [D-052]에서 저풍속 때 발견한 것과 **같은 기구**. 거기선 per_node가 완전히 비어
   '추정불가'로 드러났고, 여기선 **부분적으로만 비어 더 위험하다** — 조용히 틀린 답이 나온다.)

⇒ per_node 수(국소적합 성공 노드 수)와 이웃 사망 간격을 같이 재서 그 사실을 표로 만든다.
   `dt_window`는 **변경하지 않는다**(변수 오염 금지).
"""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import numpy as np
from sim.config import Config
from sim.engine import Engine
from sim.fire import Fire
from sim.metrics import angle_deg
from scripts.run_2l_b import ellipse_cfg, plan_tmax, grid_positions, WINDS_KMH, IGNITION_D, GEOMS
from scripts._par import pmap, n_workers


def neighbor_gap(cfg):
    """인접 이웃 쌍의 |ΔT_true| 중앙값 — 시뮬 없이 해석적으로."""
    fire = Fire(cfg, None)
    pts = grid_positions(cfg)
    T = {p: fire.T_true(p) for p in pts}
    s = cfg.spacing_m
    gaps = []
    for p in pts:
        for q in pts:
            if p is q: continue
            d = ((p[0]-q[0])**2 + (p[1]-q[1])**2) ** 0.5
            if abs(d - s) < 1e-6:                 # 4-이웃(격자 한 칸)
                gaps.append(abs(T[p] - T[q]))
    return float(np.median(gaps)) if gaps else None


def job(a):
    geom, w, d, seed = a
    cfg = ellipse_cfg(w, d, geom=geom, tau=0.0, seed=seed, t_max=plan_tmax(w, d, geom))
    eng = Engine(cfg)
    for _ in eng.stream(): pass
    n_ns = sum(1 for nd in eng.nodes if not nd.is_sink)
    dv = []
    for nd in eng.nodes:
        if nd.is_sink or nd.death_t is None: continue
        g = eng.fire._ellipse_gradT(nd.pos); ng = float(np.linalg.norm(g))
        if ng > 1e-12: dv.append(g/ng)
    loc = None
    if dv and eng.estimator.dir_global:
        m = np.mean(dv, axis=0)
        if float(np.linalg.norm(m)) > 1e-9:
            loc = angle_deg(eng.estimator.dir_global, tuple(m/np.linalg.norm(m)))
    return {"n_pernode": len(eng.estimator.per_node), "n_nonsink": n_ns,
            "n_deaths": len(eng.estimator.deaths), "dir_err_local": loc}


if __name__ == "__main__":
    seeds = [1, 2, 3]
    jobs = [(g, w, d, s) for g in GEOMS for w in WINDS_KMH for d in IGNITION_D for s in seeds]
    print(f"2.L §4 보조 — 국소적합 표본 굶주림 점검 ({len(jobs)} 런)\n", flush=True)
    res = pmap(job, jobs, workers=n_workers(), label="cov")
    rows, i = [], 0
    print(f"  {'기하':7s} {'W':>4s} {'L/B':>6s} {'발화m':>6s} {'이웃간격(s)':>12s} "
          f"{'창(8s)':>8s} {'per_node':>10s} {'/노드':>7s} {'방향(국소°)':>12s}")
    for g in GEOMS:
        for w in WINDS_KMH:
            for d in IGNITION_D:
                rs = res[i:i+len(seeds)]; i += len(seeds)
                cfg = ellipse_cfg(w, d, geom=g, t_max=plan_tmax(w, d, g))
                gap = neighbor_gap(cfg)
                pn = float(np.mean([r["n_pernode"] for r in rs]))
                nn = rs[0]["n_nonsink"]
                de = [r["dir_err_local"] for r in rs if r["dir_err_local"] is not None]
                rows.append({"geom": g, "wind_kmh": w, "LB": round(cfg.lb_ratio(),3),
                             "ignition_d_m": d, "neighbor_gap_s": round(gap,2),
                             "dt_window_s": cfg.dt_window, "starved": int(gap > cfg.dt_window),
                             "per_node_mean": round(pn,2), "n_nonsink": nn,
                             "per_node_frac": round(pn/nn*100,1),
                             "dir_err_local_mean": round(float(np.mean(de)),2) if de else None})
                print(f"  {g:7s} {w:4.0f} {cfg.lb_ratio():6.2f} {d:6.0f} {gap:12.2f} "
                      f"{('★초과' if gap>cfg.dt_window else '이내'):>8s} {pn:10.2f} "
                      f"{pn/nn*100:6.0f}% "
                      f"{(f'{np.mean(de):12.2f}' if de else f'{"-":>12s}')}")
    p = os.path.join("results","stress","summary_2l_b_coverage.csv")
    with open(p,"w",newline="",encoding="utf-8") as f:
        w_ = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w_.writeheader(); w_.writerows(rows)
    print(f"\n  [csv] {p} ({len(rows)} rows)")
    st = [r for r in rows if r["starved"]]
    print(f"\n  ★ 이웃 간격이 dt_window(8 s)를 넘는 셀: {len(st)}/{len(rows)}")
    print(f"     그 셀들의 per_node 비율 평균 {np.mean([r['per_node_frac'] for r in st]):.0f}% "
          f"(넘지 않는 셀 {np.mean([r['per_node_frac'] for r in rows if not r['starved']]):.0f}%)")
