"""run_2e3_diagnose.py — #2e-3 Step 1 · 속도/ETA 오차의 '분해 진단' (측정만).

★ 규율: `sim/` 무수정. estimator·verification·방어 파라미터 일절 불변.
  Engine이 이미 노출하는 ground-truth(`fire._positions`·`_dir_at`·`_speed_at`·`_radii`)만 읽고,
  반사실 재적합은 **신선한 Estimator 인스턴스**로만 한다(#2e-1 [D-032]과 같은 방식).

측정 항목
---------
1a 부호 포함 속도 오차 `(v̂ − v_true)/v_true` 분포 → **편향(bias) vs 산포(variance)** 판정.
1b **환원 불가 하한(floor)**:
    참 전선의 **실제 궤적**으로 각 노드의 정확한 도달시각 T_act(p)를 구하고, 거기에 estimator와
    **같은 수학(평면 최소제곱 → 1/|∇T|)**을 노이즈 없이 전역 적합했을 때의 속도 오차.
    = "완벽한 데이터 + 상수속도 모델"의 한계 → 어떤 알고리즘도 이 아래로 못 간다.
    ※ 참 속도의 시간변동 통계(std/min/max)도 같이 낸다. 다만 바람 θ요동만 있는 S2a는 참 속도가
      **상수**라 '속도 시간변동'만으로는 floor가 0이 된다 → 방향 요동이 만드는 **도달시각면의 비평면성**까지
      포함해야 진짜 하한이므로, 위처럼 실제 도달시각면에 상수속도 모델을 적합하는 방식으로 정의했다.
1c 오라클 절단: (i) 사망시각 노이즈 제거 (ii) 배치 오차 제거 (iii) 둘 다 → 지배 항 특정.
    (extra) 국소창(dt_window·min_samples) 제약 제거 = 전역 적합 → 표본 분할 효과 분리.
1d ETA 오차(초, 부호 포함): 현재 전선 전방 30/60/100 m 목표점에 대해 매 1초 샘플.
    **부호 규약(명시):** `err = ETA_pred − ETA_true`.
      err > 0 = 실제보다 **늦게** 온다고 예측 = 대피 여유를 과대평가 = **위험측(dangerous)**
      err < 0 = 실제보다 **일찍** 온다고 예측 = 조기 경보 = **보수측(safe)**
    (지시서 문구 "실제보다 빠르게(=위험하게)"는 해석이 갈릴 수 있어, 물리적 위험 방향으로 정의하고 양쪽 다 보고한다.)

산출물: results/stress/ 의 summary_2e3_1a_signed.csv · _1b_floor.csv · _1c_ablation.csv · _1d_eta.csv
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

OUTDIR = os.path.join("results", "stress")
GRIDS = {9: (3, 3), 12: (4, 3), 16: (4, 4), 20: (4, 5), 25: (5, 5)}
ETA_DISTS = (30.0, 60.0, 100.0)

# 평가 시나리오. (이름, overrides, 1b/1c 대상 여부)
SCENARIOS = [
    ("S1",        {}),
    ("S2a_5",     {"wind_noise_deg": 5.0}),
    ("S2a_10",    {"wind_noise_deg": 10.0}),
    ("S2a_20",    {"wind_noise_deg": 20.0}),
    ("S2b_20",    {"wind_speed_var_pct": 0.2}),
    ("S2b_40",    {"wind_speed_var_pct": 0.4}),
    ("S4_20",     {"placement_jitter": 0.2}),
    ("S4_40",     {"placement_jitter": 0.4}),
    ("S6_n9",     {"grid_rows": 3, "grid_cols": 3, "p_dropout": 0.05}),
    ("S6_n12",    {"grid_rows": 3, "grid_cols": 4, "p_dropout": 0.05}),
    ("S6_n25",    {"grid_rows": 5, "grid_cols": 5, "p_dropout": 0.05}),
    ("S7_worst",  {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                   "placement_jitter": 0.2, "p_dropout": 0.10}),
]


# ---------------- 참 전선의 '실제' 도달시각 ----------------
class TrueFront:
    """fire의 적분된 궤적에서 임의 점의 **정확한** 도달시각을 복원한다(명목 기준선 T_true와 다름).

    비방사: 시각 t_k에서 전선은 위치 `positions[k]`를 지나고 법선 `dir_at(t_k)`인 평면.
            점 p의 부호거리 g(k) = (p − positions[k])·n(t_k) 가 처음 0 이하가 되는 시각.
    방사  : |p − start| ≤ radii[k]·dir_factor(φ_p) 가 처음 성립하는 시각.
    """

    def __init__(self, fire):
        self.fire = fire
        self.dt = fire._dt
        K = len(fire._positions)
        self.ts = np.arange(K) * self.dt
        if not fire.radial:
            self.pos = np.asarray(fire._positions, dtype=float)
            self.dirs = np.array([fire._dir_at(float(t)) for t in self.ts], dtype=float)
        self.radii = np.asarray(fire._radii, dtype=float)

    def arrival(self, p):
        p = np.asarray(p, dtype=float)
        if self.fire.radial:
            phi = self.fire._angle_of(p)
            target = float(np.linalg.norm(p - self.fire.start)) / self.fire._dir_factor(phi)
            g = self.radii - target                      # 0 이상이면 도달
            idx = np.nonzero(g >= 0.0)[0]
        else:
            g = ((p - self.pos) * self.dirs).sum(axis=1)  # 양수면 아직 전선 앞
            idx = np.nonzero(g <= 0.0)[0]
        if idx.size == 0:
            return None
        k = int(idx[0])
        if k == 0:
            return float(self.ts[0])
        g0, g1 = float(g[k - 1]), float(g[k])            # 선형 보간으로 교차 시각
        if g1 == g0:
            return float(self.ts[k])
        frac = g0 / (g0 - g1)
        return float(self.ts[k - 1] + frac * self.dt)

    def speed_stats(self, t_lo, t_hi):
        """활성 구간의 참 전선 속도 통계(시간 변동 그 자체)."""
        ts = self.ts[(self.ts >= t_lo) & (self.ts <= t_hi)]
        if ts.size == 0:
            return None
        v = np.array([self.fire._speed_at(float(t)) for t in ts], dtype=float)
        return {"mean": float(v.mean()), "std": float(v.std()),
                "min": float(v.min()), "max": float(v.max())}


# ---------------- 반사실 적합 유틸 (원 estimator를 라이브러리로 호출) ----------------
def fit_speed_dir(cfg, neighbors, deaths_map, global_fit=False):
    """deaths_map(id→(x,y,t))로 신선한 Estimator를 적합해 (dir, speed) 반환.

    global_fit=True 면 국소창 제약 없이 **전체 사망 집합에 평면 하나**를 적합(같은 수학, 표본만 전역).
    """
    if global_fit:
        if len(deaths_map) < cfg.min_samples:
            return None, None
        A = np.array([[x, y, 1.0] for (x, y, _t) in deaths_map.values()])
        b = np.array([t for (_x, _y, t) in deaths_map.values()])
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        g = np.array([sol[0], sol[1]])
        n = float(np.linalg.norm(g))
        if n <= cfg.eps:
            return None, None
        return (float(g[0] / n), float(g[1] / n)), float(1.0 / n)
    est = Estimator(cfg, neighbors=neighbors)
    out = est.update([{"id": i, "pos": (x, y), "death_t_est": t}
                      for i, (x, y, t) in deaths_map.items()], 0.0, None)
    return out["dir"], out["speed"]


def rel_err(v, v_true):
    return None if v is None else (v - v_true) / v_true * 100.0


# ---------------- 단일 실행 ----------------
def run_one(seed, ov):
    cfg = Config(mode="ours", seed=seed, **ov)
    eng = Engine(cfg)

    tf = None
    eta_rows = []
    t_final = 0.0
    for snap in eng.stream():
        t = snap["t"]
        t_final = t
        if tf is None:
            tf = TrueFront(eng.fire)
        # 1d: 추정이 살아있고 표본이 최소 요건을 넘긴 뒤부터 1초 간격 샘플
        if eng.estimator.per_node and abs(t - round(t)) < 1e-9:
            if eng.fire.radial:
                continue
            front = np.array(eng.fire.front_pos(t), dtype=float)
            nvec = np.array(eng.fire._dir_at(t), dtype=float)
            for d in ETA_DISTS:
                p = front + nvec * d
                ta = tf.arrival(p)
                tp = eng.estimator.predict_arrival(p)
                if ta is None or tp is None:
                    continue
                eta_rows.append({"dist": d, "t": t,
                                 "eta_true": ta - t, "eta_pred": tp - t,
                                 "err": (tp - t) - (ta - t)})

    s = eng.summarize()
    deaths_map = dict(eng.estimator.deaths)
    v_true = cfg.speed_true

    out = {
        "seed": seed, "n_deaths": len(deaths_map),
        "dir_err_deg": s["final_dir_err_deg"],
        "speed_obs": eng.estimator.speed_global,
        "speed_rel_err_signed": rel_err(eng.estimator.speed_global, v_true),
        "eta_rows": eta_rows,
    }

    # ---- 1b floor: 실제 도달시각 + 노이즈 0 + 전역 적합 ----
    exact = {}
    for nd in eng.nodes:
        if nd.is_sink:
            continue
        ta = tf.arrival(nd.pos)
        if ta is not None:
            exact[nd.id] = (nd.pos[0], nd.pos[1], ta)
    d_f, v_f = fit_speed_dir(cfg, eng.net.neighbors, exact, global_fit=True)
    out["speed_floor"] = v_f
    out["speed_floor_rel_err_signed"] = rel_err(v_f, v_true)
    out["dir_floor_err_deg"] = angle_deg(d_f, cfg.direction()) if d_f else None
    tlo = min((t for (_x, _y, t) in exact.values()), default=0.0)
    thi = max((t for (_x, _y, t) in exact.values()), default=t_final)
    ss = tf.speed_stats(tlo, thi)
    out["v_true_std_pct"] = (ss["std"] / ss["mean"] * 100.0) if ss and ss["mean"] else 0.0
    out["v_true_range_pct"] = ((ss["max"] - ss["min"]) / ss["mean"] * 100.0) if ss and ss["mean"] else 0.0

    # ---- 1c(i): 사망시각 노이즈만 제거 (채택 집합·국소창은 그대로) ----
    denoised = {i: (x, y, exact[i][2]) for i, (x, y, _t) in deaths_map.items() if i in exact}
    _d, v_i = fit_speed_dir(cfg, eng.net.neighbors, denoised)
    out["speed_no_time_noise"] = rel_err(v_i, v_true)

    # ---- 1c(extra): 관측 그대로 + 전역 적합(국소창 제약만 제거) ----
    _d, v_g = fit_speed_dir(cfg, eng.net.neighbors, deaths_map, global_fit=True)
    out["speed_global_fit"] = rel_err(v_g, v_true)

    return out


# ---------------- 집계 ----------------
def q(vals, name=""):
    a = np.array([v for v in vals if v is not None and not math.isnan(v)], dtype=float)
    if a.size == 0:
        return {}
    return {f"{name}mean": round(float(a.mean()), 3), f"{name}std": round(float(a.std()), 3),
            f"{name}median": round(float(np.median(a)), 3),
            f"{name}p10": round(float(np.percentile(a, 10)), 3),
            f"{name}p90": round(float(np.percentile(a, 90)), 3),
            f"{name}absmean": round(float(np.abs(a).mean()), 3), f"{name}n": int(a.size)}


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

    print("#2e-3 Step 1 · 속도/ETA 오차 분해 진단 (측정만, sim/ 무수정)")
    print(f"  시나리오 {len(SCENARIOS)}종 × {args.seeds}시드\n")

    data = {}
    for name, ov in SCENARIOS:
        runs = [run_one(sd, ov) for sd in seeds]
        # 1c(ii)/(iii): 배치 오차 제거 = placement_jitter 0 으로 되돌린 대조 실행
        ov2 = {k: v for k, v in ov.items() if k != "placement_jitter"}
        has_jit = "placement_jitter" in ov
        runs_nojit = [run_one(sd, ov2) for sd in seeds] if has_jit else runs
        data[name] = (runs, runs_nojit, has_jit)
        print(f"  [{name:9s}] 완료  관측 속도오차(부호) "
              f"{q([r['speed_rel_err_signed'] for r in runs])['mean']:+8.2f} %  "
              f"floor {q([r['speed_floor_rel_err_signed'] for r in runs])['mean']:+7.2f} %")

    # ---------------- 1a ----------------
    rows_a = []
    for name, _ in SCENARIOS:
        runs = data[name][0]
        st = q([r["speed_rel_err_signed"] for r in runs])
        bias, sd = st["mean"], st["std"]
        rows_a.append({"scenario": name, **st,
                       "bias_abs": round(abs(bias), 3),
                       "bias_over_std": (round(abs(bias) / sd, 3) if sd > 1e-9 else None),
                       "verdict": ("bias-dominant(구조)" if sd > 1e-9 and abs(bias) / sd >= 1.0
                                   else ("variance-dominant(노이즈)" if sd > 1e-9 else "deterministic"))})
    write_csv(os.path.join(args.outdir, "summary_2e3_1a_signed.csv"), rows_a)

    # ---------------- 1b ----------------
    rows_b = []
    for name, _ in SCENARIOS:
        runs = data[name][0]
        obs = q([abs(r["speed_rel_err_signed"]) for r in runs if r["speed_rel_err_signed"] is not None])
        flo = q([abs(r["speed_floor_rel_err_signed"]) for r in runs if r["speed_floor_rel_err_signed"] is not None])
        share = (flo["mean"] / obs["mean"] * 100.0) if obs.get("mean") else None
        rows_b.append({
            "scenario": name,
            "v_true_std_pct": round(float(np.mean([r["v_true_std_pct"] for r in runs])), 3),
            "v_true_range_pct": round(float(np.mean([r["v_true_range_pct"] for r in runs])), 3),
            "obs_abs_err_pct": obs.get("mean"), "obs_std": obs.get("std"),
            "floor_abs_err_pct": flo.get("mean"), "floor_std": flo.get("std"),
            "floor_share_pct": None if share is None else round(share, 1),
            "floor_dir_err_deg": round(float(np.mean([r["dir_floor_err_deg"] for r in runs
                                                      if r["dir_floor_err_deg"] is not None])), 3),
        })
    write_csv(os.path.join(args.outdir, "summary_2e3_1b_floor.csv"), rows_b)

    # ---------------- 1c ----------------
    rows_c = []
    for name, _ in SCENARIOS:
        runs, runs_nojit, has_jit = data[name]
        def am(rs, k):
            v = [abs(r[k]) for r in rs if r.get(k) is not None]
            return round(float(np.mean(v)), 3) if v else None
        rows_c.append({
            "scenario": name,
            "observed": am(runs, "speed_rel_err_signed"),
            "no_death_time_noise": am(runs, "speed_no_time_noise"),
            "no_placement_jitter": am(runs_nojit, "speed_rel_err_signed") if has_jit else "N/A(무지터)",
            "both_removed": am(runs_nojit, "speed_no_time_noise") if has_jit else am(runs, "speed_no_time_noise"),
            "global_fit_only": am(runs, "speed_global_fit"),
            "floor": am(runs, "speed_floor_rel_err_signed"),
        })
    write_csv(os.path.join(args.outdir, "summary_2e3_1c_ablation.csv"), rows_c)

    # ---------------- 1d ----------------
    rows_d = []
    for name, _ in SCENARIOS:
        runs = data[name][0]
        for d in ETA_DISTS:
            errs = [e["err"] for r in runs for e in r["eta_rows"] if e["dist"] == d]
            tru = [e["eta_true"] for r in runs for e in r["eta_rows"] if e["dist"] == d]
            if not errs:
                continue
            a = np.array(errs, dtype=float)
            rows_d.append({
                "scenario": name, "dist_m": d, "n_samples": int(a.size),
                "eta_true_mean_s": round(float(np.mean(tru)), 2),
                "err_mean_s": round(float(a.mean()), 3), "err_std_s": round(float(a.std()), 3),
                "err_median_s": round(float(np.median(a)), 3),
                "err_p10_s": round(float(np.percentile(a, 10)), 3),
                "err_p90_s": round(float(np.percentile(a, 90)), 3),
                "abs_err_mean_s": round(float(np.abs(a).mean()), 3),
                # err>0 = 실제보다 늦게 온다고 예측 = 여유 과대평가 = 위험측
                "dangerous_share_pct": round(float((a > 0).mean() * 100), 1),
                "safe_share_pct": round(float((a < 0).mean() * 100), 1),
                "dangerous_p90_s": round(float(np.percentile(a, 90)), 3),
            })
    write_csv(os.path.join(args.outdir, "summary_2e3_1d_eta.csv"), rows_d)

    # ---------------- 콘솔 ----------------
    print("\n" + "=" * 96)
    print("1a · 부호 포함 속도 오차 (%)  — bias/std ≥ 1 이면 구조(편향) 지배")
    print("=" * 96)
    print(f"  {'시나리오':10s} {'평균':>9s} {'중앙':>9s} {'std':>8s} {'p10':>9s} {'p90':>9s} "
          f"{'|평균|/std':>10s}  판정")
    for r in rows_a:
        print(f"  {r['scenario']:10s} {r['mean']:+9.2f} {r['median']:+9.2f} {r['std']:8.2f} "
              f"{r['p10']:+9.2f} {r['p90']:+9.2f} "
              f"{(r['bias_over_std'] if r['bias_over_std'] is not None else float('nan')):10.2f}  {r['verdict']}")

    print("\n" + "=" * 96)
    print("1b · 환원 불가 하한(floor)  — floor 비중 ≥ 70 % 면 Step 2 중단")
    print("=" * 96)
    print(f"  {'시나리오':10s} {'참속도 std%':>11s} {'참속도 범위%':>12s} {'관측 |오차|%':>12s} "
          f"{'floor %':>9s} {'floor 비중%':>11s} {'floor 방향°':>11s}")
    for r in rows_b:
        print(f"  {r['scenario']:10s} {r['v_true_std_pct']:11.2f} {r['v_true_range_pct']:12.2f} "
              f"{r['obs_abs_err_pct']:12.2f} {r['floor_abs_err_pct']:9.2f} "
              f"{(r['floor_share_pct'] if r['floor_share_pct'] is not None else float('nan')):11.1f} "
              f"{r['floor_dir_err_deg']:11.2f}")

    print("\n" + "=" * 96)
    print("1c · 오라클 절단 (|속도 오차| %)")
    print("=" * 96)
    print(f"  {'시나리오':10s} {'관측':>9s} {'사망시각노이즈X':>15s} {'배치지터X':>11s} "
          f"{'둘 다 X':>9s} {'전역적합만':>11s} {'floor':>8s}")
    for r in rows_c:
        def f(v):
            return f"{v:9.2f}" if isinstance(v, (int, float)) else f"{str(v):>9s}"
        print(f"  {r['scenario']:10s} {f(r['observed'])} {f(r['no_death_time_noise']):>15s} "
              f"{f(r['no_placement_jitter']):>11s} {f(r['both_removed'])} "
              f"{f(r['global_fit_only']):>11s} {f(r['floor']):>8s}")

    print("\n" + "=" * 96)
    print("1d · ETA 오차 (초)  ·  err = ETA_pred − ETA_true")
    print("     err>0 = 실제보다 늦게 온다고 예측 = 대피여유 과대평가 = ★위험측")
    print("=" * 96)
    print(f"  {'시나리오':10s} {'거리':>5s} {'참ETA':>7s} {'평균':>8s} {'중앙':>8s} {'std':>7s} "
          f"{'|평균|':>7s} {'위험측%':>8s} {'p90(초)':>8s}")
    for r in rows_d:
        print(f"  {r['scenario']:10s} {r['dist_m']:5.0f} {r['eta_true_mean_s']:7.1f} "
              f"{r['err_mean_s']:+8.2f} {r['err_median_s']:+8.2f} {r['err_std_s']:7.2f} "
              f"{r['abs_err_mean_s']:7.2f} {r['dangerous_share_pct']:8.1f} {r['dangerous_p90_s']:+8.2f}")

    # ---------------- 판정 ----------------
    print("\n" + "=" * 96)
    print("판정 (정지 조건: floor 비중 ≥ 70 % → Step 2 중단)")
    print("=" * 96)
    key = [r for r in rows_b if r["scenario"] in ("S1", "S2a_20", "S6_n9", "S7_worst")]
    for r in key:
        v = r["floor_share_pct"]
        mark = "★ floor 지배 → 개선 여지 작음" if (v is not None and v >= 70) else "개선 여지 있음"
        print(f"  {r['scenario']:10s} floor 비중 {v:6.1f} %  → {mark}")
    vals = [r["floor_share_pct"] for r in key if r["floor_share_pct"] is not None]
    if vals:
        print(f"\n  핵심 4종 floor 비중 평균 = {np.mean(vals):.1f} %  → "
              f"{'STOP(하한 지배)' if np.mean(vals) >= 70 else 'CONTINUE(Step 2 진행 가치 있음)'}")


if __name__ == "__main__":
    main()
