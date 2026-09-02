"""run_2n_g.py — 2.N 추가-G · 전역 집계 가중 후보 비교.

유도는 `docs/유도_표본적정성_진단기준.md` 부록 B에 **측정 전** 커밋(817dbfe).
★ `sim/estimator.py` 불변 — 집계는 `sim/aggregate.py`가 per_node를 밖에서 다시 합친다.
  `legacy`는 `dir_global`과 비트 동일(테스트로 고정). **기본값 전환은 하지 않는다.**
결론 문장 없음 — 표·플래그만. 채택 결정도 하지 않는다.
"""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import numpy as np
from sim.config import Config
from sim.engine import Engine
from sim.metrics import angle_deg
from sim.aggregate import all_modes, MODES
from scripts.run_2l_b import ellipse_cfg, plan_tmax
from scripts.run_2e3_diagnose import TrueFront
from scripts._par import pmap, n_workers

TAUS = (0.0, 11.0, 78.5)
CONDS = ([("ellipse", ("flank", 10.0, d)) for d in (30.0, 60.0, 120.0)]
         + [("ellipse", ("head", w, d)) for w in (10.0, 20.0, 30.0, 50.0) for d in (30.0, 60.0, 120.0)]
         + [("line", ("straight_S1", {})), ("line", ("curved_S2a10", {"wind_noise_deg": 10.0})),
            ("line", ("curved_S2a20", {"wind_noise_deg": 20.0}))])


def job(a):
    kind, key, tau, seed = a
    if kind == "ellipse":
        g, w, d = key
        cfg = ellipse_cfg(w, d, geom=g, tau=tau, seed=seed, t_max=plan_tmax(w, d, g))
    else:
        _n, ov = key
        cfg = Config(mode="ours", seed=seed, sensor_tau_s=tau, t_max=400.0, **dict(ov))
    eng = Engine(cfg)
    for _ in eng.stream(): pass
    est = eng.estimator
    if not est.per_node:
        return {m: None for m in MODES} | {"n_eff": None, "max_w": None, "disp_w": None}
    tf = None if kind == "ellipse" else TrueFront(eng.fire)
    tn = []
    for i, v in est.per_node.items():
        if kind == "ellipse":
            gg = eng.fire._ellipse_gradT(v["pos"]); n = np.linalg.norm(gg)
            if n > 1e-12: tn.append(gg / n)
        else:
            ta = tf.arrival(v["pos"])
            tn.append(np.array(eng.fire._dir_at(ta if ta is not None else 0.0)))
    if not tn:
        return {m: None for m in MODES} | {"n_eff": None, "max_w": None, "disp_w": None}
    ref = np.mean(tn, axis=0); ref = ref / np.linalg.norm(ref)
    res = all_modes(est, cfg)
    out = {m: (angle_deg(res[m]["dir"], tuple(ref)) if res[m]["dir"] is not None else None)
           for m in MODES}
    out["n_eff"] = res["legacy"]["n_eff"]; out["max_w"] = res["legacy"]["max_w_frac"]
    out["disp_w"] = res["legacy"]["disp_w_deg"]
    out["n_used_invvar"] = res["invvar_trim"]["n_used"]
    return out


if __name__ == "__main__":
    seeds = list(range(1, 16))
    jobs = [(k, key, t, sd) for k, key in CONDS for t in TAUS for sd in seeds]
    print(f"2.N 추가-G · 집계 가중 비교 ({len(jobs)} 런) — 유도 선커밋 817dbfe\n", flush=True)
    res = pmap(job, jobs, workers=n_workers(), label="2n-g")
    rows, idx = [], 0
    print(f"  {'조건':26s} {'τ':>5s} " + "".join(f"{m:>12s}" for m in MODES) +
          f"{'n_eff':>8s}{'최대가중':>9s}")
    for kind, key in CONDS:
        lab = (f"타원[{key[0]}] W{key[1]:.0f} d{key[2]:.0f}" if kind == "ellipse" else key[0])
        for t in TAUS:
            rs = res[idx:idx + len(seeds)]; idx += len(seeds)
            rec = {"label": lab, "tau_s": t}
            for m in MODES:
                v = [r[m] for r in rs if r.get(m) is not None]
                rec[m] = round(float(np.mean(v)), 3) if v else None
            for k in ("n_eff", "max_w", "disp_w", "n_used_invvar"):
                v = [r[k] for r in rs if r.get(k) is not None]
                rec[k] = round(float(np.mean(v)), 3) if v else None
            rows.append(rec)
            f = lambda m: (f"{rec[m]:12.2f}" if rec[m] is not None else f"{'-':>12s}")
            print(f"  {lab:26s} {t:5.0f} " + "".join(f(m) for m in MODES) +
                  f"{(rec['n_eff'] if rec['n_eff'] is not None else float('nan')):8.2f}"
                  f"{(rec['max_w'] if rec['max_w'] is not None else float('nan')):9.3f}")
    p = os.path.join("results", "stress", "summary_2n_g_aggregate.csv")
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"\n  [csv] {p}")

    print("\n" + "=" * 108)
    print("★ 사전등록 예측 대조 (부록 B-7)")
    print("=" * 108)
    d30 = [r for r in rows if r["label"] == "타원[flank] W10 d30"]
    d60 = [r for r in rows if r["label"] == "타원[flank] W10 d60"]
    if d30:
        lg = np.mean([r["legacy"] for r in d30 if r["legacy"] is not None])
        iv = np.mean([r["invvar"] for r in d30 if r["invvar"] is not None])
        un = np.mean([r["uniform"] for r in d30 if r["uniform"] is not None])
        print(f"  G1 invvar가 d30을 legacy보다 크게 낮춘다 → legacy {lg:.2f}° / invvar {iv:.2f}° / "
              f"uniform {un:.2f}°  → {'일치' if iv < lg * 0.5 else '★불일치'}")
    if d60:
        lg = np.mean([r["legacy"] for r in d60 if r["legacy"] is not None])
        best = min(np.mean([r[m] for r in d60 if r[m] is not None]) for m in MODES)
        print(f"  G2 d60은 어떤 가중으로도 못 고친다 → legacy {lg:.2f}° / 최선 {best:.2f}°  "
              f"→ {'일치' if best > 30 else '★불일치'}")
    if d30:
        ne = np.mean([r["n_eff"] for r in d30 if r["n_eff"] is not None])
        print(f"  G3 n_eff가 d30을 위험으로 잡는다 → n_eff={ne:.2f} (판정선 2)  "
              f"→ {'일치' if ne < 2 else '★불일치'}")
    ok = [r for r in rows if r["label"] in ("straight_S1", "타원[head] W10 d120")]
    if ok:
        dd = [abs(r["invvar"] - r["legacy"]) for r in ok
              if r["invvar"] is not None and r["legacy"] is not None]
        print(f"  G4 잘 되는 조건은 가중을 바꿔도 거의 안 변한다 → |Δ| 평균 {np.mean(dd):.2f}°  "
              f"→ {'일치' if np.mean(dd) < 2 else '★불일치'}")
