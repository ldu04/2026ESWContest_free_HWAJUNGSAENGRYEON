"""run_2e3_floor_audit.py — #2e-3 Step 2.0 · floor 정당성 감사 ("물리인가, 방법인가").

★ 규율: estimator 불변. Step 1(`run_2e3_diagnose.py`)의 오라클 절단 기계를 그대로 재사용한다.

왜 하는가
---------
"floor = 물리적 한계"라는 서술은 **반대 방향의 과장**이 될 수 있다 — 고칠 수 있는 방법상 약점을
자연법칙인 척 변명하는 것. 그래서 floor를 네 갈래로 쪼개고, **오직 ⓓ(표본 해상도)만**
"물리적/기능적 한계"라고 부를 자격을 준다.

분해 정의 (본 스크립트가 실제로 계산하는 것)
--------------------------------------------
세 가지 '참값 기준(target)'을 명시적으로 구분한다. 하나로 뭉치면 감사가 성립하지 않는다.
  T_nom  = cfg.speed_true               (명목 상수. **Step 1이 쓴 기준**)
  T_bar  = 관측창 시간평균 참속도        (등속 추정량의 **올바른** 기준)
  T_inst = v_true(t) 순간 참속도         (시간가변 추정량이 겨눌 기준)

  F_metric   = |floor vs T_nom| − |floor vs T_bar|      … 기준 선택이 만든 허수
  F_spatial  = 참속도 std=0 시나리오에 남는 floor(vs T_bar) … 화선 곡률 vs 평면적합 미스매치
  F_temporal = (등속모델의 T_inst 대비 오차) − (선형램프 모델의 T_inst 대비 오차) … B가 회수 가능
  F_sampling = 사망 케이던스 Δt=L_node/v 의 나이퀴스트 한계를 넘는 속도요동 성분의 몫 … ★진짜 물리

주의: 이 스크립트는 Step 1 floor의 **정의 불일치**도 함께 보고한다(항목 0).
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
from scripts.run_2e3_diagnose import TrueFront, fit_speed_dir

OUTDIR = os.path.join("results", "stress")

SCENARIOS = [
    ("S1",       {}),
    ("S2a_5",    {"wind_noise_deg": 5.0}),
    ("S2a_10",   {"wind_noise_deg": 10.0}),
    ("S2a_20",   {"wind_noise_deg": 20.0}),
    ("S2b_20",   {"wind_speed_var_pct": 0.2}),
    ("S2b_40",   {"wind_speed_var_pct": 0.4}),
    ("S4_20",    {"placement_jitter": 0.2}),
    ("S6_n9",    {"grid_rows": 3, "grid_cols": 3, "p_dropout": 0.05}),
    ("S6_n25",   {"grid_rows": 5, "grid_cols": 5, "p_dropout": 0.05}),
    ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                  "placement_jitter": 0.2, "p_dropout": 0.10}),
]

FLOOR_SOURCE = '''\
# ── Step 1 (run_2e3_diagnose.run_one) 에서 floor 컬럼을 만든 코드 그대로 ──────────────
    exact = {}
    for nd in eng.nodes:
        if nd.is_sink:
            continue
        ta = tf.arrival(nd.pos)                 # 실제 궤적 기반 정확한 도달시각 T_act
        if ta is not None:
            exact[nd.id] = (nd.pos[0], nd.pos[1], ta)
    d_f, v_f = fit_speed_dir(cfg, eng.net.neighbors, exact, global_fit=True)   # ★ global_fit
    out["speed_floor"] = v_f
    out["speed_floor_rel_err_signed"] = rel_err(v_f, v_true)   # = (v_f - cfg.speed_true)/cfg.speed_true

# 그리고 global_fit=True 분기는:
        A = np.array([[x, y, 1.0] for (x, y, _t) in deaths_map.values()])
        b = np.array([t for (_x, _y, t) in deaths_map.values()])
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)      # 전 노드에 평면 '하나'
        g = np.array([sol[0], sol[1]]);  n = norm(g)
        return (g/n), 1.0/n                              # 속도 = 1/|∇T| (역수 유지)
# ──────────────────────────────────────────────────────────────────────────────────'''


def obs_window(exact):
    ts = [t for (_x, _y, t) in exact.values()]
    return (min(ts), max(ts)) if ts else (0.0, 0.0)


def audit_one(seed, ov):
    cfg = Config(mode="ours", seed=seed, **ov)
    eng = Engine(cfg)
    for _ in eng.stream():
        pass
    tf = TrueFront(eng.fire)
    fire = eng.fire

    exact = {}
    for nd in eng.nodes:
        if nd.is_sink:
            continue
        ta = tf.arrival(nd.pos)
        if ta is not None:
            exact[nd.id] = (nd.pos[0], nd.pos[1], ta)
    if len(exact) < cfg.min_samples:
        return None
    t0, t1 = obs_window(exact)

    # --- 세 가지 참값 기준 ---
    ts = np.arange(t0, t1 + 1e-9, cfg.dt)
    v_inst = np.array([fire._speed_at(float(t)) for t in ts], dtype=float)
    T_nom = cfg.speed_true
    T_bar = float(v_inst.mean()) if v_inst.size else T_nom

    # --- floor 두 정의: (1) Step1대로 전역적합 (2) 현 estimator(국소+중앙값) ---
    _d, v_glob = fit_speed_dir(cfg, eng.net.neighbors, exact, global_fit=True)
    _d2, v_loc = fit_speed_dir(cfg, eng.net.neighbors, exact, global_fit=False)

    def rel(v, ref):
        return None if (v is None or not ref) else abs(v - ref) / ref * 100.0

    # ★보강1: 관측 오차도 **같은 estimator(배포판 local+중앙값)**로 잰다.
    #   Step 1의 'floor 비중'은 분자=전역적합, 분모=배포판이라 **분모/분자가 다른 추정기**였다(오류).
    v_obs_est = eng.estimator.speed_global

    out = {
        "seed": seed,
        "v_true_std_pct": float(v_inst.std() / v_inst.mean() * 100.0) if v_inst.size else 0.0,
        "T_bar": T_bar, "T_bar_dev_pct": abs(T_bar - T_nom) / T_nom * 100.0,
        "obs_local_vs_nom": rel(v_obs_est, T_nom),
        "obs_local_vs_bar": rel(v_obs_est, T_bar),
        "floor_global_vs_nom": rel(v_glob, T_nom),
        "floor_global_vs_bar": rel(v_glob, T_bar),
        "floor_local_vs_nom": rel(v_loc, T_nom),
        "floor_local_vs_bar": rel(v_loc, T_bar),
    }
    # ★보강1: 전역적합 선택 자체가 만든 몫 = '방법'의 직접 증거.
    # ★부호 규약 통일(사용자 항목7): **항상 `local − global`**. 양수 = 배포판(국소+중앙값)이 더 나쁘다.
    #   F_definition(vs 명목)과 F_globalchoice(vs 창평균)는 **같은 비교의 두 기준**이지 서로 다른 축이 아니다.
    #   둘 다 **무노이즈 오라클**에서 잰 값이므로 **분산이 아니라 순수 편향(모델형)**이다.
    #   (분산 축은 1c에서만 드러난다: 노이즈가 있으면 전역이 더 나쁘고, 없으면 전역이 더 좋다.)
    if out["floor_global_vs_bar"] is not None and out["floor_local_vs_bar"] is not None:
        out["F_globalchoice"] = out["floor_local_vs_bar"] - out["floor_global_vs_bar"]

    # --- ⓑ 탐침: 국소 2차항을 추가하면 곡률 몫이 줄어드는가 (채택 아님, 여지 확인만) ---
    pts = np.array([[x, y] for (x, y, _t) in exact.values()], dtype=float)
    tv = np.array([t for (_x, _y, t) in exact.values()], dtype=float)
    if len(pts) >= 6:
        c = pts.mean(axis=0)
        dx, dy = pts[:, 0] - c[0], pts[:, 1] - c[1]
        M = np.column_stack([dx, dy, np.ones_like(dx), dx * dx, dx * dy, dy * dy])
        sol, *_ = np.linalg.lstsq(M, tv, rcond=None)
        g2 = np.array([sol[0], sol[1]])            # 중심에서의 기울기(2차항은 중심에서 0)
        n2 = float(np.linalg.norm(g2))
        out["floor_quad_vs_bar"] = rel(1.0 / n2, T_bar) if n2 > cfg.eps else None
    else:
        out["floor_quad_vs_bar"] = None

    # --- ⓒ 시간모델형: 무노이즈 오라클 s-vs-t 에 등속 vs 선형램프 ---
    u = np.array(cfg.direction(), dtype=float)
    s = pts @ u
    A1 = np.column_stack([np.ones_like(tv), tv])
    c1, *_ = np.linalg.lstsq(A1, s, rcond=None)          # s = a + v t        (등속)
    v_const = float(c1[1])
    A2 = np.column_stack([np.ones_like(tv), tv, tv ** 2])
    c2, *_ = np.linalg.lstsq(A2, s, rcond=None)          # s = a + b t + c t² (선형램프)
    v_ramp = c2[1] + 2.0 * c2[2] * ts

    def inst_err(vhat):
        e = np.abs(vhat - v_inst) / v_inst * 100.0
        return float(e.mean())

    out["err_const_vs_inst"] = inst_err(np.full_like(v_inst, v_const))
    out["err_ramp_vs_inst"] = inst_err(v_ramp)

    # --- ⓓ 나이퀴스트: 사망 케이던스보다 빠른 속도요동 = 원리적으로 관측 불가 ---
    #   케이던스 Δt = 노드 간격 / 속도. 관측 가능 최소 주기 = 2Δt (나이퀴스트).
    #   ★근사 대신 **정확히** 잰다: 돌풍 프로세스의 푸리에 성분을 알고 있으므로,
    #     ω ≤ ω_nyq 성분만 남긴 v_obs(t)를 재구성하면 그것이 "어떤 샘플러도 도달 못 하는 최선"이다.
    #     F_sampling = mean_t |v_obs(t) − v_inst(t)| / v_inst(t)  ← err_const 와 **같은 통계(MAE)**
    #   ★보강2: 경계는 **순간 속도에 따라 이동한다**. Δt(t)=spacing/v(t) → ω_cut(t)=π·v(t)/spacing.
    #     평균속도 기준 단일선(0.471)은 근사일 뿐이므로 범위와 시변 버전을 함께 낸다.
    #   ★보강4: '신호 분산 몫'(무차원)과 '추정오차 몫'(%)은 **다른 양**이다. 뒤섞지 않는다.
    #     변환식: F_sampling(%) = mean_t |v_obs(t) − v_inst(t)| / v_inst(t) × 100
    #       여기서 v_obs = ω ≤ ω_cut 성분만 남긴 대역제한 재구성 = "어떤 샘플러도 못 넘는 최선".
    #       기준은 **순간 참값 T_inst**다(창평균 T_bar 기준에는 이 항이 적용되지 않는다 —
    #       등속 추정량은 애초에 시간변동을 추적하지 않으므로 나이퀴스트 한계가 걸리지 않는다).
    dt_cad = cfg.spacing_m / T_bar
    w_nyq = math.pi * T_bar / cfg.spacing_m
    freqs, phases, amps = fire._speed_proc
    var_all = float(np.sum(0.5 * amps ** 2))
    var_fast = float(np.sum(0.5 * amps[freqs > w_nyq] ** 2))
    out["cadence_s"] = dt_cad
    out["w_cut_at_vbar"] = w_nyq
    out["unobservable_var_share_SIGNAL"] = (var_fast / var_all) if var_all > 1e-12 else 0.0
    if cfg.wind_speed_var_pct > 0 and ts.size:
        v_lo, v_hi = float(v_inst.min()), float(v_inst.max())
        out["w_cut_lo"] = math.pi * v_lo / cfg.spacing_m
        out["w_cut_hi"] = math.pi * v_hi / cfg.spacing_m
        out["cadence_lo_s"] = cfg.spacing_m / v_hi
        out["cadence_hi_s"] = cfg.spacing_m / v_lo

        def recon(mask_fn):
            proc = np.array([float(np.sum(amps[mask_fn(i)] * np.sin(freqs[mask_fn(i)] * t
                                                                    + phases[mask_fn(i)])))
                             for i, t in enumerate(ts)])
            return cfg.speed_true * np.maximum(0.1, 1.0 + cfg.wind_speed_var_pct * proc)

        # (a) 평균속도 기준 고정 컷오프(근사)
        v_fix = recon(lambda i: freqs <= w_nyq)
        out["F_sampling_pct"] = float((np.abs(v_fix - v_inst) / v_inst * 100.0).mean())
        # (b) 순간속도 기준 시변 컷오프(느린 골에서 더 많은 성분이 관측 불가)
        wcut_t = math.pi * v_inst / cfg.spacing_m
        v_var = recon(lambda i: freqs <= wcut_t[i])
        out["F_sampling_pct_timevar"] = float((np.abs(v_var - v_inst) / v_inst * 100.0).mean())
    else:
        out["F_sampling_pct"] = 0.0
        out["F_sampling_pct_timevar"] = 0.0
    return out


def m(rows, k):
    v = [r[k] for r in rows if r.get(k) is not None]
    return round(float(np.mean(v)), 3) if v else None


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
    cfg0 = Config()

    print("#2e-3 Step 2.0 · floor 정당성 감사 (estimator 불변)\n")
    print("=" * 100)
    print("항목 0 · Step 1의 floor를 만든 코드 (그대로 인용)")
    print("=" * 100)
    print(FLOOR_SOURCE)
    print()
    print("  ★ 정의 불일치 고지: 지시서는 'floor = 무노이즈 오라클에 **현 estimator**를 돌린 잔차'로")
    print("     가정했으나, 실제 코드는 **전 노드 전역 평면적합 1회 + 1/|∇T|** 였다.")
    print("     현 estimator의 '국소적합 + per-node 중앙값' 구조가 아니다.")
    print("     → 아래에서 **두 정의 모두** 계산해 나란히 싣고, 분해는 '현 estimator' 정의를 정본으로 쓴다.")
    print(f"\n  공통 상수: spacing={cfg0.spacing_m} m, speed_true={cfg0.speed_true} m/s, "
          f"dt_window={cfg0.dt_window} s, min_samples={cfg0.min_samples}")
    print(f"  돌풍 프로세스 주파수(rad/s) = {np.round(np.linspace(0.08, 0.55, 4), 4).tolist()} "
          f"(주기 {np.round(2*np.pi/np.linspace(0.08,0.55,4),1).tolist()} s)")

    raw, agg = [], []
    for name, ov in SCENARIOS:
        rows = [x for x in (audit_one(sd, ov) for sd in seeds) if x]
        for r in rows:
            r["scenario"] = name
        raw += rows
        a = {"scenario": name,
             "v_true_std_pct": m(rows, "v_true_std_pct"),
             "T_bar_dev_pct": m(rows, "T_bar_dev_pct"),
             "obs_local_vs_nom": m(rows, "obs_local_vs_nom"),
             "obs_local_vs_bar": m(rows, "obs_local_vs_bar"),
             "floor_global_vs_nom": m(rows, "floor_global_vs_nom"),
             "floor_global_vs_bar": m(rows, "floor_global_vs_bar"),
             "floor_local_vs_nom": m(rows, "floor_local_vs_nom"),
             "floor_local_vs_bar": m(rows, "floor_local_vs_bar"),
             "F_globalchoice": m(rows, "F_globalchoice"),
             "floor_quad_vs_bar": m(rows, "floor_quad_vs_bar"),
             "err_const_vs_inst": m(rows, "err_const_vs_inst"),
             "err_ramp_vs_inst": m(rows, "err_ramp_vs_inst"),
             "cadence_s": m(rows, "cadence_s"),
             "cadence_lo_s": m(rows, "cadence_lo_s"),
             "cadence_hi_s": m(rows, "cadence_hi_s"),
             "w_cut_at_vbar": m(rows, "w_cut_at_vbar"),
             "w_cut_lo": m(rows, "w_cut_lo"), "w_cut_hi": m(rows, "w_cut_hi"),
             "unobservable_var_share_SIGNAL": m(rows, "unobservable_var_share_SIGNAL"),
             "F_sampling_pct": m(rows, "F_sampling_pct"),
             "F_sampling_pct_timevar": m(rows, "F_sampling_pct_timevar")}
        agg.append(a)
        print(f"  [{name:9s}] floor(전역) vs명목 {a['floor_global_vs_nom']:6.2f} → vs창평균 "
              f"{a['floor_global_vs_bar']:6.2f} | floor(현estimator) vs창평균 {a['floor_local_vs_bar']:6.2f}")

    # ---------------- 분해 ----------------
    dec = []
    for a in agg:
        varying = (a["v_true_std_pct"] or 0.0) >= 0.5
        f_step1 = a["floor_global_vs_nom"] or 0.0     # Step 1이 보고한 숫자
        f_defn = a["floor_local_vs_nom"] or 0.0       # 정의 교정(전역→현 estimator)
        f_bar = a["floor_local_vs_bar"] or 0.0        # + 기준 교정(명목→창평균) = 정본
        # 장부 1: 'Step 1이 보고한 floor'의 정체 (목표 = 창평균 속도)
        L1 = {"F_definition": f_defn - f_step1,       # 정의 교체로 늘/줄어든 몫
              "F_metric": f_defn - f_bar,             # 기준 착오가 만든 허수
              "F_model_const": f_bar}                 # 남은 진짜 모델형 오차
        # 장부 2: '순간 속도를 맞추려면' (목표 = 순간 참속도, 돌풍에서만 의미)
        ec = a["err_const_vs_inst"] or 0.0
        er = a["err_ramp_vs_inst"] or 0.0
        fs = a["F_sampling_pct_timevar"] or 0.0     # ★보강2: 시변 컷오프(보수적·정확) 를 정본으로
        L2 = ({"err_const_vs_inst": ec, "F_temporal_ramp": ec - er,
               "F_sampling_physics": fs, "F_residual_observable": ec - (ec - er) - fs}
              if varying else
              {"err_const_vs_inst": None, "F_temporal_ramp": None,
               "F_sampling_physics": None, "F_residual_observable": None})
        # ⓑ 공간 몫: 참속도 std=0 이면 정본 floor 전부가 곡률. 돌풍 계열은 같은 바람세기에서 차용.
        if not varying:
            F_spatial = f_bar
        else:
            ref = {"S2b_20": "S1", "S2b_40": "S1", "S7_worst": "S2a_10"}.get(a["scenario"])
            src = next((x for x in agg if x["scenario"] == ref), None)
            F_spatial = (src["floor_local_vs_bar"] or 0.0) if src else 0.0
        dec.append({"scenario": a["scenario"],
                    "floor_reported_step1": round(f_step1, 3),
                    "floor_defn_corrected": round(f_defn, 3),
                    "floor_canonical_vs_bar": round(f_bar, 3),
                    "F_definition": round(L1["F_definition"], 3),
                    "F_metric": round(L1["F_metric"], 3),
                    "F_spatial": round(F_spatial, 3),
                    **{k: (None if v is None else round(v, 3)) for k, v in L2.items()},
                    # ★보강1: 같은 estimator(배포판)로 잰 관측 오차와 floor 비중
                    "obs_local_vs_bar": a["obs_local_vs_bar"],
                    "floor_share_same_estimator_pct": (
                        round(f_bar / a["obs_local_vs_bar"] * 100, 1)
                        if a["obs_local_vs_bar"] else None),
                    "F_globalchoice": a["F_globalchoice"],
                    # ★보강3: F_sampling 을 ETA 초로 환산 (ETA_err ≈ (d/v)·ε)
                    **({f"F_sampling_eta_{int(d)}m_s": round(d / cfg0.speed_true * fs / 100.0, 2)
                        for d in (30.0, 60.0, 100.0)} if varying else {}),
                    "F_sampling_pct_fixedcut": a["F_sampling_pct"],
                    "quad_probe_vs_bar": a["floor_quad_vs_bar"],
                    "cadence_s": a["cadence_s"],
                    "cadence_lo_s": a["cadence_lo_s"], "cadence_hi_s": a["cadence_hi_s"],
                    "w_cut_lo": a["w_cut_lo"], "w_cut_hi": a["w_cut_hi"],
                    "unobservable_var_share_SIGNAL": a["unobservable_var_share_SIGNAL"]})

    write_csv(os.path.join(args.outdir, "raw_2e3_floor_audit.csv"), raw)
    write_csv(os.path.join(args.outdir, "summary_2e3_20_floor_decomposition.csv"), dec)

    print("\n" + "=" * 100)
    print("ⓐ 지표 기준 착오 — 같은 추정치를 '명목 상수' vs '관측창 평균 참속도'에 견줌")
    print("=" * 100)
    print(f"  {'시나리오':9s} {'참속도std%':>10s} {'창평균 편차%':>12s} "
          f"{'floor(전역)vs명목':>16s} {'vs창평균':>10s} {'floor(현est)vs명목':>18s} {'vs창평균':>10s}")
    for a in agg:
        print(f"  {a['scenario']:9s} {a['v_true_std_pct']:10.2f} {a['T_bar_dev_pct']:12.2f} "
              f"{a['floor_global_vs_nom']:16.2f} {a['floor_global_vs_bar']:10.2f} "
              f"{a['floor_local_vs_nom']:18.2f} {a['floor_local_vs_bar']:10.2f}")

    print("\n" + "=" * 100)
    print("ⓑ 공간 모델형 — 참속도 std=0 인데 남는 floor = 화선 곡률 vs 평면적합 (2차항 탐침 병기)")
    print("=" * 100)
    print(f"  {'시나리오':9s} {'참속도std%':>10s} {'floor(현est)':>13s} {'2차항 탐침':>11s}  해석")
    for a in agg:
        if (a["v_true_std_pct"] or 0) >= 0.5:
            continue
        q = a["floor_quad_vs_bar"]
        room = "" if q is None else (f"→ 2차항으로 {a['floor_local_vs_bar']-q:+.2f}%p"
                                     if a["floor_local_vs_bar"] is not None else "")
        why = "곡률 없음(직선 화선)" if (a["floor_local_vs_bar"] or 0) < 0.05 else "★곡률 모델형 오차 존재"
        print(f"  {a['scenario']:9s} {a['v_true_std_pct']:10.2f} {a['floor_local_vs_bar']:13.2f} "
              f"{(q if q is not None else float('nan')):11.2f}  {why} {room}")

    print("\n" + "=" * 100)
    print("ⓒ 시간 모델형 — 무노이즈 오라클에 등속 vs 선형램프 (순간 참속도 대비 오차 %)")
    print("=" * 100)
    print(f"  {'시나리오':9s} {'등속모델':>9s} {'선형램프':>9s} {'회수 몫(F_temporal)':>19s}")
    for a in agg:
        if (a["v_true_std_pct"] or 0) < 0.5:
            continue
        d = a["err_const_vs_inst"] - a["err_ramp_vs_inst"]
        print(f"  {a['scenario']:9s} {a['err_const_vs_inst']:9.2f} {a['err_ramp_vs_inst']:9.2f} "
              f"{d:19.2f}")

    print("\n" + "=" * 100)
    print("★보강1 · 같은 estimator로 잰 floor 비중 (Step 1은 분자=전역적합/분모=배포판이라 추정기가 달랐음)")
    print("=" * 100)
    print(f"  {'시나리오':9s} {'관측(배포판)':>12s} {'floor(배포판)':>13s} {'floor 비중':>10s} | "
          f"{'floor(전역)':>11s} {'F_globalchoice':>15s}")
    for a in agg:
        sh = (a["floor_local_vs_bar"] / a["obs_local_vs_bar"] * 100) if a["obs_local_vs_bar"] else float("nan")
        print(f"  {a['scenario']:9s} {a['obs_local_vs_bar']:12.2f} {a['floor_local_vs_bar']:13.2f} "
              f"{sh:9.1f}% | {a['floor_global_vs_bar']:11.2f} {a['F_globalchoice']:+15.2f}")
    print("\n  · F_globalchoice = floor(전역적합) − floor(배포판) = **전역적합이라는 '방법 선택'이 만든 몫**")
    print("    → 부호가 어느 쪽이든, 이 값이 0이 아니라는 사실 자체가 'floor의 일부는 물리가 아니라 방법'의 직접 증거다.")

    print("\n" + "=" * 100)
    print("ⓓ 표본 해상도(나이퀴스트) — ★이 항만 '물리적 한계' 서술 허용")
    print("=" * 100)
    print(f"  케이던스 Δt = spacing / v.  **v는 순간 속도라 경계도 함께 움직인다**(★보강2):")
    print(f"    평균속도 기준(근사): Δt = {cfg0.spacing_m}/{cfg0.speed_true} = "
          f"{cfg0.spacing_m/cfg0.speed_true:.2f} s → ω_cut = π·v/spacing = "
          f"{math.pi*cfg0.speed_true/cfg0.spacing_m:.3f} rad/s")
    print(f"    돌풍 성분 ω = {np.round(np.linspace(0.08, 0.55, 4), 3).tolist()} rad/s")
    print(f"  {'시나리오':9s} {'Δt 범위(s)':>14s} {'ω_cut 범위':>16s} "
          f"{'신호분산 초과몫':>15s} {'F_samp(고정)':>13s} {'F_samp(시변)':>13s}")
    for a in agg:
        if (a["v_true_std_pct"] or 0) < 0.5:
            continue
        print(f"  {a['scenario']:9s} {a['cadence_lo_s']:6.2f}~{a['cadence_hi_s']:<7.2f} "
              f"{a['w_cut_lo']:7.3f}~{a['w_cut_hi']:<8.3f} "
              f"{a['unobservable_var_share_SIGNAL']*100:14.1f}% "
              f"{a['F_sampling_pct']:13.2f} {a['F_sampling_pct_timevar']:13.2f}")
    print("\n  ★보강4 · 단위 혼동 금지: '신호분산 초과몫'(무차원, 돌풍 신호의 분산 비율)과")
    print("    'F_sampling(%)'(추정오차)은 **다른 양**이다. 변환은 근사식이 아니라 아래 정의로 직접 계산했다:")
    print("      v_obs(t) = 대역제한 재구성(ω ≤ ω_cut 성분만)  ← 어떤 샘플러도 못 넘는 최선")
    print("      F_sampling(%) = mean_t |v_obs(t) − v_inst(t)| / v_inst(t) × 100")
    print("    기준은 **순간 참값 T_inst**다. 창평균 T_bar 기준에는 이 항이 적용되지 않는다")
    print("    (등속 추정량은 시간변동을 애초에 추적하지 않으므로 나이퀴스트 한계가 걸리지 않는다).")

    print("\n" + "=" * 100)
    print("★보강3 · F_sampling 을 ETA 초로 환산 (우리가 파는 건 속도%가 아니라 ETA다)")
    print(f"    변환: ETA_err ≈ (d / v) · ε,  d/v = 30/1.5=20 s · 60/1.5=40 s · 100/1.5=66.7 s")
    print("=" * 100)
    print(f"  {'시나리오':9s} {'F_samp %':>9s} {'ETA@30m(s)':>11s} {'ETA@60m(s)':>11s} {'ETA@100m(s)':>12s}")
    for d in dec:
        if d.get("F_sampling_eta_30m_s") is None:
            continue
        print(f"  {d['scenario']:9s} {d['F_sampling_physics']:9.2f} "
              f"{d['F_sampling_eta_30m_s']:11.2f} {d['F_sampling_eta_60m_s']:11.2f} "
              f"{d['F_sampling_eta_100m_s']:12.2f}")

    print("\n" + "=" * 100)
    print("★ 장부 1 — 'Step 1이 보고한 floor'의 정체  (목표 = 관측창 평균 참속도)")
    print("   Step1 보고 + F_definition + F_metric  =  정본 floor(= 진짜 모델형 오차)")
    print("=" * 100)
    print(f"  {'시나리오':9s} {'Step1 보고':>10s} {'F_definition':>13s} {'F_metric':>10s} "
          f"{'→ 정본 floor':>13s} {'그중 F_spatial':>14s}")
    for d in dec:
        print(f"  {d['scenario']:9s} {d['floor_reported_step1']:10.2f} {d['F_definition']:+13.2f} "
              f"{-d['F_metric']:+10.2f} {d['floor_canonical_vs_bar']:13.2f} {d['F_spatial']:14.2f}")
    print("\n  · F_definition = 전역평면적합(Step1) → 현 estimator(국소+중앙값) 로 정의를 바로잡은 몫")
    print("  · F_metric     = 명목 상수 대신 관측창 평균 참속도에 견주자 사라진 몫 = **기준 착오가 만든 허수**")
    print("  · F_spatial    = 참속도 std=0 인데도 남는 몫 = 화선 곡률 vs 평면적합 = **모델형(줄일 수 있음)**")

    print("\n" + "=" * 100)
    print("★ 장부 2 — '순간 속도를 맞추려면'  (목표 = 순간 참속도, 돌풍 계열만 의미)")
    print("   등속모델 총오차 = F_temporal(램프로 회수) + F_sampling(★물리) + F_residual(관측가능·미회수)")
    print("=" * 100)
    print(f"  {'시나리오':9s} {'등속 총오차':>11s} {'F_temporal':>11s} {'F_sampling★물리':>15s} "
          f"{'F_residual':>11s} {'물리 비중':>9s}")
    for d in dec:
        if d["err_const_vs_inst"] is None:
            continue
        tot = d["err_const_vs_inst"]
        share = d["F_sampling_physics"] / tot * 100 if tot > 1e-9 else 0.0
        print(f"  {d['scenario']:9s} {tot:11.2f} {d['F_temporal_ramp']:11.2f} "
              f"{d['F_sampling_physics']:15.2f} {d['F_residual_observable']:11.2f} {share:8.1f}%")

    print("\n" + "=" * 100)
    print("한 줄 판정 — 돌풍 floor 중 '실제 물리(ⓓ)'의 몫  (정지 조건: ≥70 % 면 B 투입 안 함)")
    print("=" * 100)
    for name in ("S2b_20", "S2b_40", "S7_worst"):
        d = next((x for x in dec if x["scenario"] == name), None)
        if not d or d["err_const_vs_inst"] is None:
            continue
        tot = d["err_const_vs_inst"]
        share = d["F_sampling_physics"] / tot * 100 if tot > 1e-9 else 0.0
        verdict = ("물리 지배 → B 투입 정당성 없음" if share >= 70 else
                   "방법 지배 → B/곡률모델 투입 정당")
        print(f"  {name:9s} 등속모델 총오차 {tot:6.2f}% 중 물리(ⓓ) {d['F_sampling_physics']:5.2f}%p "
              f"= **{share:5.1f}%**  → {verdict}")


if __name__ == "__main__":
    main()
