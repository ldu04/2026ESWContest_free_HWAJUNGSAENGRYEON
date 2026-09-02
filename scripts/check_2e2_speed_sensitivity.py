"""check_2e2_speed_sensitivity.py — #2e-2 Fix B의 **정직한 한계 찾기**: 임계의 전선속도 의존성.

dT/dt 임계 5.3 ℃/s는 `speed_true=1.5 m/s`인 baseline에서 도출됐다. 그런데 물리적으로
    dT/dt = (peak−ambient)/warm_scale · e^(−d/warm_scale) · s
이므로 **상승률은 전선 속도 s에 비례한다.** 즉 **느린 불에서는 정당한 화재사망조차 평평해 보여**
Fix B가 그들을 비화재로 오제외할 수 있다. 이건 Fix A(속도 무관, 표본 없으면 무조건 제외)에는 없는 위험이다.

그래서 속도를 스윕하며 잰다(전선 속도는 ground-truth 파라미터이지 방어 파라미터가 아니다):
  ① 정당 화재사망의 dT/dt 분포가 임계 아래로 내려가는 지점
  ② baseline(주입 0)에서 Fix B가 실제로 죽음을 잃는지(확정 수·커버리지·방향오차)
  ③ 주입 4개에서 COOL 차단력이 유지되는지
결과가 나쁘면 그대로 보고한다 — 운용 조건(불이 느릴 때)을 명시하기 위한 측정이다.
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

SPEEDS = (0.4, 0.6, 0.8, 1.0, 1.5, 2.5)
# 플래그 명시 — [D-036]으로 기본값이 Fix A가 됐으므로 빈 dict는 '레거시'가 아니다.
VARIANTS = [("before", {"nonfire_strict_gate": False, "dtdt_gate": False}),
            ("FixA_strict", {"nonfire_strict_gate": True, "dtdt_gate": False}),
            ("FixB_dtdt", {"nonfire_strict_gate": False, "dtdt_gate": True})]


def run(seed, speed, ov, n_inj=0):
    # 느린 불은 격자를 다 지나가는 데 더 오래 걸린다. t_max를 속도에 반비례로 늘려
    # "불이 끝까지 지나간 뒤"를 동일 조건으로 비교한다(속도 자체의 효과만 남기기 위함).
    t_max = max(120.0, 120.0 * 1.5 / speed)
    cfg = Config(mode="ours", seed=seed, speed_true=speed, t_max=t_max,
                 n_nonfire_deaths=n_inj, **ov)
    eng = Engine(cfg)
    for _ in eng.stream():
        pass
    s = eng.summarize()
    fire_ids = [i for i in eng.verifier.confirmed
                if eng.by_id[i].death_t is not None and not eng.by_id[i].nonfire]
    slopes = [x for x in (eng.net.rep_slope(i) for i in fire_ids) if x is not None]
    cool_pass = cool_n = 0
    for nd in eng.nodes:
        if not nd.nonfire:
            continue
        if float(eng.fire.temp_at(nd.pos, float(nd.death_t))) < cfg.warn_temp - 10.0:
            cool_n += 1
            cool_pass += int(nd.id in eng.verifier.confirmed)
    return {
        "dir": s["final_dir_err_deg"], "speed_err": s["final_speed_err_pct"],
        "confirmed": s["confirmed_deaths"], "fp": s["false_positive_rate"],
        "coverage": (len(eng.estimator.per_node) / len(eng.estimator.deaths))
                    if eng.estimator.deaths else 0.0,
        "slopes": slopes, "cool_n": cool_n, "cool_pass": cool_pass,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--outdir", default=os.path.join("results", "stress"))
    args = ap.parse_args()
    seeds = range(1, args.seeds + 1)
    thr = Config().dtdt_min_c_per_s
    print(f"#2e-2 Fix B 임계의 전선속도 의존성 — 임계 {thr} ℃/s는 speed_true=1.5에서 도출됨\n")
    print(f"  {'속도':>5s} {'정당사망 dT/dt(평균±std)':>24s} {'임계미만%':>9s} "
          f"| {'변이':12s} {'방향°':>8s} {'확정수':>7s} {'커버':>7s} {'COOL통과':>9s}")

    rows = []
    for sp in SPEEDS:
        base_slopes = []
        for i, (vn, ov) in enumerate(VARIANTS):
            r0 = [run(sd, sp, ov, 0) for sd in seeds]                 # baseline(주입 0)
            r4 = [run(sd, sp, ov, 4) for sd in seeds]                 # 주입 4개
            sl = [x for r in r0 for x in r["slopes"]]
            if vn == "before":
                base_slopes = sl
            def m(rs, k):
                v = np.array([x[k] for x in rs if x[k] is not None], dtype=float)
                return round(float(v.mean()), 4) if v.size else None
            cn = sum(x["cool_n"] for x in r4)
            cp = sum(x["cool_pass"] for x in r4)
            row = {"speed_true": sp, "variant": vn,
                   "dir_err_base": m(r0, "dir"), "speed_err_base": m(r0, "speed_err"),
                   "confirmed_base": m(r0, "confirmed"), "coverage_base": m(r0, "coverage"),
                   "fp_base": m(r0, "fp"),
                   "dir_err_inj4": m(r4, "dir"),
                   "cool_n": cn, "cool_pass": cp,
                   "cool_pass_rate": round(cp / cn, 4) if cn else None}
            if vn == "before":
                a = np.array(base_slopes, dtype=float)
                row["slope_mean"] = round(float(a.mean()), 3) if a.size else None
                row["slope_std"] = round(float(a.std()), 3) if a.size else None
                row["slope_below_thr_pct"] = (round(float((a < thr).mean() * 100), 2)
                                              if a.size else None)
            rows.append(row)
            if vn == "before":
                head = (f"  {sp:5.1f} {(row['slope_mean'] or 0):14.2f}±{(row['slope_std'] or 0):<8.2f} "
                        f"{(row['slope_below_thr_pct'] or 0):8.1f}% ")
            else:
                head = " " * 41
            def f(v, w):
                return ("-" if v is None else str(v)).rjust(w)
            print(head + f"| {vn:12s} {f(row['dir_err_base'], 8)} {f(row['confirmed_base'], 7)} "
                         f"{f(row['coverage_base'], 7)} {f(row['cool_pass_rate'], 9)}")
        print()

    os.makedirs(args.outdir, exist_ok=True)
    p = os.path.join(args.outdir, "summary_2e2_speed_sensitivity.csv")
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  [csv] {p}")


if __name__ == "__main__":
    main()
