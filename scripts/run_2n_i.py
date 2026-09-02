"""run_2n_i.py — 2.N §3-C · 명세 §5-2 사전등록 예측 검정.

★ 예측은 지시서에 **측정 전** 등록돼 있다(사후 수정 금지):
  가설 — 앵커는 **관측 1개**라 개별 지연 d_j가 평균화 없이 실리고,
        방향·속도는 국소 적합 n_j개 평균화로 ~1/√n_j 감쇠한다.
  예측 — 지터 τ에서 **(ETA 오차 증가분)/(방향 오차 증가분)** 비가 τ=0 대비 **증가**한다.
        크기는 √n_j (n=13 → 3~4배) 규모 **이내**.
  ★반증되면 반증된 대로 기록한다.

조건: 2.J-A 지터 스윕과 동일(τ 균일/지터 σ=30 %, 전선 3종, 시드 30, t_max=400).
ETA는 P1 경로(estimator.predict_arrival)를 쓴다 — 앵커가 관측 1개라는 가설의 대상이 그것이다.
결론 문장 없음.
"""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import numpy as np
from sim.config import Config
from sim.engine import Engine
from sim.metrics import angle_deg
from sim.eta_paths import predict_p1
from scripts.run_2e3_diagnose import TrueFront, ETA_DISTS
from scripts._par import pmap, n_workers

TAUS = (0.0, 11.0, 30.0, 78.5)
FRONTS = [("straight_S1", {}), ("curved_S2a10", {"wind_noise_deg": 10.0}),
          ("curved_S2a20", {"wind_noise_deg": 20.0})]
JIT = 0.3


def job(a):
    ov, tau, jit, seed = a
    cfg = Config(mode="ours", seed=seed, sensor_tau_s=tau, sensor_tau_var_pct=jit,
                 sensor_tau_var_dist=("gauss" if jit > 0 else "uniform"),
                 t_max=400.0, **dict(ov))
    eng = Engine(cfg)
    tf = None
    errs, npn = [], []
    for snap in eng.stream():
        t = snap["t"]
        if tf is None:
            tf = TrueFront(eng.fire)
        if not eng.estimator.per_node or abs(t - round(t)) > 1e-9:
            continue
        npn.append(len(eng.estimator.per_node))
        front = np.array(eng.fire.front_pos(t), float)
        nv = np.array(eng.fire._dir_at(t), float)
        for d in ETA_DISTS:
            p = front + nv * d
            ta = tf.arrival(p)
            v, _i = predict_p1(eng.estimator, p)
            if ta is not None and v is not None:
                errs.append(v - ta)
    de = (angle_deg(eng.estimator.dir_global, cfg.direction())
          if eng.estimator.dir_global else None)
    return {"dir_err": de,
            "eta_mae": float(np.mean(np.abs(errs))) if errs else None,
            "n_pernode": float(np.mean(npn)) if npn else None}


if __name__ == "__main__":
    seeds = list(range(1, 31))
    combos = [(ov, t, j) for _n, ov in FRONTS for t in TAUS for j in (0.0, JIT)]
    jobs = [(ov, t, j, sd) for ov, t, j in combos for sd in seeds]
    print(f"2.N §3-C · 명세 §5-2 예측 검정 ({len(jobs)} 런)\n", flush=True)
    res = pmap(job, jobs, workers=n_workers(), label="2n-i")
    rows, idx = [], 0
    for ov, t, j in combos:
        nm = next(n for n, o in FRONTS if o == ov)
        rs = res[idx:idx + len(seeds)]; idx += len(seeds)
        g = lambda k: [r[k] for r in rs if r.get(k) is not None]
        rows.append({"front": nm, "tau_s": t, "mode": "jitter" if j else "uniform",
                     "dir_err": round(float(np.mean(g("dir_err"))), 4) if g("dir_err") else None,
                     "eta_mae": round(float(np.mean(g("eta_mae"))), 4) if g("eta_mae") else None,
                     "n_pernode": round(float(np.mean(g("n_pernode"))), 2) if g("n_pernode") else None})
    p = os.path.join("results", "stress", "summary_2n_i_eta_vs_dir.csv")
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    print(f"  {'전선':16s} {'τ':>5s} {'방향 균일':>9s} {'방향 지터':>9s} {'ETA 균일':>9s} "
          f"{'ETA 지터':>9s} {'Δ방향':>8s} {'ΔETA':>8s} {'★비 ΔETA/Δ방향':>15s} {'n_j':>6s}")
    ratios = {}
    for nm, _ov in FRONTS:
        for t in TAUS:
            u = next((r for r in rows if r["front"] == nm and r["tau_s"] == t and r["mode"] == "uniform"), None)
            jj = next((r for r in rows if r["front"] == nm and r["tau_s"] == t and r["mode"] == "jitter"), None)
            if not u or not jj or None in (u["dir_err"], jj["dir_err"], u["eta_mae"], jj["eta_mae"]):
                continue
            dd = jj["dir_err"] - u["dir_err"]; dee = jj["eta_mae"] - u["eta_mae"]
            ratio = (dee / dd) if abs(dd) > 1e-9 else None
            ratios[(nm, t)] = ratio
            print(f"  {nm:16s} {t:5.1f} {u['dir_err']:9.3f} {jj['dir_err']:9.3f} "
                  f"{u['eta_mae']:9.3f} {jj['eta_mae']:9.3f} {dd:+8.3f} {dee:+8.3f} "
                  f"{(f'{ratio:15.3f}' if ratio is not None else f'{chr(45):>15s}')} {u['n_pernode']:6.1f}")
    print(f"\n  [csv] {p}")

    print("\n" + "=" * 104)
    print("★ 사전등록 예측 대조 (지시서 §3-C, 사후 수정 없음)")
    print("=" * 104)
    print("  예측: 지터에서 ΔETA/Δ방향 비가 **τ=0 대비 증가**, 크기는 √n_j(≈3~4배) 이내")
    n_ref = np.mean([r["n_pernode"] for r in rows if r["n_pernode"]])
    print(f"  기준: n_j 평균 {n_ref:.1f} → √n_j = {np.sqrt(n_ref):.2f}\n")
    ok_inc = ok_mag = tot = 0
    for nm, _ov in FRONTS:
        r0 = ratios.get((nm, 0.0))
        for t in TAUS:
            if t == 0.0: continue
            rt = ratios.get((nm, t))
            if r0 is None or rt is None: continue
            tot += 1
            inc = rt > r0
            mag = abs(rt / r0) <= np.sqrt(n_ref) * 1.3 if abs(r0) > 1e-9 else None
            ok_inc += inc; ok_mag += bool(mag)
            print(f"  {nm:16s} τ={t:5.1f}: 비 {r0:+.3f}(τ=0) → {rt:+.3f}  "
                  f"증가 {'O' if inc else '★X'}   배율 {(rt/r0 if abs(r0)>1e-9 else float('nan')):+.2f}"
                  f"  {'O' if mag else '★X'}")
    print(f"\n  ⇒ '비가 증가' {ok_inc}/{tot} · '√n_j 규모 이내' {ok_mag}/{tot}")
