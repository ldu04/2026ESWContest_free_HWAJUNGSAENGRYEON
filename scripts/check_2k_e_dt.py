"""check_2k_e_dt.py — 2.K §5의 **dt 상향이 결과를 바꾸지 않는지** 실제로 확인.

왜 따로 두나(정직 기록): `run_2k_e.py` 안의 수렴 점검은 u=2.0·5.0 에서 돌렸는데, 그 u들은
plan_time 이 dt=0.1 을 그대로 돌려주므로 **두 dt가 같아 아무것도 비교하지 못했다**(로그 2줄이 그 증거).
dt가 실제로 올라가는 구간은 u=0.1 뿐이다. 거기서 dt=0.1(기준) vs dt=자동 을 나란히 돌린다.
dropout 은 초당 hazard 를 보존하도록 p_eff=1-(1-p)^(dt/0.1) 로 맞춘다(본 스윕과 동일 규약).
"""
import csv, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import numpy as np
from sim.config import Config
from sim.engine import Engine
from sim.metrics import angle_deg
from scripts.run_2e3_diagnose import TrueFront
from scripts.run_2k_e import tau_of, plan_time, p_dropout_for, BURN
from scripts._par import pmap, n_workers

def job(a):
    u, c, dt, seed = a
    v = c*u; tau = tau_of(u); t_max, _ = plan_time(v, tau, Config())
    cfg = Config(mode="ours", seed=seed, peak=300.0, sensor_tau_s=tau, speed_true=v,
                 burn_scale_m=BURN, t_max=t_max, dt=dt,
                 p_dropout=p_dropout_for(Config().p_dropout, dt))
    eng = Engine(cfg)
    for _ in eng.stream(): pass
    tf = TrueFront(eng.fire)
    ex = ms = 0
    for nd in eng.nodes:
        if nd.is_sink or tf.arrival(nd.pos) is None: continue
        ex += 1
        if nd.death_t is None: ms += 1
    de = angle_deg(eng.estimator.dir_global, cfg.direction()) if eng.estimator.dir_global else None
    return {"miss_rate": ms/ex*100 if ex else 0.0, "dir_err": de,
            "n_conf": len(eng.estimator.deaths), "t_max": t_max}

if __name__ == "__main__":
    SEEDS = list(range(1, 11))
    CASES = [(0.1, 0.15), (0.1, 0.10), (0.1, 0.05)]
    rows = []
    print("2.K §5 · dt 수렴 점검 (dt가 실제로 올라가는 u=0.1 구간에서만 의미가 있다)\n")
    for u, c in CASES:
        _tm, dt_auto = plan_time(c*u, tau_of(u), Config())
        dts = sorted({0.1, dt_auto})
        print(f"  u={u} c={c}  자동 dt={dt_auto:.4f}  → 비교 {dts}", flush=True)
        res = {}
        for dt in dts:
            t0 = time.time()
            rs = pmap(job, [(u, c, dt, s) for s in SEEDS], workers=n_workers(), label=f"dt{dt}")
            mr = float(np.mean([r["miss_rate"] for r in rs]))
            de = [r["dir_err"] for r in rs if r["dir_err"] is not None]
            nc = float(np.mean([r["n_conf"] for r in rs]))
            res[dt] = (mr, de, nc)
            rows.append({"wind_u": u, "c_spread": c, "dt": dt, "t_max": rs[0]["t_max"],
                         "miss_rate_mean": round(mr, 3), "n_confirmed_mean": round(nc, 2),
                         "dir_valid": len(de),
                         "dir_err_mean": round(float(np.mean(de)), 3) if de else None})
            print(f"    dt={dt:<7.4f} 미탐지 {mr:6.2f} %  확정 {nc:5.2f}  "
                  f"방향 {(f'{np.mean(de):.3f}° (n={len(de)})' if de else '전부 추정불가')}"
                  f"   [{time.time()-t0:.0f}s]", flush=True)
        if len(dts) == 2:
            a, b = res[dts[0]], res[dts[1]]
            print(f"    ⇒ 미탐지 차 {abs(a[0]-b[0]):.3f} %p · 확정수 차 {abs(a[2]-b[2]):.2f} · "
                  f"방향가능 {len(a[1])} vs {len(b[1])}\n", flush=True)
    p = os.path.join("results", "stress", "summary_2k_e_dt_convergence_real.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"  [csv] {p} ({len(rows)} rows)")
