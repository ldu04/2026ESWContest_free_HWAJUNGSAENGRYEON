"""run_2e2_variants.py — #2e-2 · COOL 누수 차단 후보 3열 비교 (수정 전 / Fix A / Fix B).

#2e-1 진단: COOL(<50℃) 비화재 통과율 86.4 %, 그 98.9 %가 분기③ **'accepted 이웃 <3 → 관대 채택'**
([D-030]) 경로. 이 스크립트는 **그 지점만 바꾼** 두 후보를 같은 시드·같은 물리로 나란히 잰다.

  before  : 플래그 전부 off = #2d 원 방어(baseline 보존)
  Fix A   : nonfire_strict_gate — 표본 부족이면 제외(보수적 대조군)
  Fix B   : dtdt_gate — 표본 부족이면 **메시가 수신한 보고 온도 상승률 dT/dt**로 판정
            임계 5.3 ℃/s는 baseline 계열 정당 화재사망 분포(mean 10.73 − 3σ 1.82)에서 사전 도출 [D-034]

측정은 #2e-1과 **같은 정의**를 재사용한다(`run_nonfire_harm.run_one`): 그룹은 사망시점 참 국소온도로
COOL/WARM/HOT, 해악은 반사실 재적합(노드별 leave-one-out).

산출물: results/stress/
  summary_2e2_variant_groups.csv   (변이 × 그룹) 통과율·해악
  summary_2e2_variant_scale.csv    (변이 × 주입수) 방향/속도/변위·커버리지
  curve_2e2_variants.png           COOL 통과율 + 방향오차 비교
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sim.config import Config
from scripts.run_nonfire_harm import (COUNTS, GROUPS, ms, run_one, write_csv, _font)

# 각 팔은 플래그를 **명시**한다 — [D-036]으로 기본값이 Fix A가 됐으므로 빈 dict는 더 이상 '레거시'가 아니다.
VARIANTS = [
    ("before", {"nonfire_strict_gate": False, "dtdt_gate": False}),   # 레거시 관대 채택(#2d)
    ("FixA_strict", {"nonfire_strict_gate": True, "dtdt_gate": False}),  # ★ 현재 기본값
    ("FixB_dtdt", {"nonfire_strict_gate": False, "dtdt_gate": True}),    # 보존(현재 비활성)
]


def measure(ov, seeds):
    nodes, runs = [], []
    for n in COUNTS:
        for sd in seeds:
            run, inj = run_one(sd, n, ov)
            runs.append(run)
            for d in inj:
                nodes.append({
                    "seed": sd, "n_inject": n, "node_id": d["id"], "group": d["group"],
                    "confirmed": int(d["confirmed"]), "self_hot": int(d["self_hot"]),
                    "n_acc_nbrs_at_death": d["n_acc_nbrs_at_death"],
                    "dist_to_front_m": d["dist_to_front_m"],
                    "loo_dir_harm_deg": d["loo_dir_harm_deg"],
                    "loo_speed_harm_pct": d["loo_speed_harm_pct"],
                    "loo_disp_harm_m": d["loo_disp_harm_m"],
                })
    return nodes, runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--outdir", default=os.path.join("results", "stress"))
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))
    c = Config()
    print(f"#2e-2 변이 비교 — 주입수={COUNTS}, seeds={args.seeds}, "
          f"dT/dt 임계={c.dtdt_min_c_per_s} ℃/s (창 {c.dtdt_window_s}s)\n")

    data = {}
    for name, ov in VARIANTS:
        data[name] = measure(ov, seeds)
        print(f"  [{name}] 완료 — 주입 성립 {len(data[name][0])}개")

    # --- (변이 × 그룹) ---
    rows_g = []
    for name, _ in VARIANTS:
        nodes, _r = data[name]
        for g in GROUPS:
            sub = [d for d in nodes if d["group"] == g]
            if not sub:
                continue
            ps = [d for d in sub if d["confirmed"]]
            hd, hds, _ = ms([d["loo_dir_harm_deg"] for d in ps])
            hs, _x, _ = ms([d["loo_speed_harm_pct"] for d in ps])
            hp, _x, _ = ms([d["loo_disp_harm_m"] for d in ps])
            rows_g.append({
                "variant": name, "group": g, "n_nodes": len(sub), "n_passed": len(ps),
                "pass_rate": round(len(ps) / len(sub), 4),
                "loo_dir_harm_deg_mean": hd, "loo_dir_harm_deg_std": hds,
                "loo_speed_harm_pct_mean": hs, "loo_disp_harm_m_mean": hp,
            })
    write_csv(os.path.join(args.outdir, "summary_2e2_variant_groups.csv"), rows_g)

    # --- (변이 × 주입수) ---
    rows_s = []
    for name, _ in VARIANTS:
        _n, runs = data[name]
        for n in COUNTS:
            sub = [r for r in runs if r["n_inject"] == n]
            dm, ds, _ = ms([r["dir_full"] for r in sub])
            sm, _x, _ = ms([r["speed_full"] for r in sub])
            pm, _x, _ = ms([r["disp_full"] for r in sub])
            cm, _x, _ = ms([r["coverage"] for r in sub])
            fm, _x, _ = ms([r["fp_rate"] for r in sub])
            cd, _x, _ = ms([r["confirmed_deaths"] for r in sub])
            rows_s.append({
                "variant": name, "n_inject": n,
                "dir_err_deg_mean": dm, "dir_err_deg_std": ds,
                "speed_err_pct_mean": sm, "disp_m_mean": pm,
                "coverage_mean": cm, "fp_rate_mean": fm, "confirmed_deaths_mean": cd,
            })
    write_csv(os.path.join(args.outdir, "summary_2e2_variant_scale.csv"), rows_s)

    # ---------------- 콘솔 3열 표 ----------------
    def get(name, g, k):
        for r in rows_g:
            if r["variant"] == name and r["group"] == g:
                return r[k]
        return None

    print("\n" + "=" * 88)
    print("★ DoD-1 · COOL 통과율과 해악 — [수정 전 / Fix A / Fix B] 3열")
    print("=" * 88)
    print(f"  {'그룹':5s} {'지표':22s} " + "".join(f"{n:>16s}" for n, _ in VARIANTS))
    for g in GROUPS:
        for k, lbl, fmt in (("pass_rate", "통과율", "pct"),
                            ("loo_dir_harm_deg_mean", "LOO 방향해악 °", "f"),
                            ("loo_speed_harm_pct_mean", "LOO 속도해악 %p", "f"),
                            ("loo_disp_harm_m_mean", "LOO 변위해악 m", "f")):
            cells = []
            for n, _ in VARIANTS:
                v = get(n, g, k)
                if v is None:
                    cells.append(f"{'-':>16s}")
                elif fmt == "pct":
                    np_ = get(n, g, "n_passed")
                    nn = get(n, g, "n_nodes")
                    cells.append(f"{v*100:9.1f}% ({np_}/{nn})".rjust(16))
                else:
                    cells.append(f"{v:16.3f}")
            mark = " ★" if (g == "COOL" and k == "pass_rate") else ""
            print(f"  {g:5s} {lbl:22s} " + "".join(cells) + mark)
        print()

    print("=" * 88)
    print("DoD-2 · S11 조건에서의 방향오차·커버리지 (주입수별)")
    print("=" * 88)
    print(f"  {'주입':>4s} {'지표':14s} " + "".join(f"{n:>14s}" for n, _ in VARIANTS))
    for n in COUNTS:
        for k, lbl in (("dir_err_deg_mean", "방향오차 °"), ("speed_err_pct_mean", "속도오차 %"),
                       ("coverage_mean", "커버리지"), ("confirmed_deaths_mean", "확정 사망수"),
                       ("fp_rate_mean", "오탐률")):
            cells = []
            for vn, _ in VARIANTS:
                r = next(x for x in rows_s if x["variant"] == vn and x["n_inject"] == n)
                cells.append(f"{r[k]:14.4f}" if r[k] is not None else f"{'-':>14s}")
            print(f"  {n:4d} {lbl:14s} " + "".join(cells))
        print()

    # ---------------- 곡선 ----------------
    plt = _font()
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
    w = 0.25
    xs = np.arange(len(GROUPS))
    cols = {"before": "#7f8c8d", "FixA_strict": "#8e44ad", "FixB_dtdt": "#c0392b"}
    for i, (name, _) in enumerate(VARIANTS):
        axes[0].bar(xs + (i - 1) * w, [get(name, g, "pass_rate") or 0 for g in GROUPS],
                    w, label=name, color=cols[name])
    axes[0].set_xticks(xs)
    axes[0].set_xticklabels(GROUPS)
    axes[0].set_ylabel("교차검증 통과율")
    axes[0].set_title("(a) 그룹별 통과율 — COOL이 낮아야 성공", fontsize=10)
    axes[0].legend(fontsize=8)
    axes[0].grid(True, axis="y", alpha=0.3)
    for name, _ in VARIANTS:
        ys = [next(x for x in rows_s if x["variant"] == name and x["n_inject"] == n)["dir_err_deg_mean"]
              for n in COUNTS]
        axes[1].plot(COUNTS, ys, marker="o", lw=2, color=cols[name], label=name)
    axes[1].set_xlabel("비화재 사망 주입 수 (16노드 중)")
    axes[1].set_ylabel("방향오차 (°)")
    axes[1].set_xticks(list(COUNTS))
    axes[1].axvspan(0.8, 2.2, color="#27ae60", alpha=0.12)
    axes[1].set_title("(b) 방향오차 (녹색 = 현실적 1~2개)", fontsize=10)
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.3)
    fig.suptitle(f"#2e-2 COOL 누수 차단 후보 비교 (dT/dt 임계 {c.dtdt_min_c_per_s} C/s)", fontsize=11)
    fig.tight_layout()
    p = os.path.join(args.outdir, "curve_2e2_variants.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    print(f"  [png] {p}")


if __name__ == "__main__":
    main()
