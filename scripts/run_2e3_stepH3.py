"""run_2e3_stepH3.py — #2e-3 Step 2.H **Step 2b** · 방법 C(dT/dt 독립 속도) + L 미스매치 게이트.

방법 C: 예열 구간의 온도장이 `T(d) = T_amb + ΔT·exp(−d/L)` 이고 화선이 속도 v로 접근하면
    dT/dt = (v/L)·(T − T_amb)   ⟹   **v = L · (dT/dt) / (T − T_amb)**
노드 하나가 **자기 온도 곡선만으로** 속도를 낸다 — 평면적합·역수·이웃 불필요 → 기하 추정과 독립.

★ 착수 전 해석적 예측 (측정 전에 적는다)
──────────────────────────────────────────────────────────────────────────────
**v는 L에 정비례한다.** 따라서 L을 x배 틀리게 주면 속도 추정도 **정확히 x배** 틀린다.
[D-043] Step 2a의 τ 재구성과는 성격이 다르다 — 거기서는 미스매치가 부분적으로 흡수됐지만,
여기서는 **L 오차가 1차로 그대로 전이**된다. ⇒ **L ±50 %면 속도 오차 ±50 %가 그냥 실린다**고 예상.
그러면 게이트를 통과 못 하고, 지시서대로 **"캘리브레이션 전제 발전방향"으로만** 기재해야 한다.
→ 예측이 맞든 틀리든 그대로 보고한다.
──────────────────────────────────────────────────────────────────────────────

규율
----
· **god-view 금지**: dT/dt는 `network.rep_hist`(메시가 실제 수신한 보고 온도)에서만.
· **예열 밴드에서만** 계산: `T_amb+10 ~ warn_temp(60 ℃)`. 점화 근방은 포화·비선형이라 제외
  (이 선택은 **물리 근거**지 점수 튜닝이 아니다).
· 노드별 v를 **중앙값**으로 집계(로버스트). 평가 기준은 **관측창 평균 참속도 T_bar**([D-038] ⓐ).
· 융합 가중치는 **S1 잔차 분산**에서 도출(테스트 점수 금지). 게이트 통과 시에만 융합 평가.
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
from scripts.run_2e3_diagnose import TrueFront
from scripts.run_2e3_stepE import OUTDIR

L_MULT = (0.5, 0.7, 0.8, 1.0, 1.2, 1.3, 1.5)
EVAL = [
    ("S1",       {}),
    ("S2a_10",   {"wind_noise_deg": 10.0}),
    ("S2a_20",   {"wind_noise_deg": 20.0}),
    ("S6_n9",    {"grid_rows": 3, "grid_cols": 3, "p_dropout": 0.05}),
    ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                  "placement_jitter": 0.2, "p_dropout": 0.10}),
]


def method_c_speed(eng, cfg, L_used):
    """예열 밴드에서 v = L·(dT/dt)/(T−T_amb). 노드별 중앙값 → 전체 중앙값."""
    lo = cfg.ambient + 10.0
    hi = cfg.warn_temp
    per_node = []
    for uid, hist in eng.net.rep_hist.items():
        if len(hist) < 2:
            continue
        ts = np.array([h[0] for h in hist], dtype=float)
        Ts = np.array([h[1] for h in hist], dtype=float)
        if np.ptp(ts) < 1e-9:
            continue
        d = np.gradient(Ts, ts)
        vs = []
        for i in range(Ts.size):
            T = Ts[i]
            if not (lo <= T < hi):          # 예열 밴드에서만(점화 근방 제외)
                continue
            denom = T - cfg.ambient
            if denom <= 1e-6 or d[i] <= 0:
                continue
            vs.append(L_used * d[i] / denom)
        if vs:
            per_node.append(float(np.median(vs)))
    return float(np.median(per_node)) if per_node else None, len(per_node)


def run_one(seed, ov, tau=0.0):
    cfg = Config(mode="ours", seed=seed, sensor_tau_s=tau, **ov)
    eng = Engine(cfg)
    for _ in eng.stream():
        pass
    tf = TrueFront(eng.fire)
    ex = [tf.arrival(nd.pos) for nd in eng.nodes if not nd.is_sink]
    ex = [x for x in ex if x is not None]
    ts = np.arange(min(ex), max(ex) + 1e-9, cfg.dt)
    T_bar = float(np.mean([eng.fire._speed_at(float(x)) for x in ts]))
    return cfg, eng, T_bar


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
    L0 = Config().warm_scale

    print("#2e-3 Step 2.H · Step 2b — 방법 C(dT/dt 독립 속도) + L 미스매치 게이트")
    print(f"  v = L·(dT/dt)/(T−T_amb),  예열 밴드 {Config().ambient+10:.0f}~{Config().warn_temp:.0f} ℃, L0={L0} m")
    print("  ★예측: v ∝ L 이라 L 오차가 1차로 그대로 전이 → ±50 % L이면 속도 ±50 % 예상(측정으로 확정)\n")

    rows = []
    for name, ov in EVAL:
        cache = [run_one(sd, ov) for sd in seeds]
        # 기하 속도(배포판 estimator) 기준
        ge = [(e.estimator.speed_global - tb) / tb * 100.0
              for _c, e, tb in cache if e.estimator.speed_global]
        for m in L_MULT:
            ce, nn = [], []
            for cfg, eng, tb in cache:
                v, n = method_c_speed(eng, cfg, L0 * m)
                if v:
                    ce.append((v - tb) / tb * 100.0)
                    nn.append(n)
            rows.append({"scenario": name, "L_mult": m,
                         "geo_signed": round(float(np.mean(ge)), 3) if ge else None,
                         "geo_abs": round(float(np.mean(np.abs(ge))), 3) if ge else None,
                         "C_signed": round(float(np.mean(ce)), 3) if ce else None,
                         "C_abs": round(float(np.mean(np.abs(ce))), 3) if ce else None,
                         "C_std": round(float(np.std(ce)), 3) if ce else None,
                         "n_nodes": round(float(np.mean(nn)), 1) if nn else 0})
        print(f"  [{name:9s}] 완료")
    write_csv(os.path.join(args.outdir, "summary_2e3_H3_methodC.csv"), rows)

    print("\n" + "=" * 100)
    print("★ 방법 C 속도 오차 vs L 미스매치  (부호 포함, 기준 = 관측창 평균 참속도)")
    print("=" * 100)
    print(f"  {'시나리오':9s} {'기하 |오차|':>10s} | " + "".join(f"L×{m:<4.1f}".rjust(11) for m in L_MULT))
    for name, _ in EVAL:
        sub = [r for r in rows if r["scenario"] == name]
        g = sub[0]["geo_abs"]
        cells = []
        for m in L_MULT:
            r = next(x for x in sub if x["L_mult"] == m)
            cells.append(f"{r['C_signed']:+11.1f}" if r["C_signed"] is not None else f"{'-':>11s}")
        print(f"  {name:9s} {g:10.2f} | " + "".join(cells))

    print("\n" + "=" * 100)
    print("★ L 미스매치 게이트 판정 — L×1.0 대비 오차가 어떻게 전이되나")
    print("=" * 100)
    print(f"  {'시나리오':9s} {'L×1.0 |오차|':>11s} {'L×0.5':>9s} {'L×1.5':>9s} {'전이 배율(0.5×)':>15s} {'전이 배율(1.5×)':>15s}")
    fails = 0
    for name, _ in EVAL:
        sub = {r["L_mult"]: r for r in rows if r["scenario"] == name}
        b = sub[1.0]["C_abs"]
        lo, hi = sub[0.5]["C_abs"], sub[1.5]["C_abs"]
        # v ∝ L 이므로 이론상 L×0.5 → 속도 절반, L×1.5 → 1.5배
        print(f"  {name:9s} {b:11.2f} {lo:9.2f} {hi:9.2f} "
              f"{(lo/b if b else float('nan')):15.2f} {(hi/b if b else float('nan')):15.2f}")
        if max(lo, hi) > 30.0:
            fails += 1
    print(f"\n  실용 밴드(속도 오차 <30 %)를 L ±50 %에서 벗어나는 시나리오 = {fails}/{len(EVAL)}")

    print("\n" + "=" * 100)
    print("★ 판정")
    print("=" * 100)
    s1 = {r["L_mult"]: r for r in rows if r["scenario"] == "S1"}
    print(f"  S1 기준: L×1.0 에서 방법 C 오차 {s1[1.0]['C_signed']:+.1f} % (std {s1[1.0]['C_std']:.1f}), "
          f"기하 {s1[1.0]['geo_signed']:+.1f} %")
    print(f"  S1 L×0.5 → {s1[0.5]['C_signed']:+.1f} % · L×1.5 → {s1[1.5]['C_signed']:+.1f} %")
    worst = max(abs(r["C_signed"]) for r in rows if r["L_mult"] in (0.5, 1.5)
                and r["C_signed"] is not None)
    if worst <= 30.0:
        v = f"게이트 통과(±50 % L에서 최악 {worst:.1f} %) → 융합 평가 진행 가치 있음"
    else:
        v = (f"**게이트 불통과**(±50 % L에서 최악 {worst:.1f} %) → 방법 C는 채택하지 않고 "
             f"**'캘리브레이션 전제 발전방향'으로만** 기재")
    print(f"\n  → **{v}**")


if __name__ == "__main__":
    main()
