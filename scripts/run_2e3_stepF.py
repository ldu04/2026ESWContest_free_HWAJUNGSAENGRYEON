"""run_2e3_stepF.py — #2e-3 Step 2.F · E3 밴드의 **warm_scale 미스매치 게이트**.

왜: E3의 편향 항은 시뮬 S1의 `warm_scale = W0 = 6 m`에서 도출됐다([D-040]).
실물의 warm_scale이 다르면 밴드가 무너질 수 있다. **이 게이트를 통과해야만** 보고서가 밴드를
'실물 대비 유효'로 주장할 수 있고, 통과 전엔 '시뮬 캘리브레이션 전제'로만 쓸 수 있다.

★ 규율: **강건성 시험이지 튜닝이 아니다.**
  - E3 편향 항은 **W0 도출값으로 고정**한다. 미스매치 세계에서 **재적합 금지.**
  - estimator·방어 파라미터 불변. `sim/` 무수정.
  - 평가 세계(S2~S11)의 실제 warm_scale만 W0×(1±0.2/±0.3/±0.5)로 틀리게 준다.

물리적 예측(측정 전에 적어 둔다 — 맞든 틀리든 그대로 보고)
------------------------------------------------------
노드는 자기 온도가 `temp_threshold`에 닿을 때 마지막 보고를 낸다. 그 순간 전선까지 거리는
    d_thresh = W · ln((peak−ambient)/(threshold−ambient)) = W · ln 5
이므로 **선행시간 ∝ W**다. 따라서
  · **W가 크면**  실제 선행↑ → 예측이 더 이르다 → W0 기준 E3는 **과소보정** →
                 밴드가 여전히 이르다 → 참 도착이 **늦은끝보다 늦음**(`breach_late`, **안전측**).
  · **W가 작으면** 실제 선행↓ → W0 기준 E3는 **과대보정** → 밴드가 너무 늦게 이동 →
                 참 도착이 **이른끝보다 이름**(`breach_early`, **★위험측**).
→ 지시서 가설("W가 크면 위험측")과 **부호가 반대**로 예상된다. 측정이 정본이다.

(B)안 팽창 밴드 E3x — 물리에서 도출, 점수 보고 조정하지 않음
-------------------------------------------------------
편향은 선행시간 ∝ W 이므로, W가 [rW0, RW0] 범위에 있다고 선언하면 편향도 대략 그 배율로 흔들린다.
  이른끝 이동 = (−q95) × r   (가장 적게 보정 → 이른끝을 더 이르게 = 보수적)
  늦은끝 이동 = (−q05) × R   (가장 많이 보정 → 늦은끝을 더 늦게 = 커버 확대)
r·R은 **선언한 warm_scale 불확실 범위**에서 오는 값이지 테스트 점수에서 오지 않는다.
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
from scripts.run_2e3_diagnose import ETA_DISTS
from scripts.run_2e3_stepE import run_one, OUTDIR

MULTS = (0.5, 0.7, 0.8, 1.0, 1.2, 1.3, 1.5)          # W0×(1±0.5/±0.3/±0.2) + 기준
EXPAND_R, EXPAND_R_HI = 0.5, 1.5                      # (B)안 팽창: 선언한 warm_scale 범위 ±50 %

# 평가는 **S2~S11**에서만(도출 세트 S1 제외)
EVAL = [
    ("S2a_10",   {"wind_noise_deg": 10.0}),
    ("S2a_20",   {"wind_noise_deg": 20.0}),
    ("S2b_40",   {"wind_speed_var_pct": 0.4}),
    ("S4_40",    {"placement_jitter": 0.4}),
    ("S6_n9",    {"grid_rows": 3, "grid_cols": 3, "p_dropout": 0.05}),
    ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                  "placement_jitter": 0.2, "p_dropout": 0.10}),
]
# 부수(선택) 2차 민감도: 편향 항의 '기울기' 부분은 warm_scale이 아니라 사망시각 노이즈 모델 의존
SECONDARY = [("clock_0ms", {}), ("clock_100ms", {"clock_jitter_ms": 100.0}),
             ("clock_300ms", {"clock_jitter_ms": 300.0}),
             ("temp_0.5s", {"temp_jitter_s": 0.5})]


def derive_bias_at_W0(seeds):
    """★도출 — S1, W0(기본 warm_scale)에서만. 이후 어떤 시험 세계에서도 **고정**한다."""
    s1 = []
    for sd in seeds:
        r, _s = run_one(sd, {}, floor_pct=0.0)
        s1 += r
    bias = {}
    for d in ETA_DISTS:
        e = np.array([x["eta_point"] - x["eta_true"] for x in s1 if x["dist"] == d])
        bias[d] = (float(np.percentile(e, 5)), float(np.percentile(e, 95)))
    return bias


def evaluate(seeds, ov, floor_pct, bias, mult_note=""):
    """고정 편향항으로 E3/E3x 커버리지·breach 측정."""
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
        rec = {"dist_m": d, "n": len(sub), "eta_true_mean_s": round(float(tr.mean()), 1)}
        for tag, sl, sh in (("E3", -q95, -q05),
                            ("E3x", -q95 * EXPAND_R, -q05 * EXPAND_R_HI)):
            lo, hi = lo0 + sl, hi0 + sh
            rec[f"{tag}_cov_pct"] = round(float(((tr >= lo) & (tr <= hi)).mean()) * 100, 1)
            rec[f"{tag}_breach_early_pct"] = round(float((tr < lo).mean()) * 100, 1)
            rec[f"{tag}_breach_late_pct"] = round(float((tr > hi).mean()) * 100, 1)
            rec[f"{tag}_width_s"] = round(float((hi - lo).mean()), 1)
        out.append(rec)
    return out


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
    W0 = Config().warm_scale

    floors = {}
    p = os.path.join(OUTDIR, "summary_2e3_20_floor_decomposition.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8")):
            fs = float(r["F_sampling_physics"]) if r.get("F_sampling_physics") else 0.0
            floors[r["scenario"]] = max(fs, float(r["floor_canonical_vs_bar"] or 0.0))

    print("#2e-3 Step 2.F · E3 밴드의 warm_scale 미스매치 게이트 (강건성 시험, 재적합 금지)")
    print(f"  W0 = {W0} m,  d_thresh = W·ln5 → 선행시간 ∝ W")
    for m in MULTS:
        W = W0 * m
        print(f"    W={W:4.1f} m ({m:+.0%} 대비 W0)  d_thresh={W*math.log(5):5.2f} m  "
              f"선행시간={W*math.log(5)/1.5:5.2f} s")
    print()

    bias = derive_bias_at_W0(seeds)
    print("  ★고정 편향항(W0=6 m, S1에서 도출 — 아래 어떤 세계에서도 재적합하지 않음):")
    for d in ETA_DISTS:
        print(f"    {d:5.0f} m: q05={bias[d][0]:+7.2f}s  q95={bias[d][1]:+7.2f}s")
    print()

    rows = []
    for name, ov in EVAL:
        fl = floors.get(name, 0.0)
        for m in MULTS:
            ov2 = dict(ov)
            ov2["warm_scale"] = W0 * m
            for rec in evaluate(seeds, ov2, fl, bias):
                rec.update({"scenario": name, "warm_mult": m, "warm_scale_m": round(W0 * m, 2)})
                rows.append(rec)
        print(f"  [{name:9s}] 7개 warm_scale 완료")
    write_csv(os.path.join(args.outdir, "summary_2e3_F_warmscale_gate.csv"), rows)

    # ---------------- 표 ----------------
    print("\n" + "=" * 104)
    print("★ warm_scale 미스매치 — E3(고정 편향항) 커버리지 / ★위험측(breach_early) / 보수초과")
    print("=" * 104)
    print(f"  {'배율':>6s} {'W(m)':>6s} | " + "".join(f"{int(d)}m 커버/위험/보수".rjust(24) for d in ETA_DISTS))
    for m in MULTS:
        cells = []
        for d in ETA_DISTS:
            sub = [r for r in rows if r["warm_mult"] == m and r["dist_m"] == d]
            cov = np.mean([r["E3_cov_pct"] for r in sub])
            be = np.mean([r["E3_breach_early_pct"] for r in sub])
            bl = np.mean([r["E3_breach_late_pct"] for r in sub])
            cells.append(f"{cov:6.1f}/{be:6.1f}/{bl:6.1f}".rjust(24))
        mark = "  ← 도출 조건" if m == 1.0 else ""
        print(f"  {m:+6.0%} {W0*m:6.2f} | " + "".join(cells) + mark)

    print("\n" + "=" * 104)
    print("★ 비대칭 보고 — warm_scale 어느 부호가 이른끝을 뚫는가")
    print("=" * 104)
    lo_m = [m for m in MULTS if m < 1.0]
    hi_m = [m for m in MULTS if m > 1.0]
    be_lo = np.mean([r["E3_breach_early_pct"] for r in rows if r["warm_mult"] in lo_m])
    be_hi = np.mean([r["E3_breach_early_pct"] for r in rows if r["warm_mult"] in hi_m])
    bl_lo = np.mean([r["E3_breach_late_pct"] for r in rows if r["warm_mult"] in lo_m])
    bl_hi = np.mean([r["E3_breach_late_pct"] for r in rows if r["warm_mult"] in hi_m])
    print(f"  W 과소(0.5~0.8×): ★위험측 {be_lo:5.1f} %   보수초과 {bl_lo:5.1f} %")
    print(f"  W 과대(1.2~1.5×): ★위험측 {be_hi:5.1f} %   보수초과 {bl_hi:5.1f} %")
    print(f"  → 이른끝을 뚫는 쪽은 **W {'과소' if be_lo > be_hi else '과대'}**")
    print(f"     (지시서 가설은 'W 과대 → 위험측'. 측정 결과와 {'일치' if be_hi > be_lo else '**반대**'})")

    worst_be = max(r["E3_breach_early_pct"] for r in rows)
    worst_cell = max(rows, key=lambda r: r["E3_breach_early_pct"])
    base_cov = np.mean([r["E3_cov_pct"] for r in rows if r["warm_mult"] == 1.0])
    mm_cov = np.mean([r["E3_cov_pct"] for r in rows if r["warm_mult"] != 1.0])

    print("\n" + "=" * 104)
    print("★ (B)안 팽창 밴드 E3x — 선언한 warm_scale 범위 ±50 %에서 물리로 도출(점수 조정 아님)")
    print("=" * 104)
    print(f"  {'배율':>6s} | " + "".join(f"{int(d)}m E3x 커버/위험/폭(s)".rjust(26) for d in ETA_DISTS))
    for m in MULTS:
        cells = []
        for d in ETA_DISTS:
            sub = [r for r in rows if r["warm_mult"] == m and r["dist_m"] == d]
            cells.append(f"{np.mean([r['E3x_cov_pct'] for r in sub]):6.1f}/"
                         f"{np.mean([r['E3x_breach_early_pct'] for r in sub]):5.1f}/"
                         f"{np.mean([r['E3x_width_s'] for r in sub]):6.1f}".rjust(26))
        print(f"  {m:+6.0%} | " + "".join(cells))
    worst_be_x = max(r["E3x_breach_early_pct"] for r in rows)
    w_e3 = np.mean([r["E3_width_s"] for r in rows if r["dist_m"] == 100.0])
    w_e3x = np.mean([r["E3x_width_s"] for r in rows if r["dist_m"] == 100.0])

    print("\n" + "=" * 104)
    print("★ 판정")
    print("=" * 104)
    print(f"  E3  최악 위험측 = {worst_be:.1f} %  ({worst_cell['scenario']} @{worst_cell['dist_m']:.0f}m, "
          f"W×{worst_cell['warm_mult']:.1f})")
    print(f"  E3  커버리지: 도출조건 {base_cov:.1f} %  vs 미스매치 평균 {mm_cov:.1f} %  "
          f"(저하 {base_cov-mm_cov:+.1f} %p)")
    print(f"  E3x 최악 위험측 = {worst_be_x:.1f} %   ·  100 m 폭 {w_e3:.1f} s → {w_e3x:.1f} s "
          f"({w_e3x/w_e3:.2f}배)")
    if worst_be <= 10.0 and (base_cov - mm_cov) < 10.0:
        v = "(A) 강건 — '실물 대비 유효(명시된 warm_scale 범위 내)' 주장 가능"
    elif worst_be_x <= 10.0:
        v = "(B) 팽창 밴드로 breach 잡힘 — E3x 채택, 폭 정직 보고. '±50 % warm_scale까지 강건' 주장"
    else:
        v = "(C) 팽창으로도 못 잡음 — 시뮬 전용. '시뮬 캘리브레이션 전제, 실물 재캘리브레이션 필요' 명시"
    print(f"\n  → **판정: {v}**")

    # ---------------- 부수: 2차 민감도 ----------------
    print("\n" + "=" * 104)
    print("부수(2차 민감도) — 편향항의 '기울기' 부분은 사망시각 노이즈 모델 의존. W0 고정, 노이즈만 변경")
    print("=" * 104)
    sec = []
    for name, ov in EVAL[:2]:
        for sname, sov in SECONDARY:
            o = dict(ov)
            o.update(sov)
            for rec in evaluate(seeds, o, floors.get(name, 0.0), bias):
                rec.update({"scenario": name, "noise": sname})
                sec.append(rec)
    write_csv(os.path.join(args.outdir, "summary_2e3_F_noise_sensitivity.csv"), sec)
    print(f"  {'시나리오':9s} {'노이즈':12s} " + "".join(f"{int(d)}m 커버/위험".rjust(18) for d in ETA_DISTS))
    for name, _ in EVAL[:2]:
        for sname, _ in SECONDARY:
            cells = []
            for d in ETA_DISTS:
                r = next((x for x in sec if x["scenario"] == name and x["noise"] == sname
                          and x["dist_m"] == d), None)
                cells.append((f"{r['E3_cov_pct']:6.1f}/{r['E3_breach_early_pct']:5.1f}"
                              if r else "-").rjust(18))
            print(f"  {name:9s} {sname:12s} " + "".join(cells))


if __name__ == "__main__":
    main()
