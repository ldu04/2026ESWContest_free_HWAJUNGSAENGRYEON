"""run_2n_h.py — 2.N §3-A(영향범위) + §3-B(두 경로 차이) 측정.

★ A는 **게이트를 적용하기 전에 영향 범위부터** 잰다(지시). 크면 조치 전에 상의한다.
★ estimator.py 불변 — 게이트는 sim/eta_paths.py의 버전 분기로만 계산한다.
결론 문장 없음.
"""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import numpy as np
from sim.config import Config
from sim.engine import Engine
from sim.eta_paths import node_grades, gated_allow, predict_p1, predict_p2
from scripts.run_2e3_diagnose import TrueFront, ETA_DISTS
from scripts.run_2l_b import ellipse_cfg, plan_tmax
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
    tf = None
    n_q = n_p1 = n_p1g = n_p2 = 0          # 질의 수 / 각 경로 산출 성공 수
    e1, e1g, e2, diff = [], [], [], []     # 참값 대비 오차 · P1−P2 차이
    for snap in eng.stream():
        t = snap["t"]
        if tf is None and kind != "ellipse":
            tf = TrueFront(eng.fire)
        if not eng.estimator.per_node or abs(t - round(t)) > 1e-9:
            continue
        grades = node_grades(eng.estimator, cfg)
        allow = gated_allow(grades)
        front = np.array(eng.fire.front_pos(t), float)
        nv = np.array(eng.fire._dir_at(t) if kind != "ellipse" else cfg.direction(), float)
        for d in ETA_DISTS:
            p = front + nv * d
            ta = (eng.fire.T_true(p) if kind == "ellipse"
                  else (tf.arrival(p) if tf else None))
            if ta is None or not np.isfinite(ta):
                continue
            n_q += 1
            v1, _i = predict_p1(eng.estimator, p)
            v1g, _ig = predict_p1(eng.estimator, p, allow)
            v2, _j = predict_p2(eng.estimator, p)
            if v1 is not None: n_p1 += 1; e1.append(v1 - ta)
            if v1g is not None: n_p1g += 1; e1g.append(v1g - ta)
            if v2 is not None: n_p2 += 1; e2.append(v2 - ta)
            if v1 is not None and v2 is not None: diff.append(v1 - v2)
    f = lambda a: (float(np.mean(np.abs(a))) if a else None)
    return {"n_q": n_q, "n_p1": n_p1, "n_p1g": n_p1g, "n_p2": n_p2,
            "mae_p1": f(e1), "mae_p1g": f(e1g), "mae_p2": f(e2),
            "diff_mae": f(diff),
            "diff_p95": (float(np.percentile(np.abs(diff), 95)) if diff else None),
            "lost_frac": (1.0 - n_p1g / n_p1) * 100 if n_p1 else None}


