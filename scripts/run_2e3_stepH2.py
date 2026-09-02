"""run_2e3_stepH2.py — #2e-3 Step 2.H **Step 2a** · 재구성 사망시각을 넣고 **2.G τ 게이트 재실행**.

★ 판정 기준 (사용자 지시, Step 1 '결함 2' 반영)
──────────────────────────────────────────────────────────────────────────────
Step 1에서 **잔차 지표가 관대해 어떤 부분 보정도 자동으로 "순이득"**이 됨을 확인했다.
따라서 **잔차로 판정하지 않는다.** 유일한 기준은 **[D-042] τ 게이트의 위험측 `breach_early`**다:
  결합 최악(warm_scale×0.5 ∧ τ=10 s)에서 E3x2 위험측이 **(C) 19.3 % → ≤10 %** 로 내려가
  **(B)로 완화되는가.** 강풍·결합 축은 반드시 포함한다(재구성의 실질 성과가 강풍 복구이므로).
──────────────────────────────────────────────────────────────────────────────

구현
----
· 스트림을 돌면서, 새로 확정된 사망마다 **그 시점의 `rep_hist`**로 재구성 시각을 계산해
  **병렬 estimator**에 증분 투입한다(그 시점에 실제로 가용한 데이터만 씀 — 미래 정보 금지).
· **τ_used = 0 이면 재구성하지 않고 원 사망시각을 쓴다.** 그래야 τ=0 세계가 기존과 동일하고,
  [D-040]의 편향 항(S1·W0·τ=0에서 도출)을 **재적합 없이** 그대로 쓸 수 있다.
· 밴드는 E2 / E3 / E3x / **E3x2**(이른끝 무보정) 전부 산출. 판정은 E3x2 기준.
· estimator.py 불변. 재구성은 사망시각 산출 앞단에서만.
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
from sim.estimator import Estimator
from sim.metrics import angle_deg
from scripts.run_2e3_diagnose import TrueFront, ETA_DISTS
from scripts.run_2e3_stepE import speed_band, nearest_local, OUTDIR
from scripts.run_2e3_stepF import derive_bias_at_W0, EXPAND_R, EXPAND_R_HI
from scripts.run_2e3_stepH import recon_cross_time

# 2.G와 같은 평가 세트(결합 최악 포함). 강풍 축 필수.
EVAL = [
    ("S2a_10",   {"wind_noise_deg": 10.0}),
    ("S2a_20",   {"wind_noise_deg": 20.0}),
    ("S4_40",    {"placement_jitter": 0.4}),
    ("S6_n9",    {"grid_rows": 3, "grid_cols": 3, "p_dropout": 0.05}),
    ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                  "placement_jitter": 0.2, "p_dropout": 0.10}),
]
# (τ_true, mode_var_pct, warm_mult) — 2.G의 핵심 셀 + 결합 최악
CASES = [
    (0.0, 0.0, 1.0),                            # 기준(τ 없음)
    (5.0, 0.0, 1.0),                            # 강풍 방향 복구 확인 축([D-042] P4a)
    (10.0, 0.0, 1.0),                           # τ 단독 최대
    (10.0, 0.0, 0.5), (10.0, 0.3, 0.5),         # ★ 결합 최악(판정 기준)
]
TAU_USED_MULT = (0.0, 0.5, 0.8, 1.0, 1.5)        # 0.0 = 재구성 안 함(=2.G 기준선)


def run_one(seed, ov, tau, var_pct, warm_mult, tau_used_mult, floor_pct):
    cfg = Config(mode="ours", seed=seed, sensor_tau_s=tau, sensor_tau_var_pct=var_pct,
                 warm_scale=Config().warm_scale * warm_mult, **ov)
    tau_used = tau * tau_used_mult
    eng = Engine(cfg)
    rec_est = Estimator(cfg, neighbors=eng.net.neighbors)
    fed = set()
    tf = None
    rows = []
    for snap in eng.stream():
        t = snap["t"]
        if tf is None:
            tf = TrueFront(eng.fire)
        # 새로 확정된 사망 → **그 시점 rep_hist**로 재구성해 병렬 estimator에 투입
        new = []
        for uid, (x, y, t_obs) in eng.estimator.deaths.items():
            if uid in fed:
                continue
            fed.add(uid)
            td = t_obs
            if tau_used > 0:
                tr = recon_cross_time(eng.net.rep_hist.get(uid, []), tau_used,
                                      cfg.temp_threshold)
                if tr is not None:
                    td = tr
            new.append({"id": uid, "pos": (x, y), "death_t_est": td})
        if new:
            rec_est.update(new, t, None)
        if not rec_est.per_node or abs(t - round(t)) > 1e-9:
            continue
        band = speed_band(rec_est)
        if band is None:
            continue
        v_lo, v_hi, med = band
        v_lo2 = min(v_lo, med * (1 - floor_pct / 100.0))
        v_hi2 = max(v_hi, med * (1 + floor_pct / 100.0))
        front = np.array(eng.fire.front_pos(t), dtype=float)
        nvec = np.array(eng.fire._dir_at(t), dtype=float)
        for d in ETA_DISTS:
            p = front + nvec * d
            ta = tf.arrival(p)
            loc = nearest_local(rec_est, p)
            if ta is None or loc is None:
                continue
            u = np.array(loc["dir"], dtype=float)
            s_axis = float(u @ (p - np.array(loc["pos"], dtype=float)))
            if s_axis <= 0:
                continue
            base_t = loc["t"] - t
            rows.append({"dist": d, "eta_true": ta - t,
                         "e2_early": base_t + s_axis / v_hi2,
                         "e2_late": base_t + s_axis / v_lo2})
    dir_err = angle_deg(rec_est.dir_global, cfg.direction()) if rec_est.dir_global else None
    return rows, dir_err


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

    floors = {}
    p = os.path.join(OUTDIR, "summary_2e3_20_floor_decomposition.csv")
    for r in csv.DictReader(open(p, encoding="utf-8")):
        fs = float(r["F_sampling_physics"]) if r.get("F_sampling_physics") else 0.0
        floors[r["scenario"]] = max(fs, float(r["floor_canonical_vs_bar"] or 0.0))

    print("#2e-3 Step 2.H · Step 2a — 재구성 사망시각 + 2.G τ 게이트 재실행")
    print("  ★판정은 **위험측(breach_early)으로만**. 잔차 지표는 관대해서 쓰지 않는다(Step 1 결함 2).")
    print("  기준: 결합최악(W×0.5 ∧ τ=10 s) E3x2 위험측 19.3 % → ≤10 % 면 (C)→(B) 완화\n")

    bias = derive_bias_at_W0(seeds)      # S1·W0·τ=0, 재적합 없음
    rows = []
    for name, ov in EVAL:
        fl = floors.get(name, 0.0)
        for tau, vp, wm in CASES:
            for um in TAU_USED_MULT:
                if tau == 0.0 and um != 0.0:
                    continue                      # τ=0 세계는 재구성 대상 아님
                R, D = [], []
                for sd in seeds:
                    r, de = run_one(sd, ov, tau, vp, wm, um, fl)
                    R += r
                    if de is not None:
                        D.append(de)
                for d in ETA_DISTS:
                    sub = [x for x in R if x["dist"] == d]
                    if not sub:
                        continue
                    q05, q95 = bias[d]
                    tr = np.array([x["eta_true"] for x in sub])
                    lo0 = np.array([x["e2_early"] for x in sub])
                    hi0 = np.array([x["e2_late"] for x in sub])
                    rec = {"scenario": name, "tau_s": tau, "var_pct": vp, "warm_mult": wm,
                           "tau_used_mult": um, "dist_m": d, "n": len(sub),
                           "dir_deg": round(float(np.mean(D)), 3) if D else None}
                    for tag, sl, sh in (("E3x", -q95 * EXPAND_R, -q05 * EXPAND_R_HI),
                                        ("E3x2", 0.0, -q05 * EXPAND_R_HI)):
                        lo, hi = lo0 + sl, hi0 + sh
                        rec[f"{tag}_cov"] = round(float(((tr >= lo) & (tr <= hi)).mean()) * 100, 1)
                        rec[f"{tag}_be"] = round(float((tr < lo).mean()) * 100, 1)
                        rec[f"{tag}_w"] = round(float((hi - lo).mean()), 1)
                    rows.append(rec)
        print(f"  [{name:9s}] 완료")
    write_csv(os.path.join(args.outdir, "summary_2e3_H2_recon_gate.csv"), rows)

    # ---------------- 결합 최악 ----------------
    print("\n" + "=" * 104)
    print("★ 결합 최악(W×0.5 ∧ τ=10 s) — E3x2 위험측이 재구성으로 내려가나  ← 유일 판정 기준")
    print("=" * 104)
    print(f"  {'τ_used/τ':>9s} {'모드':9s} | "
          + "".join(f"{int(d)}m 커버/★위험".rjust(20) for d in ETA_DISTS) + "  최악")
    for vp, mode in ((0.0, "uniform"), (0.3, "variable")):
        for um in TAU_USED_MULT:
            sel = [r for r in rows if r["warm_mult"] == 0.5 and r["var_pct"] == vp
                   and r["tau_used_mult"] == um]
            if not sel:
                continue
            cells = []
            for d in ETA_DISTS:
                s = [r for r in sel if r["dist_m"] == d]
                cells.append(f"{np.mean([x['E3x2_cov'] for x in s]):7.1f}/"
                             f"{np.mean([x['E3x2_be'] for x in s]):6.1f}".rjust(20))
            wcell = max(r["E3x2_be"] for r in sel)
            tag = "  ← 2.G 기준선(재구성 없음)" if um == 0.0 else ""
            print(f"  {um:9.1f} {mode:9s} | " + "".join(cells) + f"  {wcell:5.1f}%{tag}")

    print("\n" + "=" * 104)
    print("★ 강풍 축 방향 복구 (S2a 20°) — 재구성이 [D-042] P4a 손상을 되돌리나")
    print("=" * 104)
    print(f"  {'τ':>5s} {'모드':9s} {'W배율':>6s} " + "".join(f"τ_used={m:<5.1f}".rjust(14) for m in TAU_USED_MULT))
    for tau, vp, wm in CASES:
        cells = []
        for um in TAU_USED_MULT:
            s = [r for r in rows if r["scenario"] == "S2a_20" and r["tau_s"] == tau
                 and r["var_pct"] == vp and r["warm_mult"] == wm and r["tau_used_mult"] == um]
            cells.append((f"{s[0]['dir_deg']:14.3f}" if s and s[0]["dir_deg"] is not None
                          else f"{'-':>14s}"))
        print(f"  {tau:5.1f} {'variable' if vp else 'uniform':9s} {wm:6.1f} " + "".join(cells))

    # ---------------- 판정 ----------------
    base = max((r["E3x2_be"] for r in rows if r["warm_mult"] == 0.5 and r["tau_used_mult"] == 0.0),
               default=0.0)
    best_um, best_v = None, 1e9
    for um in TAU_USED_MULT:
        if um == 0.0:
            continue
        w = max((r["E3x2_be"] for r in rows if r["warm_mult"] == 0.5 and r["tau_used_mult"] == um),
                default=1e9)
        if w < best_v:
            best_um, best_v = um, w
    rob = max((r["E3x2_be"] for r in rows if r["warm_mult"] == 0.5
               and r["tau_used_mult"] in (0.5, 0.8, 1.0, 1.2, 1.5)), default=0.0)
    print("\n" + "=" * 104)
    print("★ 판정 (위험측 기준만)")
    print("=" * 104)
    print(f"  결합최악 E3x2 최악 위험측:  재구성 없음 {base:.1f} %  →  최적 τ_used({best_um:.1f}×) {best_v:.1f} %")
    print(f"  τ_used 미스매치 ±50 % 전 범위 최악 = {rob:.1f} %")
    if rob <= 10.0:
        v = (f"(C)→(B) **완화 성공**. τ를 ±50 % 이내로 실측하면 결합 위험이 팽창으로 흡수됨"
             f"(전 범위 최악 {rob:.1f} %)")
    elif best_v <= 10.0:
        v = (f"부분 완화 — τ_used={best_um:.1f}×에서만 {best_v:.1f} %로 내려감. "
             f"미스매치 전 범위로는 {rob:.1f} % → **τ 정밀 실측 전제 하에서만 (B)**")
    else:
        v = f"(C) 유지 — 재구성으로도 결합최악 위험측 {rob:.1f} %. null 결과 그대로 보고"
    print(f"\n  → **{v}**")


if __name__ == "__main__":
    main()
