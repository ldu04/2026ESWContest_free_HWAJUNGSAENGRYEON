"""run_2e3_stepH.py — #2e-3 Step 2.H **Step 1(진단)** · "죽음의 시각이 아니라 죽음의 곡선을 쓴다".

지금 노드는 임계(80 ℃) 도달 **시각 하나**만 쓰고 죽어가는 **온도 곡선**은 버린다. 2.G는 그 버려진
정보 때문에 τ가 방향까지 위협하고 결합최악이 안 잡혀 **판정 (C)**로 끝났다. 이 단계는 곡선을 되살려
센서 지연을 역보상한다:  **T_air = T_sensor + τ·(dT_sensor/dt)**  (1차 저역통과의 역식).

★★ 정직성 핵심 (이 파일 전체를 지배하는 규칙)
──────────────────────────────────────────────────────────────────────────────────
시뮬은 `T_sensor += (T_air − T_sensor)·(dt/τ)` 로 뭉갰다. 그걸 **같은 모델·같은 τ**로 되돌리면
**당연히 복원된다 = tautology(순환논증)**. 그러므로:
  · **1b(매치드) 결과는 성과가 아니다.** 상한 파악용으로 기록만 하고 헤드라인에 쓰지 않는다.
  · **이 단계의 모든 가치는 1c(미스매치·노이즈 강건성)에서만 나온다.**
──────────────────────────────────────────────────────────────────────────────────

규율
----
· **god-view 금지**: 재구성은 `network.rep_hist`(메시가 **실제 수신한** 보고 온도 계열)에서만.
  시뮬 정답 온도(`fire.temp_at`)는 **평가 기준**으로만 쓰고 재구성 입력으로는 쓰지 않는다.
· **재구성 τ는 '실측 전제'**: 지금 시뮬 τ로 최종 보정을 확정하지 않는다. 상한·강건성만 측정.
· estimator 불변. 재구성은 **사망시각 산출 앞단**에서만.

★ 착수 전 예측 (측정 전에 적는다 — 맞든 틀리든 그대로 보고)
  Q1a. 무풍·직선(S1)에서는 모든 노드의 임계 통과 상승률이 같아 **τ 지연이 진짜 균일** →
       방향 2.115°가 τ에 **불변**일 것. (2.G에서 방향이 무너진 건 S2a 20°=바람으로 화선이 굽은 조건뿐이었다.)
       → 맞으면 "헤드라인은 τ에 강건, τ의 방향 위협은 바람 굽힘 한정"이라는 방어선이 생긴다. **단정 아님.**
  Q1c. dT/dt는 미분이라 잡음을 증폭한다. 보고 간격이 heartbeat 1 s로 성기므로 증폭이 클 것이고,
       **어느 잡음 수준 이상에서는 재구성이 무보정보다 나빠지는 교차점**이 있을 것이다.
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
TAUS = (0.0, 2.0, 5.0, 10.0)
MISMATCH = (0.5, 0.7, 0.8, 1.0, 1.2, 1.3, 1.5)       # τ_used / τ_true
NOISES = (0.0, 0.25, 0.5, 1.0, 2.0)                   # 보고 온도 측정 잡음 std(℃)
QUANT = 0.0625                                        # DS18B20 12bit

HEAD = [("S1", {}), ("S2a_5", {"wind_noise_deg": 5.0})]          # 1a 헤드라인 대상
EVAL = [("S1", {}), ("S2a_5", {"wind_noise_deg": 5.0}),
        ("S2a_10", {"wind_noise_deg": 10.0}), ("S2a_20", {"wind_noise_deg": 20.0}),
        ("S6_n9", {"grid_rows": 3, "grid_cols": 3, "p_dropout": 0.05}),
        ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                      "placement_jitter": 0.2, "p_dropout": 0.10})]


# ---------------- 역보상 재구성 (god-view 금지: rep_hist 만 사용) ----------------
def recon_cross_time(hist, tau_used, thr, smooth=0):
    """보고 온도 계열에서 `T_air = T_sensor + τ·dT/dt` 가 thr를 처음 넘는 시각.

    smooth>0 이면 이동평균 창(샘플 수)으로 평활한 뒤 미분 — 도함수 잡음 완화 시험용.
    """
    if len(hist) < 2:
        return None
    ts = np.array([h[0] for h in hist], dtype=float)
    Ts = np.array([h[1] for h in hist], dtype=float)
    if np.ptp(ts) < 1e-9:
        return None
    if smooth and smooth > 1:
        # ★평활은 **미분 단계에서** 한다: 후행 창(마지막 k점)에 최소제곱 직선을 맞춰 기울기를 쓴다.
        #   (초기 구현은 np.convolve(mode="same")로 값 자체를 평활했는데, 짧은 계열의 **끝단이
        #    가장자리 효과로 뭉개졌다** — 임계 통과가 바로 그 끝단이라 측정이 무효였다. 정정.)
        d = np.empty_like(Ts)
        for i in range(Ts.size):
            lo = max(0, i - smooth + 1)
            tt, TT = ts[lo:i + 1], Ts[lo:i + 1]
            if tt.size < 2 or np.ptp(tt) < 1e-9:
                d[i] = 0.0
            else:
                d[i] = float(np.polyfit(tt, TT, 1)[0])
    else:
        d = np.gradient(Ts, ts)
    Tair = Ts + tau_used * d
    for i in range(Tair.size):
        if Tair[i] >= thr:
            if i == 0:
                return float(ts[0])
            a, b = Tair[i - 1], Tair[i]
            if abs(b - a) < 1e-12:
                return float(ts[i])
            f = (thr - a) / (b - a)
            return float(ts[i - 1] + f * (ts[i] - ts[i - 1]))
    return None


def true_air_cross(fire, pos, cfg):
    """참 **공기** 온도가 임계를 넘는 시각 = τ=0일 때의 사망시각. 평가 기준(재구성 입력 아님)."""
    n = int(round(cfg.t_max / cfg.dt))
    for k in range(n):
        t = round(k * cfg.dt, 6)
        if fire.temp_at(pos, t) >= cfg.temp_threshold:
            return t
    return None


def run_case(seed, ov, tau, order=1, noise=0.0, quant=0.0, var_pct=0.0):
    cfg = Config(mode="ours", seed=seed, sensor_tau_s=tau, sensor_order=order,
                 sensor_noise_c=noise, sensor_quant_c=quant,
                 sensor_tau_var_pct=var_pct, **ov)
    eng = Engine(cfg)
    for _ in eng.stream():
        pass
    return cfg, eng


def true_air_map(cfg, eng):
    """노드별 참 공기 임계 통과 시각을 **한 번만** 계산해 캐시(τ_used와 무관하므로 재사용)."""
    if not hasattr(eng, "_air_map"):
        eng._air_map = {nd.id: true_air_cross(eng.fire, nd.pos, cfg)
                        for nd in eng.nodes if not nd.is_sink}
    return eng._air_map


def eval_recon(cfg, eng, tau_used, smooth=0):
    """재구성 사망시각으로 신선한 Estimator를 적합 → 방향/속도, 그리고 시각 잔차."""
    amap = true_air_map(cfg, eng)
    ev, resid_raw, resid_rec = [], [], []
    for uid, (x, y, t_obs) in eng.estimator.deaths.items():
        t_true = amap.get(uid)
        if t_true is None:
            continue
        resid_raw.append(t_obs - t_true)                       # 무보정 잔차(양수 = 늦다)
        tr = recon_cross_time(eng.net.rep_hist.get(uid, []), tau_used,
                              cfg.temp_threshold, smooth)
        if tr is None:
            tr = t_obs
        resid_rec.append(tr - t_true)
        ev.append({"id": uid, "pos": (x, y), "death_t_est": tr})
    if len(ev) < cfg.min_samples:
        return None
    est = Estimator(cfg, neighbors=eng.net.neighbors)
    out = est.update(ev, 0.0, None)
    de = angle_deg(out["dir"], cfg.direction()) if out["dir"] else None
    return {"dir": de, "speed": out["speed"],
            "resid_raw_mean": float(np.mean(resid_raw)) if resid_raw else None,
            "resid_raw_abs": float(np.mean(np.abs(resid_raw))) if resid_raw else None,
            "resid_rec_mean": float(np.mean(resid_rec)) if resid_rec else None,
            "resid_rec_abs": float(np.mean(np.abs(resid_rec))) if resid_rec else None}


def agg(rows, k):
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

    print("#2e-3 Step 2.H · Step 1(진단) — 죽음의 곡선 재구성 (estimator 불변, 측정만)")
    print("  ★ 매치드(1b)는 tautology → 성과 아님. 가치는 1c(미스매치·잡음 강건성)에서만.\n")

    # ============ 1a. 헤드라인 방향 vs τ ============
    print("=" * 100)
    print("1a · 헤드라인 방향(무풍·저풍)이 τ에 살아남나  ← 2.G 세트에 S1이 없어 이번에 측정")
    print("=" * 100)
    rows_a = []
    for name, ov in HEAD:
        for tau in TAUS:
            for mode, vp in (("uniform", 0.0), ("variable", 0.3)):
                if tau == 0.0 and mode == "variable":
                    continue
                de, se = [], []
                for sd in seeds:
                    cfg, eng = run_case(sd, ov, tau, var_pct=vp)
                    if eng.estimator.dir_global:
                        de.append(angle_deg(eng.estimator.dir_global, cfg.direction()))
                    if eng.estimator.speed_global:
                        se.append((eng.estimator.speed_global - cfg.speed_true)
                                  / cfg.speed_true * 100.0)
                rows_a.append({"scenario": name, "tau_s": tau, "mode": mode,
                               "dir_deg": round(float(np.mean(de)), 3) if de else None,
                               "dir_std": round(float(np.std(de)), 3) if de else None,
                               "speed_pct": round(float(np.mean(se)), 3) if se else None})
    write_csv(os.path.join(args.outdir, "summary_2e3_H_1a_dir_vs_tau.csv"), rows_a)
    print(f"  {'시나리오':8s} {'τ(s)':>5s} {'모드':9s} {'방향(°)':>10s} {'±std':>8s} {'속도(%)':>9s}")
    for r in rows_a:
        print(f"  {r['scenario']:8s} {r['tau_s']:5.1f} {r['mode']:9s} {r['dir_deg']:10.3f} "
              f"{r['dir_std']:8.3f} {r['speed_pct']:+9.2f}")
    base = next(r for r in rows_a if r["scenario"] == "S1" and r["tau_s"] == 0.0)
    worst = max((r for r in rows_a if r["scenario"] == "S1"), key=lambda r: r["dir_deg"])
    print(f"\n  → S1 헤드라인 {base['dir_deg']}° · τ 스윕 최악 {worst['dir_deg']}° "
          f"(τ={worst['tau_s']:.0f}s/{worst['mode']})  "
          f"{'✅ 헤드라인 유지' if worst['dir_deg'] <= base['dir_deg']*1.2 else '❌ 헤드라인 열화'}")

    # ============ 1b. 매치드 상한 (tautology — 성과 아님) ============
    print("\n" + "=" * 100)
    print("1b · 매치드 재구성 상한  ★tautology(같은 모델·같은 τ) → 성과 아님, 상한 파악용 기록만")
    print("=" * 100)
    rows_b = []
    for name, ov in EVAL:
        for tau in (2.0, 5.0, 10.0):
            rs = []
            for sd in seeds:
                cfg, eng = run_case(sd, ov, tau)
                r = eval_recon(cfg, eng, tau_used=tau)
                if r:
                    rs.append(r)
            if rs:
                rows_b.append({"scenario": name, "tau_s": tau,
                               "resid_raw_abs": agg(rs, "resid_raw_abs"),
                               "resid_rec_abs": agg(rs, "resid_rec_abs"),
                               "dir_recon": agg(rs, "dir")})
    write_csv(os.path.join(args.outdir, "summary_2e3_H_1b_matched.csv"), rows_b)
    print(f"  {'시나리오':9s} {'τ(s)':>5s} {'무보정 |잔차|(s)':>16s} {'재구성 |잔차|(s)':>16s} {'회복률':>8s} {'방향(°)':>9s}")
    for r in rows_b:
        rec = 1 - r["resid_rec_abs"] / r["resid_raw_abs"] if r["resid_raw_abs"] else 0
        print(f"  {r['scenario']:9s} {r['tau_s']:5.1f} {r['resid_raw_abs']:16.3f} "
              f"{r['resid_rec_abs']:16.3f} {rec*100:7.1f}% {r['dir_recon']:9.3f}")
    print("  ※ 회복률이 높은 건 당연하다(시뮬이 뭉갠 걸 같은 식으로 되돌림). **성과로 세지 않는다.**")

    # ============ 1c. 강건성 3축 ============
    print("\n" + "=" * 100)
    print("1c-(i) · τ 미스매치 — 재구성 τ_used 를 τ_true 의 ±% 로 틀리게 (τ_true=5 s)")
    print("=" * 100)
    rows_c1 = []
    for name, ov in EVAL:
        cache = [run_case(sd, ov, 5.0) for sd in seeds]
        raw = [eval_recon(c, e, tau_used=0.0) for c, e in cache]
        raw = [r for r in raw if r]
        for m in MISMATCH:
            rs = [eval_recon(c, e, tau_used=5.0 * m) for c, e in cache]
            rs = [r for r in rs if r]
            rows_c1.append({"scenario": name, "mult": m,
                            "resid_raw_abs": agg(raw, "resid_raw_abs"),
                            "resid_rec_abs": agg(rs, "resid_rec_abs"),
                            "dir_raw": agg(raw, "dir"), "dir_rec": agg(rs, "dir")})
        print(f"  [{name:9s}] 완료")
    write_csv(os.path.join(args.outdir, "summary_2e3_H_1c_tau_mismatch.csv"), rows_c1)
    print(f"\n  {'시나리오':9s} {'τ_used/τ_true':>13s} {'무보정|잔차|':>12s} {'재구성|잔차|':>12s} "
          f"{'순이득?':>8s} {'방향 무보정→재구성':>20s}")
    for r in rows_c1:
        gain = r["resid_raw_abs"] - r["resid_rec_abs"]
        print(f"  {r['scenario']:9s} {r['mult']:13.1f} {r['resid_raw_abs']:12.3f} "
              f"{r['resid_rec_abs']:12.3f} {('+' if gain > 0 else ''):>2s}{gain:6.3f} "
              f"{r['dir_raw']:9.3f} → {r['dir_rec']:7.3f}")

    print("\n" + "=" * 100)
    print("1c-(ii) · 모델 미스매치 — 실제 센서는 2차 지연인데 1차 역식으로 재구성 (τ=5 s)")
    print("=" * 100)
    rows_c2 = []
    for name, ov in EVAL:
        for order in (1, 2):
            cache = [run_case(sd, ov, 5.0, order=order) for sd in seeds]
            raw = [x for x in (eval_recon(c, e, 0.0) for c, e in cache) if x]
            rec = [x for x in (eval_recon(c, e, 5.0) for c, e in cache) if x]
            rows_c2.append({"scenario": name, "order": order,
                            "resid_raw_abs": agg(raw, "resid_raw_abs"),
                            "resid_rec_abs": agg(rec, "resid_rec_abs"),
                            "dir_raw": agg(raw, "dir"), "dir_rec": agg(rec, "dir")})
    write_csv(os.path.join(args.outdir, "summary_2e3_H_1c_model_mismatch.csv"), rows_c2)
    print(f"  {'시나리오':9s} {'센서차수':>7s} {'무보정|잔차|':>12s} {'재구성|잔차|':>12s} {'순이득':>8s}")
    for r in rows_c2:
        g = r["resid_raw_abs"] - r["resid_rec_abs"]
        print(f"  {r['scenario']:9s} {r['order']:7d} {r['resid_raw_abs']:12.3f} "
              f"{r['resid_rec_abs']:12.3f} {g:+8.3f}")

    print("\n" + "=" * 100)
    print("1c-(iii) · ★도함수 잡음 증폭 — 보고 온도에 잡음+양자화, 평활 없이/3점 평활 (τ=5 s, 매치드 τ)")
    print("=" * 100)
    rows_c3 = []
    for name, ov in EVAL[:4]:
        for ns in NOISES:
            cache = [run_case(sd, ov, 5.0, noise=ns, quant=QUANT) for sd in seeds]
            raw = [x for x in (eval_recon(c, e, 0.0) for c, e in cache) if x]
            for sm in (0, 3):
                rec = [x for x in (eval_recon(c, e, 5.0, smooth=sm) for c, e in cache) if x]
                rows_c3.append({"scenario": name, "noise_c": ns, "smooth": sm,
                                "resid_raw_abs": agg(raw, "resid_raw_abs"),
                                "resid_rec_abs": agg(rec, "resid_rec_abs"),
                                "dir_raw": agg(raw, "dir"), "dir_rec": agg(rec, "dir")})
        print(f"  [{name:9s}] 완료")
    write_csv(os.path.join(args.outdir, "summary_2e3_H_1c_deriv_noise.csv"), rows_c3)
    print(f"\n  {'시나리오':9s} {'잡음(℃)':>8s} {'평활':>5s} {'무보정|잔차|':>12s} "
          f"{'재구성|잔차|':>12s} {'순이득':>8s} {'방향 무보정→재구성':>20s}")
    for r in rows_c3:
        g = r["resid_raw_abs"] - r["resid_rec_abs"]
        print(f"  {r['scenario']:9s} {r['noise_c']:8.2f} {r['smooth']:5d} {r['resid_raw_abs']:12.3f} "
              f"{r['resid_rec_abs']:12.3f} {g:+8.3f} {r['dir_raw']:9.3f} → {r['dir_rec']:7.3f}")

    # ============ 결론 ============
    print("\n" + "=" * 100)
    print("★ 결론 — 재구성이 '순이득'인 조건")
    print("=" * 100)
    ok_m = [r["mult"] for r in rows_c1 if r["resid_raw_abs"] - r["resid_rec_abs"] > 0]
    bad_m = sorted({r["mult"] for r in rows_c1 if r["resid_raw_abs"] - r["resid_rec_abs"] <= 0})
    ok_n0 = sorted({r["noise_c"] for r in rows_c3
                    if r["smooth"] == 0 and r["resid_raw_abs"] - r["resid_rec_abs"] > 0})
    ok_n3 = sorted({r["noise_c"] for r in rows_c3
                    if r["smooth"] == 3 and r["resid_raw_abs"] - r["resid_rec_abs"] > 0})
    print(f"  τ 미스매치: 순이득 배율 = {sorted(set(ok_m))}   순손실 배율 = {bad_m if bad_m else '없음'}")
    print(f"  도함수 잡음(평활 없음): 순이득 잡음 = {ok_n0} ℃")
    print(f"  도함수 잡음(3점 평활):  순이득 잡음 = {ok_n3} ℃")
    o2 = [r for r in rows_c2 if r["order"] == 2]
    g2 = [r["resid_raw_abs"] - r["resid_rec_abs"] for r in o2]
    print(f"  모델 미스매치(2차 센서): 순이득 {sum(1 for x in g2 if x>0)}/{len(g2)} 시나리오, "
          f"평균 {np.mean(g2):+.3f} s")


if __name__ == "__main__":
    main()