if __name__ == "__main__":
    seeds = list(range(1, 11))
    jobs = [(k, key, t, sd) for k, key in CONDS for t in TAUS for sd in seeds]
    print(f"2.N §3-A/B · ETA 등급 게이트 영향범위 + 두 경로 차이 ({len(jobs)} 런)")
    print("  ★게이트는 아직 적용 안 함 — 영향 범위만 잰다\n", flush=True)
    res = pmap(job, jobs, workers=n_workers(), label="2n-h")
    rows, idx = [], 0
    print(f"  {'조건':26s} {'τ':>4s} {'질의':>7s} {'P1산출':>7s} {'게이트후':>8s} "
          f"{'★손실%':>8s} {'MAE P1':>9s} {'MAE 게이트':>10s} {'MAE P2':>9s} {'|P1−P2|':>9s}")
    for kind, key in CONDS:
        lab = (f"타원[{key[0]}] W{key[1]:.0f} d{key[2]:.0f}" if kind == "ellipse" else key[0])
        for t in TAUS:
            rs = res[idx:idx + len(seeds)]; idx += len(seeds)
            g = lambda k: [r[k] for r in rs if r.get(k) is not None]
            rec = {"label": lab, "tau_s": t,
                   "n_q": sum(r["n_q"] for r in rs), "n_p1": sum(r["n_p1"] for r in rs),
                   "n_p1g": sum(r["n_p1g"] for r in rs), "n_p2": sum(r["n_p2"] for r in rs)}
            rec["lost_pct"] = (round((1 - rec["n_p1g"] / rec["n_p1"]) * 100, 2)
                               if rec["n_p1"] else None)
            for k in ("mae_p1", "mae_p1g", "mae_p2", "diff_mae", "diff_p95"):
                rec[k] = round(float(np.mean(g(k))), 3) if g(k) else None
            rows.append(rec)
            fm = lambda k, w=9: (f"{rec[k]:{w}.2f}" if rec[k] is not None else f"{'-':>{w}s}")
            print(f"  {lab:26s} {t:4.0f} {rec['n_q']:7d} {rec['n_p1']:7d} {rec['n_p1g']:8d} "
                  f"{(f'{rec[chr(108)+chr(111)+chr(115)+chr(116)+chr(95)+chr(112)+chr(99)+chr(116)]:8.2f}' if rec['lost_pct'] is not None else '       -')} "
                  f"{fm('mae_p1')} {fm('mae_p1g',10)} {fm('mae_p2')} {fm('diff_mae')}")
    p = os.path.join("results", "stress", "summary_2n_h_eta_paths.csv")
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"\n  [csv] {p}")

    print("\n" + "=" * 104)
    print("★★ A 영향 범위 — 게이트로 ETA를 못 내게 되는 정도")
    print("=" * 104)
    tot_q = sum(r["n_p1"] for r in rows); tot_g = sum(r["n_p1g"] for r in rows)
    print(f"  전체 질의 중 P1 산출 {tot_q}건 → 게이트 후 {tot_g}건 "
          f"(손실 {(1-tot_g/tot_q)*100:.2f} %)")
    full = [r for r in rows if r["n_p1"] > 0 and r["n_p1g"] == 0]
    part = [r for r in rows if r["n_p1"] > 0 and 0 < r["n_p1g"] < r["n_p1"]]
    print(f"  ★ETA를 **전혀 못 내게 되는** 조건: {len(full)}/{len(rows)}")
    for r in full: print(f"      - {r['label']} τ={r['tau_s']:.0f}")
    print(f"  부분 손실 조건: {len(part)}/{len(rows)}")
    for r in sorted(part, key=lambda x: -x["lost_pct"])[:8]:
        print(f"      - {r['label']:26s} τ={r['tau_s']:3.0f}  손실 {r['lost_pct']:5.2f} %  "
              f"MAE {r['mae_p1']} → {r['mae_p1g']}")
    imp = [(r["mae_p1"] - r["mae_p1g"]) for r in rows
           if r["mae_p1"] is not None and r["mae_p1g"] is not None]
    if imp:
        print(f"  게이트 적용 시 MAE 변화: 평균 {np.mean(imp):+.3f} s "
              f"(개선 {sum(1 for x in imp if x>0)} / 악화 {sum(1 for x in imp if x<0)} 조건)")

    print("\n" + "=" * 104)
    print("★ B 두 경로 일치도 — |P1 − P2| (같은 질의점, 차이는 속도원뿐)")
    print("=" * 104)
    dm = [r["diff_mae"] for r in rows if r["diff_mae"] is not None]
    dp = [r["diff_p95"] for r in rows if r["diff_p95"] is not None]
    print(f"  전 조건 평균 |P1−P2| = {np.mean(dm):.2f} s · P95 = {np.mean(dp):.2f} s")
    print(f"  {'조건':26s} {'τ':>4s} {'|P1−P2| 평균':>13s} {'P95':>9s} {'MAE P1':>9s} {'MAE P2':>9s}")
    for r in sorted([x for x in rows if x["diff_mae"] is not None],
                    key=lambda x: -x["diff_mae"])[:10]:
        print(f"  {r['label']:26s} {r['tau_s']:4.0f} {r['diff_mae']:13.2f} {r['diff_p95']:9.2f} "
              f"{r['mae_p1']:9.2f} {r['mae_p2']:9.2f}")
