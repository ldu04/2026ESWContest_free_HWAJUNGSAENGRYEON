"""run_2j_a.py — 2.J 파트 A · **실측 τ에서 방향(direction) 강건성** 재검증.

배경: H1 τ 실측(강제대류 11 s / 정지공기 78.5 s)이 기존 검증 울타리 {0,2,5,10} s를 벗어났다.
      "방향 2.1°가 실측 τ에서도 버티나"는 한 번도 재본 적이 없다. 그걸 잰다.

★ 강령 준수 (변수 오염·동어반복 방지)
  · **estimator 손대지 않음** — 평면 최소자승 → ∇T → 방향. 파일 불변.
  · **threshold·전선·노드배치 불변** — τ만 주입한다.
  · **곡선 전선 필수 포함** — 직선만 쓰면 P4a 효과가 숨어 낙관 편향된다. 직선은 대조군.
  · 결론 문장 쓰지 않음. 데이터·그래프만.

★ 사전등록 예측 (측정 전에 기록 — 틀리면 틀렸다고 남긴다)
  A1: τ↑ → 방향오차 단조 증가. 단 **붕괴(>10°) 없이 한 자릿수 도 이내**에 머문다.
      (상수 지연 성분은 기울기에서 상쇄되고, 오염은 dT/dt 불균일이라는 2차 효과뿐이므로)
  A2: **노드별 지터 τ가 균일 τ보다 방향을 더 망친다** (지터는 상수 상쇄가 안 되므로).

★ t_max 이중 실행 (truncation vs τ 물리 분리)
  τ가 크면 t_max=120 s 안에 임계를 못 넘어 죽지 못하는 노드가 생긴다. 그건 **시간 절단
  아티팩트**이지 τ의 물리가 아니다. 그래서 배포 조건(t_max=120)과 연장 조건(t_max=400)을
  **둘 다** 돌려 나란히 싣는다. 어느 쪽도 숨기지 않는다.
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
from sim.metrics import angle_deg

OUTDIR = os.path.join("results", "stress")

# 실측 두 점(11, 78.5) 필수 포함
TAUS_UNIFORM = (0.0, 2.0, 5.0, 10.0, 11.0, 20.0, 30.0, 50.0, 78.5, 100.0)
TAUS_JITTER = (11.0, 30.0, 78.5)
JITTER_SIGMA = 0.3
T_MAXES = (120.0, 400.0)

# 곡선 전선(바람) 필수 + 직선 대조군
FRONTS = [
    ("straight_S1",  {}),                          # 대조군: 직선 전선
    ("curved_S2a10", {"wind_noise_deg": 10.0}),    # 곡선
    ("curved_S2a20", {"wind_noise_deg": 20.0}),    # 곡선(2.G/2.H에서 방향 열화 관측된 조건)
]


def run_one(seed, front_ov, tau, t_max, jitter=0.0):
    cfg = Config(mode="ours", seed=seed, sensor_tau_s=tau,
                 sensor_tau_var_pct=jitter,
                 sensor_tau_var_dist=("gauss" if jitter > 0 else "uniform"),
                 t_max=t_max, **front_ov)
    eng = Engine(cfg)
    for _ in eng.stream():
        pass

    dir_err = (angle_deg(eng.estimator.dir_global, cfg.direction())
               if eng.estimator.dir_global else None)
    speed_err = ((eng.estimator.speed_global - cfg.speed_true) / cfg.speed_true * 100.0
                 if eng.estimator.speed_global else None)

    n_nonsink = sum(1 for nd in eng.nodes if not nd.is_sink)
    n_died = sum(1 for nd in eng.nodes if (not nd.is_sink) and nd.death_t is not None)
    return {"dir_err": dir_err, "speed_err": speed_err,
            "n_nonsink": n_nonsink, "n_died": n_died,
            "n_missed": n_nonsink - n_died,
            "n_confirmed": len(eng.estimator.deaths),
            "coverage": len(eng.estimator.per_node)}


def agg(rows, k):
    v = [r[k] for r in rows if r.get(k) is not None]
    if not v:
        return None, None
    return round(float(np.mean(v)), 4), round(float(np.std(v)), 4)


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


def plot(rows, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    avail = {f.name for f in font_manager.fontManager.ttflist}
    for fam in ("Malgun Gothic", "NanumGothic", "AppleGothic", "Noto Sans CJK KR"):
        if fam in avail:
            plt.rcParams["font.family"] = fam
            break
    plt.rcParams["axes.unicode_minus"] = False

    for tm in T_MAXES:
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8))
        cols = {"straight_S1": "#7f8c8d", "curved_S2a10": "#2980b9", "curved_S2a20": "#c0392b"}

        # (a) 방향오차 vs τ
        ax = axes[0]
        for name, _ in FRONTS:
            sub = sorted([r for r in rows if r["front"] == name and r["mode"] == "uniform"
                          and r["t_max"] == tm], key=lambda r: r["tau_s"])
            if not sub:
                continue
            xs = [r["tau_s"] for r in sub]
            ys = [r["dir_err_mean"] for r in sub]
            es = [r["dir_err_std"] or 0 for r in sub]
            ax.errorbar(xs, ys, yerr=es, marker="o", lw=2, capsize=3,
                        color=cols[name], label=f"{name} (uniform)")
            j = sorted([r for r in rows if r["front"] == name and r["mode"] == "jitter"
                        and r["t_max"] == tm], key=lambda r: r["tau_s"])
            if j:
                ax.plot([r["tau_s"] for r in j], [r["dir_err_mean"] for r in j],
                        marker="s", ls="--", lw=1.6, color=cols[name],
                        label=f"{name} (jitter s=0.3)")
        ax.axhline(5.0, color="k", ls=":", lw=1.5)
        ax.text(2, 5.3, "실용선 5°", fontsize=9)
        for t in (11.0, 78.5):
            ax.axvline(t, color="#27ae60", ls="-.", lw=1.2, alpha=0.7)
        ax.text(11, ax.get_ylim()[1] * 0.93, "실측 11s", fontsize=8, color="#1e8449")
        ax.text(78.5, ax.get_ylim()[1] * 0.85, "실측 78.5s", fontsize=8, color="#1e8449")
        ax.set_xlabel("센서 시상수 τ (s)")
        ax.set_ylabel("방향 오차 (°)")
        ax.set_title(f"(a) τ vs 방향오차   [t_max={tm:.0f}s]", fontsize=11)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7.5)

        # (b) 미탐지 노드 수 vs τ
        ax = axes[1]
        for name, _ in FRONTS:
            sub = sorted([r for r in rows if r["front"] == name and r["mode"] == "uniform"
                          and r["t_max"] == tm], key=lambda r: r["tau_s"])
            if not sub:
                continue
            ax.plot([r["tau_s"] for r in sub], [r["n_missed_mean"] for r in sub],
                    marker="o", lw=2, color=cols[name], label=name)
        ax.set_xlabel("센서 시상수 τ (s)")
        ax.set_ylabel("미탐지 노드 수 (평균)")
        ax.set_title(f"(b) τ vs 미탐지 노드   [t_max={tm:.0f}s]", fontsize=11)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)

        fig.suptitle(f"2.J-A  실측 τ 방향 강건성 (t_max={tm:.0f}s)", fontsize=12)
        fig.tight_layout()
        p = os.path.join(outdir, f"curve_2j_a_tmax{int(tm)}.png")
        fig.savefig(p, dpi=120)
        plt.close(fig)
        print(f"  [png] {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--outdir", default=OUTDIR)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))

    print("2.J-A · 실측 τ 방향 강건성 (estimator·threshold·전선 불변, τ만 주입)")
    print(f"  균일 τ: {TAUS_UNIFORM}")
    print(f"  지터 τ: μ={TAUS_JITTER}, τ_i ~ μ(1+N(0,{JITTER_SIGMA})), 0.5s 클립")
    print(f"  전선  : {[n for n, _ in FRONTS]}   (곡선 필수 포함, 직선은 대조군)")
    print(f"  t_max : {T_MAXES}  (절단 아티팩트와 τ 물리 분리용)")
    print(f"  시드  : {args.seeds}\n")

    raw, rows = [], []
    for tm in T_MAXES:
        for name, ov in FRONTS:
            for tau in TAUS_UNIFORM:
                rs = [run_one(sd, ov, tau, tm) for sd in seeds]
                for i, r in enumerate(rs):
                    raw.append({"t_max": tm, "front": name, "mode": "uniform",
                                "tau_s": tau, "seed": seeds[i], **r})
                dm, ds = agg(rs, "dir_err")
                sm, _ = agg(rs, "speed_err")
                mm, _ = agg(rs, "n_missed")
                cm, _ = agg(rs, "n_confirmed")
                rows.append({"t_max": tm, "front": name, "mode": "uniform", "tau_s": tau,
                             "dir_err_mean": dm, "dir_err_std": ds, "speed_err_mean": sm,
                             "n_missed_mean": mm, "n_confirmed_mean": cm,
                             "n_valid": sum(1 for r in rs if r["dir_err"] is not None)})
            for tau in TAUS_JITTER:
                rs = [run_one(sd, ov, tau, tm, jitter=JITTER_SIGMA) for sd in seeds]
                for i, r in enumerate(rs):
                    raw.append({"t_max": tm, "front": name, "mode": "jitter",
                                "tau_s": tau, "seed": seeds[i], **r})
                dm, ds = agg(rs, "dir_err")
                sm, _ = agg(rs, "speed_err")
                mm, _ = agg(rs, "n_missed")
                cm, _ = agg(rs, "n_confirmed")
                rows.append({"t_max": tm, "front": name, "mode": "jitter", "tau_s": tau,
                             "dir_err_mean": dm, "dir_err_std": ds, "speed_err_mean": sm,
                             "n_missed_mean": mm, "n_confirmed_mean": cm,
                             "n_valid": sum(1 for r in rs if r["dir_err"] is not None)})
            print(f"  [t_max={tm:.0f}  {name:14s}] 완료")

    write_csv(os.path.join(args.outdir, "raw_2j_a_dir_vs_tau.csv"), raw)
    write_csv(os.path.join(args.outdir, "summary_2j_a_dir_vs_tau.csv"), rows)
    plot(rows, args.outdir)

    # ---------------- 표 출력 (해석 없이 수치만) ----------------
    for tm in T_MAXES:
        print("\n" + "=" * 108)
        print(f"방향오차(°)  ±std   [t_max={tm:.0f}s]     · 실용선 5°")
        print("=" * 108)
        hdr = f"  {'τ(s)':>6s} {'모드':7s}"
        for n, _ in FRONTS:
            hdr += f"{n:>22s}"
        print(hdr + f"{'미탐지(직/곡10/곡20)':>24s}")
        for tau in TAUS_UNIFORM:
            for mode in ("uniform", "jitter"):
                sel = [r for r in rows if r["tau_s"] == tau and r["mode"] == mode
                       and r["t_max"] == tm]
                if not sel:
                    continue
                line = f"  {tau:6.1f} {mode:7s}"
                miss = []
                for n, _ in FRONTS:
                    r = next((x for x in sel if x["front"] == n), None)
                    if r and r["dir_err_mean"] is not None:
                        flag = "*" if r["dir_err_mean"] > 5.0 else " "
                        line += f"{r['dir_err_mean']:14.3f}±{r['dir_err_std']:<6.2f}{flag}"
                        miss.append(f"{r['n_missed_mean']:.1f}")
                    else:
                        line += f"{'추정불가':>22s}"
                        miss.append("-")
                print(line + f"{'/'.join(miss):>24s}")
        print("  (* = 실용선 5° 초과)")


if __name__ == "__main__":
    main()
