"""run_2e3_stepA.py — #2e-3 Step 2.A · 역수 제거(A) 병행 비교.

원 estimator는 그대로 두고(engine이 계속 사용), **같은 사망 이벤트를 병렬 A-estimator에도 먹여**
같은 런 안에서 baseline과 A를 나란히 잰다. `sim/engine.py`·`sim/estimator.py` **무수정**.

★ 사용자 감사 반영 지침
  1) **성공 기준은 '현재 방법 floor'가 아니라 `F_sampling`(물리)**이다.
     S2a·S6는 F_sampling ≈ 0 → A의 목표는 사실상 **0에 가까운 모델형 오차**.
     부풀려진 현재방법 floor(S2a20의 11.69 등)를 "근접했다"의 기준으로 쓰지 않는다.
  2) A는 감사가 지목한 **역수 + per-node 중앙값의 곡률 Jensen 편향**을 정조준한다
     → S6(자유도 0)뿐 아니라 **S2a 곡률**도 내려가는지 본다.
     A가 현재방법 floor **아래로** 가면 "그 floor는 물리가 아니었다"의 최종 확증.
  3) 속도 오차를 **두 기준 모두** 보고: 관측창 평균 참속도(T_bar, 공정) + 순간 참속도(T_inst, 추적).
  5) ETA −6.4 s 오프셋은 **보정하지 않는다**(문서화 기본). A의 ETA 개선은 순수하게 속도 개선분이다.
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
from sim.estimator_regress import RegressionEstimator
from sim.metrics import angle_deg
from scripts.run_2e3_diagnose import TrueFront, ETA_DISTS

OUTDIR = os.path.join("results", "stress")

SCENARIOS = [
    ("S1",       {}),
    ("S2a_5",    {"wind_noise_deg": 5.0}),
    ("S2a_10",   {"wind_noise_deg": 10.0}),
    ("S2a_20",   {"wind_noise_deg": 20.0}),
    ("S2b_20",   {"wind_speed_var_pct": 0.2}),
    ("S2b_40",   {"wind_speed_var_pct": 0.4}),
    ("S4_20",    {"placement_jitter": 0.2}),
    ("S4_40",    {"placement_jitter": 0.4}),
    ("S6_n9",    {"grid_rows": 3, "grid_cols": 3, "p_dropout": 0.05}),
    ("S6_n12",   {"grid_rows": 3, "grid_cols": 4, "p_dropout": 0.05}),
    ("S6_n25",   {"grid_rows": 5, "grid_cols": 5, "p_dropout": 0.05}),
    ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                  "placement_jitter": 0.2, "p_dropout": 0.10}),
]


def run_one(seed, ov):
    cfg = Config(mode="ours", seed=seed, **ov)
    eng = Engine(cfg)
    a_est = RegressionEstimator(cfg, neighbors=eng.net.neighbors)   # 병렬 A-추정기
    fed = set()
    tf = None
    eta = []
    for snap in eng.stream():
        t = snap["t"]
        if tf is None:
            tf = TrueFront(eng.fire)
        # 같은 사망 이벤트를 A-추정기에도 (증분) 투입
        new = [{"id": i, "pos": (x, y), "death_t_est": tt}
               for i, (x, y, tt) in eng.estimator.deaths.items() if i not in fed]
        if new:
            for e in new:
                fed.add(e["id"])
            a_est.update(new, t, None)
        if eng.estimator.per_node and a_est.per_node and abs(t - round(t)) < 1e-9:
            front = np.array(eng.fire.front_pos(t), dtype=float)
            nvec = np.array(eng.fire._dir_at(t), dtype=float)
            for d in ETA_DISTS:
                p = front + nvec * d
                ta = tf.arrival(p)
                if ta is None:
                    continue
                tb = eng.estimator.predict_arrival(p)
                tA = a_est.predict_arrival(p)
                if tb is None or tA is None:
                    continue
                eta.append({"dist": d,
                            "err_base": (tb - t) - (ta - t),
                            "err_A": (tA - t) - (ta - t)})

    # --- 참값 두 기준 ---
    exact = {}
    for nd in eng.nodes:
        if nd.is_sink:
            continue
        ta = tf.arrival(nd.pos)
        if ta is not None:
            exact[nd.id] = ta
    if not exact:
        return None
    t0, t1 = min(exact.values()), max(exact.values())
    ts = np.arange(t0, t1 + 1e-9, cfg.dt)
    v_inst = np.array([eng.fire._speed_at(float(x)) for x in ts], dtype=float)
    T_bar = float(v_inst.mean()) if v_inst.size else cfg.speed_true

    def errs(v):
        if v is None:
            return None, None
        e_bar = (v - T_bar) / T_bar * 100.0
        e_inst = float((np.abs(v - v_inst) / v_inst * 100.0).mean()) if v_inst.size else None
        return e_bar, e_inst

    b_bar, b_inst = errs(eng.estimator.speed_global)
    a_bar, a_inst = errs(a_est.speed_global)
    dir_b = angle_deg(eng.estimator.dir_global, cfg.direction()) if eng.estimator.dir_global else None
    dir_a = angle_deg(a_est.dir_global, cfg.direction()) if a_est.dir_global else None

    return {"seed": seed,
            "speed_base_vs_bar": b_bar, "speed_A_vs_bar": a_bar,
            "speed_base_vs_inst": b_inst, "speed_A_vs_inst": a_inst,
            "dir_base": dir_b, "dir_A": dir_a,
            "dir_delta": (None if (dir_b is None or dir_a is None) else dir_a - dir_b),
            "cov_base": len(eng.estimator.per_node), "cov_A": len(a_est.per_node),
            "eta": eta}


def agg(vals):
    a = np.array([v for v in vals if v is not None and not math.isnan(v)], dtype=float)
    if a.size == 0:
        return None, None, None
    return (round(float(a.mean()), 3), round(float(np.abs(a).mean()), 3), round(float(a.std()), 3))


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
    print(f"  [csv] {path} ({len(rows)} rows)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--outdir", default=OUTDIR)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))

    # 감사(Step 2.0)에서 나온 물리 하한 F_sampling — 성공 기준의 정본(★지침1)
    fs = {}
    # 감사 산출물은 항상 정본 위치(results/stress)에서 읽는다 — --outdir 를 바꿔도 기준은 고정.
    p = os.path.join(OUTDIR, "summary_2e3_20_floor_decomposition.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8")):
            fs[r["scenario"]] = {
                "F_sampling": (float(r["F_sampling_physics"]) if r.get("F_sampling_physics") else 0.0),
                "floor_method": float(r["floor_canonical_vs_bar"] or 0.0)}

    print("#2e-3 Step 2.A · 역수 제거(A) 병행 비교  (원 estimator 무수정, 병렬 추정기로 동시 측정)")
    print("  ★성공 기준 = F_sampling(물리). S2a·S6는 F_sampling≈0 이므로 목표는 '거의 0'.\n")

    res, rows = {}, []
    for name, ov in SCENARIOS:
        runs = [x for x in (run_one(sd, ov) for sd in seeds) if x]
        res[name] = runs
        bb, bba, _ = agg([r["speed_base_vs_bar"] for r in runs])
        ab, aba, _ = agg([r["speed_A_vs_bar"] for r in runs])
        bi, _x, _y = agg([r["speed_base_vs_inst"] for r in runs])
        ai, _x, _y = agg([r["speed_A_vs_inst"] for r in runs])
        db, _x, _y = agg([r["dir_base"] for r in runs])
        da, _x, _y = agg([r["dir_A"] for r in runs])
        dd = max(abs(r["dir_delta"]) for r in runs if r["dir_delta"] is not None)
        rows.append({"scenario": name,
                     "F_sampling_physics": fs.get(name, {}).get("F_sampling"),
                     "floor_method_step20": fs.get(name, {}).get("floor_method"),
                     "speed_base_vs_bar_signed": bb, "speed_A_vs_bar_signed": ab,
                     "speed_base_vs_bar_abs": bba, "speed_A_vs_bar_abs": aba,
                     "speed_base_vs_inst": bi, "speed_A_vs_inst": ai,
                     "dir_base_deg": db, "dir_A_deg": da, "dir_max_abs_delta_deg": round(dd, 6),
                     "cov_base": int(np.mean([r["cov_base"] for r in runs])),
                     "cov_A": int(np.mean([r["cov_A"] for r in runs]))})
        print(f"  [{name:9s}] 속도(vs창평균) base {bb:+7.2f} → A {ab:+7.2f} | "
              f"방향 base {db:6.3f} → A {da:6.3f} (최대 편차 {dd:.2e})")
    write_csv(os.path.join(args.outdir, "summary_2e3_A_speed_dir.csv"), rows)

    # --- ETA ---
    eta_rows = []
    for name, _ in SCENARIOS:
        for d in ETA_DISTS:
            eb = [e["err_base"] for r in res[name] for e in r["eta"] if e["dist"] == d]
            ea = [e["err_A"] for r in res[name] for e in r["eta"] if e["dist"] == d]
            if not eb:
                continue
            B, A = np.array(eb), np.array(ea)
            eta_rows.append({"scenario": name, "dist_m": d, "n": int(B.size),
                             "base_mean_s": round(float(B.mean()), 2),
                             "A_mean_s": round(float(A.mean()), 2),
                             "base_abs_s": round(float(np.abs(B).mean()), 2),
                             "A_abs_s": round(float(np.abs(A).mean()), 2),
                             "base_std_s": round(float(B.std()), 2),
                             "A_std_s": round(float(A.std()), 2),
                             "base_danger_pct": round(float((B > 0).mean() * 100), 1),
                             "A_danger_pct": round(float((A > 0).mean() * 100), 1)})
    write_csv(os.path.join(args.outdir, "summary_2e3_A_eta.csv"), eta_rows)

    # ---------------- 콘솔 ----------------
    print("\n" + "=" * 104)
    print("★ 속도 오차 — baseline vs A  ·  성공 기준은 F_sampling(물리), 현재방법 floor는 참고용")
    print("=" * 104)
    print(f"  {'시나리오':9s} {'F_samp★물리':>11s} {'(방법floor)':>11s} | "
          f"{'base 부호':>10s} {'A 부호':>9s} | {'base |·|':>9s} {'A |·|':>8s} | "
          f"{'base vs순간':>11s} {'A vs순간':>10s}")
    for r in rows:
        fsv = r["F_sampling_physics"]
        print(f"  {r['scenario']:9s} {(fsv if fsv is not None else 0.0):11.2f} "
              f"{(r['floor_method_step20'] or 0.0):11.2f} | "
              f"{r['speed_base_vs_bar_signed']:+10.2f} {r['speed_A_vs_bar_signed']:+9.2f} | "
              f"{r['speed_base_vs_bar_abs']:9.2f} {r['speed_A_vs_bar_abs']:8.2f} | "
              f"{r['speed_base_vs_inst']:11.2f} {r['speed_A_vs_inst']:10.2f}")

    print("\n" + "=" * 104)
    print("★ 방향 비열화 검증 (구조적으로 불변이도록 설계: 방향 가중치에 원 평면속도만 사용)")
    print("=" * 104)
    worst = max(r["dir_max_abs_delta_deg"] for r in rows)
    for r in rows:
        print(f"  {r['scenario']:9s} base {r['dir_base_deg']:7.3f}°  A {r['dir_A_deg']:7.3f}°  "
              f"최대 |Δ| = {r['dir_max_abs_delta_deg']:.3e}°   "
              f"커버리지 {r['cov_base']} → {r['cov_A']}")
    print(f"\n  전 시나리오 최대 방향 편차 = {worst:.3e}°  → "
          f"{'✅ 비열화 없음(비트 동일 수준)' if worst < 1e-9 else '★ 방향 변화 발생 — 원인 규명 필요'}")

    print("\n" + "=" * 104)
    print("★ ETA 오차 (초) — err>0 = 늦게 예측 = 위험측.  −6.4 s 오프셋은 보정하지 않음(문서화 기본)")
    print("=" * 104)
    print(f"  {'시나리오':9s} {'거리':>5s} {'base 평균':>9s} {'A 평균':>8s} {'base |·|':>9s} "
          f"{'A |·|':>8s} {'base std':>9s} {'A std':>8s} {'base위험%':>9s} {'A위험%':>8s}")
    for r in eta_rows:
        print(f"  {r['scenario']:9s} {r['dist_m']:5.0f} {r['base_mean_s']:+9.2f} {r['A_mean_s']:+8.2f} "
              f"{r['base_abs_s']:9.2f} {r['A_abs_s']:8.2f} {r['base_std_s']:9.2f} {r['A_std_s']:8.2f} "
              f"{r['base_danger_pct']:9.1f} {r['A_danger_pct']:8.1f}")

    print("\n" + "=" * 104)
    print("★ 판정 (지침1·2)")
    print("=" * 104)
    for r in rows:
        fsv = r["F_sampling_physics"] or 0.0
        a_abs = r["speed_A_vs_bar_abs"]
        fl = r["floor_method_step20"] or 0.0
        if fsv < 0.5:      # 물리 하한이 사실상 0인 시나리오
            note = ("✅ 물리 하한(≈0)에 근접" if a_abs < 1.0 else
                    f"잔여 {a_abs:.2f} % — 물리로 설명 안 됨(방법 몫)")
            extra = ""
            if fl > 0.05:
                extra = ("  ★ 현재방법 floor(%.2f) **아래로 내려감** → 그 floor는 물리가 아니었음의 확증"
                         % fl) if a_abs < fl else "  (현재방법 floor 위)"
            print(f"  {r['scenario']:9s} base {r['speed_base_vs_bar_abs']:6.2f} → A {a_abs:6.2f} %  "
                  f"| 물리하한 ≈0  {note}{extra}")
        else:
            print(f"  {r['scenario']:9s} base {r['speed_base_vs_bar_abs']:6.2f} → A {a_abs:6.2f} %  "
                  f"| 물리하한 {fsv:.2f} %(vs순간) — 돌풍은 여기까지가 한계")


if __name__ == "__main__":
    main()
