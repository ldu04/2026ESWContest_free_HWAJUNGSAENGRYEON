"""run_2e3_stepI_a.py — #2e-3 Step 2.I-a · **대τ 감쇠 → 검출 실패** 시험 (우리 τ 이야기의 구멍 점검).

★★ 착수 시 발견한 전제 결함 (측정 전에 기록)
──────────────────────────────────────────────────────────────────────────────
지시서는 "온도 펄스(폭 ~20 s)"를 전제하지만, **현재 `fire._temp_from_d`는 전선 통과 후(d ≤ 0)
`peak`(300 ℃)를 영구 반환**한다 — 온도가 올라간 뒤 **내려오지 않는다**. 따라서 현 모델에서는
1차 저역통과가 어떤 τ에서도 결국 300 ℃로 수렴하므로 **감쇠에 의한 검출 실패가 원리적으로 불가능**하고,
τ가 클 때 보이는 "안 죽음"은 **`t_max` 절단 아티팩트**다(전혀 다른 기제).

→ 두 겹으로 측정한다:
  **ⓐ 현 모델(burn_scale=0):** t_max를 늘리면 미검출이 사라지는가 = 절단 아티팩트임을 확인.
  **ⓑ 펄스 모델(burn_scale>0):** 연소 후 냉각 꼬리를 넣어 **진짜 감쇠→검출 실패**의 파단 τ를 측정.
  (냉각 꼬리는 물리적으로 정당한 최소 추가이며 `burn_scale_m=0`이면 기존과 비트 동일.)
──────────────────────────────────────────────────────────────────────────────

★ 부호/방향 예측 (측정 전에 적는다 — 맞든 틀리든 그대로 보고)
  Pa1. **현 모델**: t_max를 120→300 s로 늘리면 검출 실패율이 **0으로 수렴**한다(절단 아티팩트).
  Pa2. **펄스 모델**: 80 ℃ 이상 구간 폭 ≈ (warm_scale + burn_scale)·ln5 / v.
       burn=10 m·v=1.5 m/s면 ≈ (6+10)·1.609/1.5 ≈ **17 s**. τ가 이 폭에 근접하면 감쇠로 최고값이
       80 ℃에 못 미쳐 **검출 실패**. 파단은 **τ ~ 펄스폭의 1/2 부근**(τ≈8~10 s)으로 예상.
  Pa3. **화선이 빠를수록 펄스가 짧아 같은 τ에서 더 나쁘다** — 실패는 대략 τ/펄스폭의 함수.
  Pa4. **검출 실패는 위험측 실패다** — 그 지점에 불이 왔는지 모르니 그 구역을 **미연소로 오인**한다.
  Pa5. 재구성(T_air = T_sensor + τ·dT/dt)은 **감쇠가 심하면 미분 신호 자체가 약해져** 회복이 제한될 것.

규율: estimator·E3x2 편향항 불변. 환경 모델만. 파라미터는 물리에서(테스트 점수 금지).
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
from sim.node import NodeState
from scripts.run_2e3_diagnose import TrueFront
from scripts.run_2e3_stepE import OUTDIR
from scripts.run_2e3_stepH import recon_cross_time

TAUS = (0.0, 2.0, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0)
EVAL = [
    ("S1",       {}),
    ("S2a_10",   {"wind_noise_deg": 10.0}),
    ("S6_n9",    {"grid_rows": 3, "grid_cols": 3, "p_dropout": 0.05}),
    ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                  "placement_jitter": 0.2, "p_dropout": 0.10}),
]


def run_case(seed, ov, tau, burn, t_max, var_pct=0.0, speed=None):
    kw = dict(mode="ours", seed=seed, sensor_tau_s=tau, sensor_tau_var_pct=var_pct,
              burn_scale_m=burn, t_max=t_max, **ov)
    if speed is not None:
        kw["speed_true"] = speed
    cfg = Config(**kw)
    eng = Engine(cfg)
    smax = {nd.id: nd.temp for nd in eng.nodes}
    for _ in eng.stream():
        for nd in eng.nodes:
            if nd.temp > smax[nd.id]:
                smax[nd.id] = nd.temp
    tf = TrueFront(eng.fire)

    exposed = miss = 0
    atten, delay, rec_ok = [], [], []
    for nd in eng.nodes:
        if nd.is_sink:
            continue
        ta = tf.arrival(nd.pos)
        if ta is None:                       # 전선이 도달하지 않은 노드는 대상 아님
            continue
        exposed += 1
        atten.append(smax[nd.id])            # 센서 최고 읽음값(참 최고 = peak)
        if nd.death_t is None:
            miss += 1                        # ★검출 실패: 노출됐는데 죽음 신호 없음
        else:
            delay.append(nd.death_t - ta)
        # 재구성 회복: 보고 계열에서 역보상해 임계 통과를 되살리나
        if tau > 0:
            tr = recon_cross_time(eng.net.rep_hist.get(nd.id, []), tau, cfg.temp_threshold)
            rec_ok.append(1 if tr is not None else 0)
    return {"exposed": exposed, "miss": miss,
            "miss_rate": (miss / exposed * 100.0) if exposed else 0.0,
            "sensor_peak": float(np.mean(atten)) if atten else None,
            "delay": float(np.mean(delay)) if delay else None,
            "recon_rate": (float(np.mean(rec_ok)) * 100.0) if rec_ok else None,
            "confirmed": len(eng.estimator.deaths)}


def agg(rs, k):
    v = [r[k] for r in rs if r.get(k) is not None]
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
    c0 = Config()
    L, v0 = c0.warm_scale, c0.speed_true

    print("#2e-3 Step 2.I-a · 대τ 감쇠 → 검출 실패 (estimator 불변, 환경 모델만)")
    print(f"  ★전제 결함 고지: 현 모델은 전선 통과 후 peak를 **영구 유지**해 '펄스'가 없다.")
    print(f"    → burn_scale_m(냉각 꼬리)을 추가해야 감쇠 시험이 성립. 0이면 기존과 비트 동일.\n")
    for b in (0.0, 6.0, 10.0):
        if b > 0:
            w = (L + b) * math.log((c0.peak - c0.ambient) / (c0.temp_threshold - c0.ambient)) / v0
            print(f"    burn_scale={b:4.1f} m → 80 ℃ 이상 펄스 폭 ≈ {w:5.2f} s")
        else:
            print(f"    burn_scale= 0.0 m → 펄스 없음(통과 후 300 ℃ 영구)")
    print()

    rows = []
    # ---- ⓐ 현 모델: t_max 절단 vs 진짜 실패 ----
    print("=" * 100)
    print("ⓐ 현 모델(burn_scale=0) — t_max 절단 아티팩트인가 (Pa1 검증)")
    print("=" * 100)
    print(f"  {'τ(s)':>5s} {'t_max':>6s} " + "".join(f"{n:>16s}" for n, _ in EVAL))
    for tm in (120.0, 300.0):
        for tau in TAUS:
            cells = []
            for name, ov in EVAL:
                rs = [run_case(sd, ov, tau, 0.0, tm) for sd in seeds]
                mr = agg(rs, "miss_rate")
                rows.append({"phase": "a_noburn", "scenario": name, "tau_s": tau, "t_max": tm,
                             "burn": 0.0, "miss_rate": mr, "sensor_peak": agg(rs, "sensor_peak"),
                             "delay": agg(rs, "delay"), "recon_rate": agg(rs, "recon_rate"),
                             "confirmed": agg(rs, "confirmed")})
                cells.append(f"{mr:15.1f}%")
            print(f"  {tau:5.1f} {tm:6.0f} " + "".join(cells))

    # ---- ⓑ 펄스 모델: 진짜 감쇠 ----
    print("\n" + "=" * 100)
    print("ⓑ 펄스 모델(burn_scale=10 m, 펄스 폭 ≈17 s, t_max=300) — 감쇠→검출 실패 (Pa2)")
    print("=" * 100)
    print(f"  {'τ(s)':>5s} {'τ/펄스폭':>8s} " + "".join(f"{n+' 실패/센서peak':>22s}" for n, _ in EVAL))
    wpulse = (L + 10.0) * math.log((c0.peak - c0.ambient) / (c0.temp_threshold - c0.ambient)) / v0
    for tau in TAUS:
        cells = []
        for name, ov in EVAL:
            rs = [run_case(sd, ov, tau, 10.0, 300.0) for sd in seeds]
            mr, sp = agg(rs, "miss_rate"), agg(rs, "sensor_peak")
            rows.append({"phase": "b_pulse", "scenario": name, "tau_s": tau, "t_max": 300.0,
                         "burn": 10.0, "miss_rate": mr, "sensor_peak": sp,
                         "delay": agg(rs, "delay"), "recon_rate": agg(rs, "recon_rate"),
                         "confirmed": agg(rs, "confirmed")})
            cells.append(f"{mr:8.1f}% /{sp:9.1f}℃".rjust(22))
        print(f"  {tau:5.1f} {tau/wpulse:8.2f} " + "".join(cells))

    # ---- 속도 상호작용(Pa3) ----
    print("\n" + "=" * 100)
    print("Pa3 · 화선 속도 상호작용 — 빠를수록 펄스가 짧아 같은 τ에서 더 나쁜가 (S1, burn=10)")
    print("=" * 100)
    print(f"  {'속도(m/s)':>9s} {'펄스폭(s)':>9s} " + "".join(f"τ={t:<5.0f}".rjust(11) for t in TAUS))
    for sp in (0.75, 1.5, 3.0):
        w = (L + 10.0) * math.log((c0.peak - c0.ambient) / (c0.temp_threshold - c0.ambient)) / sp
        cells = []
        for tau in TAUS:
            rs = [run_case(sd, {}, tau, 10.0, 300.0, speed=sp) for sd in seeds]
            mr = agg(rs, "miss_rate")
            rows.append({"phase": "c_speed", "scenario": "S1", "tau_s": tau, "t_max": 300.0,
                         "burn": 10.0, "speed": sp, "miss_rate": mr,
                         "sensor_peak": agg(rs, "sensor_peak")})
            cells.append(f"{mr:10.1f}%")
        print(f"  {sp:9.2f} {w:9.2f} " + "".join(cells))

    write_csv(os.path.join(args.outdir, "summary_2e3_Ia_tau_attenuation.csv"), rows)

    # ---- 판정 ----
    print("\n" + "=" * 100)
    print("★ 판정")
    print("=" * 100)
    a120 = max(r["miss_rate"] for r in rows if r["phase"] == "a_noburn" and r["t_max"] == 120.0)
    a300 = max(r["miss_rate"] for r in rows if r["phase"] == "a_noburn" and r["t_max"] == 300.0)
    print(f"  ⓐ 현 모델 최대 검출 실패율: t_max=120 s **{a120:.1f} %** → t_max=300 s **{a300:.1f} %**")
    print(f"     → {'Pa1 확증: 절단 아티팩트였다' if a300 < 1.0 else 'Pa1 반증: t_max를 늘려도 남는다'}")
    br = None
    for tau in TAUS:
        m = max(r["miss_rate"] for r in rows if r["phase"] == "b_pulse" and r["tau_s"] == tau)
        if m > 10.0 and br is None:
            br = tau
    print(f"  ⓑ 펄스 모델 파단 τ(실패율 >10 %) = {br if br else '없음(τ≤60 s에서 미도달)'} s "
          f"(펄스 폭 {wpulse:.1f} s)")
    for tau in TAUS:
        m = max(r["miss_rate"] for r in rows if r["phase"] == "b_pulse" and r["tau_s"] == tau)
        rr = [r["recon_rate"] for r in rows if r["phase"] == "b_pulse" and r["tau_s"] == tau
              and r["recon_rate"] is not None]
        print(f"     τ={tau:5.1f} s (τ/폭 {tau/wpulse:4.2f}): 최대 실패율 {m:5.1f} %"
              + (f", 재구성 임계복원 {np.mean(rr):5.1f} %" if rr else ""))


if __name__ == "__main__":
    main()
