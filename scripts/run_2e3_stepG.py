"""run_2e3_stepG.py — #2e-3 Step 2.G · **센서 열관성 τ 게이트** (2.F 기계를 τ 축으로 확장).

왜: τ는 2.F가 다룬 warm_scale과 **같은 종류의 문제**다 — 시뮬엔 없고 실물엔 있으며 우리가 정확히
모르는 캘리브레이션 변수. 2.F는 warm_scale만 게이트했고 τ는 게이트 밖이었다.

★ 규율(2.F와 동일): **강건성 시험이지 튜닝이 아니다.**
  - E3/E3x 편향 항은 **S1 · W0=6 m · τ=0** 도출값으로 **고정**. 시험 세계에서 **재적합 금지.**
  - τ 모델은 **평가 세계에만** 넣는다(τ를 안다고 가정하지 않는다 — 실물에서 모르는 게 핵심).
  - τ ∈ {0,2,5,10} s 범위는 **DS18B20의 물리적 응답 근거**지 결과를 보고 고른 값이 아니다.
  - estimator·verification·방어 파라미터 불변. τ=0이면 기존과 비트 동일(회귀로 증명 완료).

═══════════════════════════════════════════════════════════════════════════════════════
★★ 착수 전 부호 예측 (측정 전에 적는다. 맞든 틀리든 그대로 보고한다 — #2e-1·2.F의 교훈)
═══════════════════════════════════════════════════════════════════════════════════════
 P1. 무보정 원 추정의 사망시각은 참 도착보다 **6.44 s 이르다**(노드가 죽을 때 불은 아직
     d = W·ln5 = 9.657 m 앞). τ는 센서가 80 ℃에 늦게 닿게 만들어 사망시각을 **뒤로** 민다
     → 이 6.44 s 선행 마진을 갉아먹는다. **τ > 6.44 s면 사망시각이 참 도착보다 늦어진다.**
 P2. E3 편향 항은 "원 추정이 6.44 s 이르다"고 **가정하고** 그만큼 뒤로 민다. τ 때문에 원 추정이
     덜 이르면(또는 늦으면) E3는 **과대보정** → 밴드가 참값보다 **늦게** 놓임
     → **breach_early(위험측) 증가.**
 P3. ⇒ **τ가 클수록 위험측↑.** 이 위험 방향은 2.F의 **"warm_scale 과소"와 같은 종류**
     (둘 다 과대보정 → 밴드 늦음 → 위험). ⇒ **worst = warm_scale 과소 AND τ 과대.**
 P4. (부수) **균일 τ**는 모든 사망시각을 **일괄 시프트** → 도착시각면의 **기울기 불변**
     → **방향·속도 불변, ETA 오프셋만 이동.**
     **변동 τ**(노드별 ±)는 사망시각에 **노이즈**를 더한다 → **속도 오차 증가**(방향은 상대적으로 견고).
═══════════════════════════════════════════════════════════════════════════════════════
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
from sim.metrics import angle_deg
from scripts.run_2e3_diagnose import TrueFront, ETA_DISTS
from scripts.run_2e3_stepE import run_one, OUTDIR
from scripts.run_2e3_stepF import derive_bias_at_W0, EXPAND_R, EXPAND_R_HI

TAUS = (0.0, 2.0, 5.0, 10.0)          # DS18B20 물리 응답 범위(테스트 점수 아님)
VAR_PCT = 0.3                          # 변동 τ 모드: 노드별 ±30 %(제조·피복·기류 편차)

EVAL = [
    ("S2a_10",   {"wind_noise_deg": 10.0}),
    ("S2a_20",   {"wind_noise_deg": 20.0}),
    ("S4_40",    {"placement_jitter": 0.4}),      # 2.F 최악 breach 지점
    ("S6_n9",    {"grid_rows": 3, "grid_cols": 3, "p_dropout": 0.05}),
    ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                  "placement_jitter": 0.2, "p_dropout": 0.10}),
]


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


# ---------------- A-3(a) 방향·속도 비열화 + 사망시각 선행 (ETA 샘플링 없이 빠르게) ----------------
def dir_speed_probe(seeds, ov, tau, var_pct):
    de, se, lead = [], [], []
    for sd in seeds:
        cfg = Config(mode="ours", seed=sd, sensor_tau_s=tau, sensor_tau_var_pct=var_pct, **ov)
        eng = Engine(cfg)
        for _ in eng.stream():
            pass
        tf = TrueFront(eng.fire)
        if eng.estimator.dir_global:
            de.append(angle_deg(eng.estimator.dir_global, cfg.direction()))
        ex = [tf.arrival(nd.pos) for nd in eng.nodes if not nd.is_sink]
        ex = [x for x in ex if x is not None]
        ts = np.arange(min(ex), max(ex) + 1e-9, cfg.dt)
        vb = float(np.mean([eng.fire._speed_at(float(x)) for x in ts]))
        if eng.estimator.speed_global:
            se.append((eng.estimator.speed_global - vb) / vb * 100.0)
        for i, (x, y, tt) in eng.estimator.deaths.items():
            ta = tf.arrival((x, y))
            if ta is not None:
                lead.append(tt - ta)          # 음수 = 사망시각이 참 도착보다 이르다
    f = lambda a: (round(float(np.mean(a)), 3), round(float(np.std(a)), 3)) if a else (None, None)
    return {"dir_mean": f(de)[0], "dir_std": f(de)[1],
            "speed_mean": f(se)[0], "speed_std": f(se)[1],
            "lead_mean": f(lead)[0], "lead_std": f(lead)[1]}


# ---------------- A-3(b) τ별 밴드 커버리지/위험측 ----------------
def evaluate(seeds, ov, floor_pct, bias):
    R = []
    for sd in seeds:
        r, _s = run_one(sd, ov, floor_pct=floor_pct)
        R += r
    out = []
    for d in ETA_DISTS:
        sub = [x for x in R if x["dist"] == d]
        if not sub:
            continue
        q05, q95 = bias[d]
        tr = np.array([x["eta_true"] for x in sub])
        lo0 = np.array([x["e2_early"] for x in sub])
        hi0 = np.array([x["e2_late"] for x in sub])
        rec = {"dist_m": d, "n": len(sub)}
        # E3x2 = (B)안 추가 팽창. **이른끝을 아예 보정하지 않는다(shift 0).**
        #   근거(물리, 점수 아님): τ와 warm_scale이 둘 다 미지이면 −6.44 s 선행 마진이 **완전히 소진**될 수 있다
        #   (측정: τ=10 s에서 −6.44 → −1.4 s, W×0.5와 겹치면 0 근처). 마진이 0일 수 있다면
        #   이른끝을 뒤로 미는 보정 자체가 위험을 만든다 → 이른끝은 **원 추정 그대로** 둔다.
        for tag, sl, sh in (("E3", -q95, -q05),
                            ("E3x", -q95 * EXPAND_R, -q05 * EXPAND_R_HI),
                            ("E3x2", 0.0, -q05 * EXPAND_R_HI)):
            lo, hi = lo0 + sl, hi0 + sh
            rec[f"{tag}_cov_pct"] = round(float(((tr >= lo) & (tr <= hi)).mean()) * 100, 1)
            rec[f"{tag}_breach_early_pct"] = round(float((tr < lo).mean()) * 100, 1)
            rec[f"{tag}_width_s"] = round(float((hi - lo).mean()), 1)
        out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--outdir", default=OUTDIR)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))
    c0 = Config()
    d_thresh = c0.warm_scale * math.log((c0.peak - c0.ambient) / (c0.temp_threshold - c0.ambient))

    print("#2e-3 Step 2.G · 센서 열관성 τ 게이트 (편향항 고정 = 재적합 금지)")
    print(f"  기준 선행: d_thresh = {d_thresh:.3f} m → {d_thresh/c0.speed_true:.2f} s")
    print(f"  τ ∈ {TAUS} s (DS18B20 물리 응답 근거), 변동 모드 ±{VAR_PCT:.0%}\n")
    print("  ★착수 전 예측: τ↑ → 사망시각 뒤로 밀림 → E3 과대보정 → 밴드 늦음 → 위험측↑,")
    print("    위험 방향은 warm_scale 과소와 동종 → worst = W×0.5 ∧ τ=10 s.")
    print("    부수: 균일 τ는 방향·속도 불변(ETA 오프셋만), 변동 τ는 속도 노이즈↑\n")

    floors = {}
    p = os.path.join(OUTDIR, "summary_2e3_20_floor_decomposition.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8")):
            fs = float(r["F_sampling_physics"]) if r.get("F_sampling_physics") else 0.0
            floors[r["scenario"]] = max(fs, float(r["floor_canonical_vs_bar"] or 0.0))

    bias = derive_bias_at_W0(seeds)      # S1·W0·τ=0 에서만 도출, 이후 고정
    print("  고정 편향항(S1·W0·τ=0):")
    for d in ETA_DISTS:
        print(f"    {d:5.0f} m: q05={bias[d][0]:+7.2f}s  q95={bias[d][1]:+7.2f}s")
    print()

    # ---------------- P4 검증: 방향·속도 비열화 ----------------
    probe = []
    for name, ov in EVAL:
        for tau in TAUS:
            for mode, vp in (("uniform", 0.0), ("variable", VAR_PCT)):
                if tau == 0.0 and mode == "variable":
                    continue
                r = dir_speed_probe(seeds, ov, tau, vp)
                r.update({"scenario": name, "tau_s": tau, "mode": mode})
                probe.append(r)
        print(f"  [probe {name:9s}] 완료")
    write_csv(os.path.join(args.outdir, "summary_2e3_G_dir_speed.csv"), probe)

    # ---------------- τ 게이트 ----------------
    rows = []
    for name, ov in EVAL:
        fl = floors.get(name, 0.0)
        cases = [(tau, mode, vp, 1.0)
                 for tau in TAUS for mode, vp in (("uniform", 0.0), ("variable", VAR_PCT))
                 if not (tau == 0.0 and mode == "variable")]
        cases += [(10.0, "uniform", 0.0, 0.5), (10.0, "variable", VAR_PCT, 0.5)]  # 결합 최악
        for tau, mode, vp, wmult in cases:
            ov2 = dict(ov)
            ov2.update({"sensor_tau_s": tau, "sensor_tau_var_pct": vp})
            if wmult != 1.0:
                ov2["warm_scale"] = c0.warm_scale * wmult
            for rec in evaluate(seeds, ov2, fl, bias):
                rec.update({"scenario": name, "tau_s": tau, "mode": mode, "warm_mult": wmult})
                rows.append(rec)
        print(f"  [gate  {name:9s}] 완료")
    write_csv(os.path.join(args.outdir, "summary_2e3_G_tau_gate.csv"), rows)

    # ================= 출력 =================
    print("\n" + "=" * 104)
    print("★ P1 검증 — τ가 사망시각 선행(참 도착 대비, 음수=이르다)을 얼마나 갉아먹나")
    print("=" * 104)
    print(f"  {'τ(s)':>5s} {'모드':9s} " + "".join(f"{n:>13s}" for n, _ in EVAL))
    for tau in TAUS:
        for mode in ("uniform", "variable"):
            if tau == 0.0 and mode == "variable":
                continue
            cells = []
            for name, _ in EVAL:
                r = next((x for x in probe if x["scenario"] == name and x["tau_s"] == tau
                          and x["mode"] == mode), None)
                cells.append(f"{r['lead_mean']:+13.2f}" if r else f"{'-':>13s}")
            print(f"  {tau:5.1f} {mode:9s} " + "".join(cells))
    print("  → 값이 0에 가까워지거나 양수가 되면 '사망시각이 참 도착보다 늦다' = 선행 마진 소진")

    print("\n" + "=" * 104)
    print("★ P4 검증 — 방향(°) / 속도(%) 비열화")
    print("=" * 104)
    print(f"  {'τ(s)':>5s} {'모드':9s} " + "".join(f"{n+' 방향/속도':>22s}" for n, _ in EVAL))
    for tau in TAUS:
        for mode in ("uniform", "variable"):
            if tau == 0.0 and mode == "variable":
                continue
            cells = []
            for name, _ in EVAL:
                r = next((x for x in probe if x["scenario"] == name and x["tau_s"] == tau
                          and x["mode"] == mode), None)
                cells.append(f"{r['dir_mean']:8.3f}/{r['speed_mean']:+9.2f}".rjust(22) if r
                             else f"{'-':>22s}")
            print(f"  {tau:5.1f} {mode:9s} " + "".join(cells))

    print("\n" + "=" * 104)
    print("★ τ 게이트 — E3x(현행 1.43배 팽창) 커버리지 / ★위험측, 5 시나리오 평균")
    print("=" * 104)
    print(f"  {'τ(s)':>5s} {'모드':9s} {'W배율':>6s} | "
          + "".join(f"{int(d)}m 커버/위험".rjust(20) for d in ETA_DISTS))
    for tau in TAUS:
        for mode in ("uniform", "variable"):
            if tau == 0.0 and mode == "variable":
                continue
            for wm in (1.0, 0.5):
                sel = [r for r in rows if r["tau_s"] == tau and r["mode"] == mode
                       and r["warm_mult"] == wm]
                if not sel:
                    continue
                cells = []
                for d in ETA_DISTS:
                    s = [r for r in sel if r["dist_m"] == d]
                    cells.append(f"{np.mean([x['E3x_cov_pct'] for x in s]):7.1f}/"
                                 f"{np.mean([x['E3x_breach_early_pct'] for x in s]):6.1f}".rjust(20))
                tag = "  ← 결합최악" if (wm == 0.5) else ""
                print(f"  {tau:5.1f} {mode:9s} {wm:6.1f} | " + "".join(cells) + tag)

    # ---------------- 판정 ----------------
    e3x_worst = max(r["E3x_breach_early_pct"] for r in rows)
    wc = max(rows, key=lambda r: r["E3x_breach_early_pct"])
    comb = [r for r in rows if r["warm_mult"] == 0.5]
    comb_worst = max(r["E3x_breach_early_pct"] for r in comb) if comb else 0.0
    tau10 = [r for r in rows if r["tau_s"] == 10.0 and r["warm_mult"] == 1.0]
    tau10_worst = max(r["E3x_breach_early_pct"] for r in tau10) if tau10 else 0.0
    lead10 = [x["lead_mean"] for x in probe if x["tau_s"] == 10.0]

    print("\n" + "=" * 104)
    print("★ 판정")
    print("=" * 104)
    print(f"  E3x 최악 위험측 = {e3x_worst:.1f} %  "
          f"({wc['scenario']} @{wc['dist_m']:.0f}m, τ={wc['tau_s']:.0f}s/{wc['mode']}, W×{wc['warm_mult']})")
    print(f"    · τ=10 s 단독(W×1.0) 최악 = {tau10_worst:.1f} %")
    print(f"    · 결합최악(W×0.5 ∧ τ=10 s) 최악 = {comb_worst:.1f} %")
    print(f"    · τ=10 s에서 사망시각 선행 = {np.mean(lead10):+.2f} s "
          f"(기준 −6.44 s 대비 {np.mean(lead10)+6.44:+.2f} s 잠식)")
    x2_worst = max(r["E3x2_breach_early_pct"] for r in rows)
    x2c = max((r["E3x2_breach_early_pct"] for r in comb), default=0.0)
    w_x = np.mean([r["E3x_width_s"] for r in rows if r["dist_m"] == 100.0])
    w_x2 = np.mean([r["E3x2_width_s"] for r in rows if r["dist_m"] == 100.0])

    print("\n" + "=" * 104)
    print("★ (B)안 추가 팽창 E3x2 — 이른끝을 **보정하지 않음**(shift 0). 근거: τ·W 둘 다 미지면 선행 마진이 0일 수 있음")
    print("=" * 104)
    print(f"  {'τ(s)':>5s} {'모드':9s} {'W배율':>6s} | "
          + "".join(f"{int(d)}m 커버/위험/폭".rjust(22) for d in ETA_DISTS))
    for tau in TAUS:
        for mode in ("uniform", "variable"):
            if tau == 0.0 and mode == "variable":
                continue
            for wm in (1.0, 0.5):
                sel = [r for r in rows if r["tau_s"] == tau and r["mode"] == mode
                       and r["warm_mult"] == wm]
                if not sel:
                    continue
                cells = []
                for d in ETA_DISTS:
                    s = [r for r in sel if r["dist_m"] == d]
                    cells.append(f"{np.mean([x['E3x2_cov_pct'] for x in s]):6.1f}/"
                                 f"{np.mean([x['E3x2_breach_early_pct'] for x in s]):5.1f}/"
                                 f"{np.mean([x['E3x2_width_s'] for x in s]):6.1f}".rjust(22))
                print(f"  {tau:5.1f} {mode:9s} {wm:6.1f} | " + "".join(cells))

    print(f"\n  E3x2 최악 위험측 = {x2_worst:.1f} %  (결합최악 {x2c:.1f} %)  ·  "
          f"100 m 폭 {w_x:.1f} s → {w_x2:.1f} s ({w_x2/w_x:.2f}배)")

    if e3x_worst <= 10.0:
        v = ("(A) 현행 E3x(1.43배)가 τ까지 흡수 — 추가 조치 불요. "
             "주장: 'warm_scale ±50 % + τ ≤ 10 s까지 강건'")
    elif x2_worst <= 10.0:
        v = (f"(B) 현행 E3x로는 부족(최악 {e3x_worst:.1f} %)하나 **E3x2**(이른끝 무보정)가 흡수"
             f"(최악 {x2_worst:.1f} %) → E3x2 채택, 100 m 폭 {w_x2/w_x:.2f}배 추가 확대를 정직 보고")
    else:
        v = (f"(C) E3x2로도 위험측 지배(최악 {x2_worst:.1f} %) → "
             f"**τ 실측·보정 없이는 실물 ETA 밴드 주장 불가**. τ 보정은 Part B(실측) 이후에만")
    print(f"\n  → **판정: {v}**")
    return rows, probe, bias, floors, seeds, args


if __name__ == "__main__":
    main()
