"""run_2n_c.py — 2.N §3 · 분기③ `residual_min_samples` 스윕.

유도는 `docs/유도_표본적정성_진단기준.md` **부록 A**에 측정 전 커밋(69a9009).
n=3이면 DOF=0이라 잔차가 항등 0 → residual 검사가 무조건 통과(공허). 판별력엔 n≥4가 필요.

★ 변수 분리: `min_samples`(estimator·verifier 공용) 대신 `residual_min_samples`만 스윕한다.
  기본값 None → min_samples 폴백이라 **비트 동일**(회귀로 확인).
★ 스윕 결과만 낸다 — **채택 여부는 결정하지 않는다**(판정 규칙 변경은 baseline 재확정을 요구).
"""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import numpy as np
from sim.config import Config
from sim.engine import Engine
from sim.metrics import angle_deg
from scripts._par import pmap, n_workers

SCEN = [("S1", {}), ("S2a_10", {"wind_noise_deg": 10.0}),
        ("S11_nonfire4", {"n_nonfire_deaths": 4}), ("S11_nonfire8", {"n_nonfire_deaths": 8})]
NVALS = (3, 4, 5, 6)


def job(a):
    name, ov, n, seed = a
    cfg = Config(mode="ours", seed=seed, residual_min_samples=n, **ov)
    eng = Engine(cfg)
    first_dir = None
    for snap in eng.stream():
        if first_dir is None and snap["est"] and snap["est"].get("dir") is not None:
            first_dir = snap["t"]
    v = eng.verifier
    b3 = [d for d in v.sample_poor_log]
    act = {i for i in eng.nonfire_ids if eng.by_id[i].nonfire}
    pol = len(act & set(eng.estimator.deaths)) / len(act) * 100 if act else None
    de = (angle_deg(eng.estimator.dir_global, cfg.direction())
          if eng.estimator.dir_global else None)
    fd = min((nd.death_t for nd in eng.nodes if nd.death_t is not None), default=None)
    return {"dir_err": de, "first_dir_t": first_dir, "first_death_t": fd,
            "n_confirmed": len(eng.estimator.deaths), "n_excluded": len(v.excluded_nonfire),
            "n_residual_fits": len(v.residual_n_log),
            "n_dof0": sum(1 for x in v.residual_n_log if x == 3),
            "n_sample_poor": len(b3), "pollution": pol}


if __name__ == "__main__":
    seeds = list(range(1, 31))
    jobs = [(nm, ov, n, sd) for nm, ov in SCEN for n in NVALS for sd in seeds]
    print("=" * 104)
    print("2.N §3 · 분기③ residual_min_samples 스윕 (유도: 부록 A, 선커밋 69a9009)")
    print("=" * 104)
    print(f"  값 {NVALS} (3=현행) · 시나리오 {[n for n,_ in SCEN]} · 시드 30 · {len(jobs)} 런")
    print("  ★ estimator의 min_samples는 3으로 **고정** — 분기③만 조인다\n", flush=True)
    res = pmap(job, jobs, workers=n_workers(), label="2n-c")
    rows, idx = [], 0
    print(f"  {'시나리오':15s} {'n':>3s} {'방향오차':>9s} {'첫방향':>8s} {'확정':>7s} {'제외':>7s} "
          f"{'residual적합':>12s} {'그중n=3':>9s} {'표본부족':>9s} {'오염률%':>9s}")
    for nm, ov in SCEN:
        for n in NVALS:
            rs = res[idx:idx + len(seeds)]; idx += len(seeds)
            g = lambda k: [r[k] for r in rs if r[k] is not None]
            rec = {"scenario": nm, "residual_min_samples": n,
                   "dir_err_mean": round(float(np.mean(g("dir_err"))), 3) if g("dir_err") else None,
                   "first_dir_t": round(float(np.mean(g("first_dir_t"))), 2) if g("first_dir_t") else None,
                   "n_confirmed": round(float(np.mean(g("n_confirmed"))), 2),
                   "n_excluded": round(float(np.mean(g("n_excluded"))), 2),
                   "n_residual_fits": round(float(np.mean(g("n_residual_fits"))), 2),
                   "n_dof0": round(float(np.mean(g("n_dof0"))), 2),
                   "n_sample_poor": round(float(np.mean(g("n_sample_poor"))), 2),
                   "pollution_pct": round(float(np.mean(g("pollution"))), 2) if g("pollution") else None}
            rows.append(rec)
            print(f"  {nm:15s} {n:3d} {(rec['dir_err_mean'] or 0):9.3f} {(rec['first_dir_t'] or 0):8.2f} "
                  f"{rec['n_confirmed']:7.2f} {rec['n_excluded']:7.2f} {rec['n_residual_fits']:12.2f} "
                  f"{rec['n_dof0']:9.2f} {rec['n_sample_poor']:9.2f} "
                  f"{(rec['pollution_pct'] if rec['pollution_pct'] is not None else float('nan')):9.2f}")
    p = os.path.join("results", "stress", "summary_2n_c_residual_minsamples.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"\n  [csv] {p}")
    print("\n" + "=" * 104)
    print("★ 교환관계 — n을 올리면 공허한 통과가 줄지만 진짜 화재사망도 버려진다")
    print("=" * 104)
    print(f"  {'시나리오':15s} {'n':>3s} {'DOF=0 적합':>11s} {'확정 변화':>10s} {'오염률 변화':>12s} {'방향 변화':>10s}")
    for nm, _ov in SCEN:
        base = next(r for r in rows if r["scenario"] == nm and r["residual_min_samples"] == 3)
        for n in NVALS:
            r = next(x for x in rows if x["scenario"] == nm and x["residual_min_samples"] == n)
            dc = r["n_confirmed"] - base["n_confirmed"]
            dp = ((r["pollution_pct"] - base["pollution_pct"])
                  if (r["pollution_pct"] is not None and base["pollution_pct"] is not None) else None)
            dd = ((r["dir_err_mean"] - base["dir_err_mean"])
                  if (r["dir_err_mean"] is not None and base["dir_err_mean"] is not None) else None)
            print(f"  {nm:15s} {n:3d} {r['n_dof0']:11.2f} {dc:+10.2f} "
                  f"{(f'{dp:+.2f}' if dp is not None else '-'):>12s} "
                  f"{(f'{dd:+.3f}' if dd is not None else '-'):>10s}")
    print("\n  ★ 채택 여부는 결정하지 않는다 — Cowork/사용자 판단.")
