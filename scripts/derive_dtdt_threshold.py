"""derive_dtdt_threshold.py — #2e-2 Fix B의 dT/dt 임계를 **baseline에서 먼저** 도출.

규율(지시서 #2e-2 §규율2, [D-030] 선례): 임계는 **정당한 화재사망들의 상승률 분포**에서 정한다.
**S10/S11(테스트 시나리오)의 점수는 도출에 일절 쓰지 않는다** — 테스트 점수로 스윕하면 overfit.

도출 모집단 = baseline 계열(비열화를 지켜야 하는 바로 그 시나리오들):
  S1(정상) · S2a(바람 5/10/20°) · S2b(돌풍 20/40%) · S4(배치 10/20/40%) · S5(dropout .02~.30) · S6(밀도 9~25)
  전부 `n_nonfire_deaths=0` → 확정된 죽음은 **모두 정당한 화재사망**이다.

두 모집단을 따로 본다:
  (i) 전체 정당 화재사망 — 크고 안정적인 분포.
  (ii) **분기③ 표본부족 경로를 실제로 통과한** 정당 화재사망 — 게이트가 실제로 심판하게 될 대상.
      (기본 플래그 off 상태에서 `verifier.sample_poor_log`의 by="lenient" 항목)

**사전 선언한 선택 규칙**(수치를 보기 전에 고정):
  후보 = 각 모집단의 `mean − 3σ`([D-030]이 residual에 쓴 것과 같은 형태)와 `p1`(1퍼센타일).
  최종 임계 = **네 후보 중 가장 낮은(=가장 관대한) 양수 값**. 근거: 이 프로젝트의 하드 규칙은
  DoD-1 **baseline 비열화**이므로, 애매하면 정당한 화재사망을 잃지 않는 쪽으로 기운다.
  (COOL 차단력이 떨어지면 그건 그대로 정직하게 보고한다.)
"""
import argparse
import csv
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

GRIDS = {9: (3, 3), 12: (4, 3), 16: (4, 4), 20: (4, 5), 25: (5, 5)}

# baseline 계열만. S3(방사)·S7(복합)은 위 축들의 조합이라 중복, S8~S11은 도출 금지(테스트 시나리오).
LEVELS = (
    [("S1", {})]
    + [(f"S2a_{d}", {"wind_noise_deg": float(d)}) for d in (5, 10, 20)]
    + [(f"S2b_{int(p*100)}", {"wind_speed_var_pct": p}) for p in (0.2, 0.4)]
    + [(f"S4_{int(p*100)}", {"placement_jitter": p}) for p in (0.1, 0.2, 0.4)]
    + [(f"S5_{p}", {"p_dropout": p}) for p in (0.02, 0.05, 0.10, 0.20, 0.30)]
    + [(f"S6_n{n}", {"grid_rows": GRIDS[n][1], "grid_cols": GRIDS[n][0], "p_dropout": 0.05})
       for n in (9, 12, 20, 25)]
)


def stats(v, label):
    a = np.array(v, dtype=float)
    if a.size == 0:
        print(f"  {label:34s}  표본 없음")
        return None
    d = {
        "population": label, "n": int(a.size),
        "min": round(float(a.min()), 3), "p1": round(float(np.percentile(a, 1)), 3),
        "p5": round(float(np.percentile(a, 5)), 3), "median": round(float(np.median(a)), 3),
        "mean": round(float(a.mean()), 3), "std": round(float(a.std()), 3),
        "mean_minus_3sigma": round(float(a.mean() - 3 * a.std()), 3),
        "max": round(float(a.max()), 3),
    }
    print(f"  {label:34s}  n={d['n']:5d}  min={d['min']:7.2f}  p1={d['p1']:7.2f}  "
          f"p5={d['p5']:7.2f}  median={d['median']:7.2f}  mean={d['mean']:7.2f}±{d['std']:.2f}  "
          f"mean-3σ={d['mean_minus_3sigma']:7.2f}")
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--outdir", default=os.path.join("results", "stress"))
    args = ap.parse_args()
    seeds = range(1, args.seeds + 1)

    print("#2e-2 dT/dt 임계 도출 — baseline 계열만(S10/S11 미사용, 테스트 점수 스윕 금지)")
    print(f"  레벨 {len(LEVELS)}종 × {args.seeds}시드, 창 = Config().dtdt_window_s "
          f"= {Config().dtdt_window_s}s\n")

    all_slopes, poor_slopes, per_level = [], [], []
    for name, ov in LEVELS:
        lv_all, lv_poor = [], []
        for sd in seeds:
            # ★ 레거시(관대 채택) 고정: 도출 모집단 (ii)는 '분기③ 표본부족을 통과한' 죽음이라
            #   관대 채택 경로가 살아 있어야 관찰된다. [D-036]으로 기본값이 Fix A가 된 뒤에도
            #   이 스크립트의 산출물(임계 5.3의 근거)이 재현되도록 여기서 명시 고정한다.
            cfg = Config(mode="ours", seed=sd, nonfire_strict_gate=False, dtdt_gate=False, **ov)
            eng = Engine(cfg)
            for _ in eng.stream():
                pass
            poor_ids = {r["uid"] for r in eng.verifier.sample_poor_log if r["by"] == "lenient"}
            for uid in eng.verifier.confirmed:
                nd = eng.by_id[uid]
                if nd.death_t is None or nd.nonfire:         # 정당한 화재사망만
                    continue
                sl = eng.net.rep_slope(uid)
                if sl is None:
                    continue
                lv_all.append(sl)
                if uid in poor_ids:
                    lv_poor.append(sl)
        all_slopes += lv_all
        poor_slopes += lv_poor
        a = np.array(lv_all, dtype=float)
        per_level.append({"level": name, "n": len(lv_all), "n_sample_poor": len(lv_poor),
                          "min": round(float(a.min()), 3) if a.size else None,
                          "p1": round(float(np.percentile(a, 1)), 3) if a.size else None,
                          "mean": round(float(a.mean()), 3) if a.size else None,
                          "std": round(float(a.std()), 3) if a.size else None})
        print(f"  [{name:9s}] 정당 화재사망 {len(lv_all):4d}건 "
              f"(그중 분기③ 표본부족 {len(lv_poor):3d}건)")

    print("\n분포 (℃/s)")
    d_all = stats(all_slopes, "(i) 전체 정당 화재사망")
    d_poor = stats(poor_slopes, "(ii) 분기③ 표본부족 통과분")

    cands = []
    for d in (d_all, d_poor):
        if d:
            cands += [(f"{d['population']} mean-3σ", d["mean_minus_3sigma"]),
                      (f"{d['population']} p1", d["p1"])]
    print("\n후보 (사전 선언 규칙: 양수 후보 중 **가장 낮은 값** = baseline 비열화 우선)")
    for lab, v in cands:
        print(f"    {lab:44s} {v:8.3f}")
    pos = [v for _, v in cands if v > 0]
    thr = round(min(pos), 1) if pos else None
    print(f"\n  → 채택 임계 dtdt_min_c_per_s = {thr} ℃/s"
          f"   (현재 config 값 = {Config().dtdt_min_c_per_s})")
    if thr is not None and d_all:
        below = sum(1 for x in all_slopes if x < thr)
        print(f"    이 임계에서 정당 화재사망 중 임계 미만 = {below}/{len(all_slopes)} "
              f"({below/len(all_slopes)*100:.2f} %)  ← 잠재적 오제외 상한(분기③ 표본부족일 때만 실제 적용)")
        if d_poor:
            b2 = sum(1 for x in poor_slopes if x < thr)
            print(f"    분기③ 표본부족 통과분 중 임계 미만 = {b2}/{len(poor_slopes)} "
                  f"({b2/len(poor_slopes)*100:.2f} %)  ← 실제 오제외 예상치")

    os.makedirs(args.outdir, exist_ok=True)
    rows = [x for x in (d_all, d_poor) if x]
    for r in rows:
        r["adopted_threshold_c_per_s"] = thr
    p = os.path.join(args.outdir, "summary_2e2_dtdt_threshold.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n  [csv] {p}")
    p2 = os.path.join(args.outdir, "summary_2e2_dtdt_by_level.csv")
    with open(p2, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(per_level[0].keys()))
        w.writeheader()
        w.writerows(per_level)
    print(f"  [csv] {p2}")


if __name__ == "__main__":
    main()
