"""run_2k_d.py — 2.K §4 · **속도·ETA의 지터 τ 취약성** (미확인 가정 해소).

배경: 2.J-A는 **방향**에 대해서만 지터 τ의 영향을 쟀다(τ=78.5 s 지터에서 66.7°, 균일 대비 ~190배).
속도(1/|∇T|)와 ETA는 **아직 안 돌려봤다**. 같은 메커니즘이 망가뜨릴 개연성이 높지만
**이는 확인되지 않은 가정이지 측정된 사실이 아니다.** 그걸 잰다.

★ ETA는 방향·속도와 구조가 다르다 (이 스크립트의 두 번째 목적)
  균일 지연은 도착시각장의 **기울기에서 상쇄**되어 방향·속도를 보존하지만,
  ETA는 "지금이 몇 시인가"라는 **절대 시각 기준**을 요구하므로 균일 지연이 **그대로 남는다.**
  warm_scale에 대해 −6.4 s 보정을 넣었던 것과 같은 종류의 처치가 τ에도 필요하며,
  **새 τ값(11 s·78.5 s)에 대한 보정치는 아직 산출된 적이 없다.** 그것을 산출한다.

★ 강령 준수
  · `sim/estimator.py` **불변**. 밴드 기계는 `run_2e3_stepE`/`stepF`/`stepG`의 것을 **그대로 임포트**해
    쓴다(재정의 금지 → "실용선 임의 변경 금지"를 코드 수준에서 보장).
  · 고정 편향항 `derive_bias_at_W0`(S1·W0·τ=0)는 **재적합 금지** — 그대로 쓴다.
  · 새로 산출하는 **τ 보정치도 S1에서만 도출**하고 곡선 전선(S2a)에서 **평가**한다(도출/평가 분리).
  · 조건은 2.J-A와 **동일**: τ 스윕, 균일/지터 σ=30 %, 곡선+직선, 시드 30, t_max 이중.
  · 결론 문장 없음. 원자료·그래프·예측 어긋난 지점 플래그만.

★ 사전등록 예측 (Cowork, 본인 표기 신뢰도 낮음 — 이 부류에서 이미 4번 빗나감)
  D1: 속도는 역수(1/|∇T|) 때문에 방향보다 지터에 **더** 취약하다.
  D2: 균일 τ의 ETA 편향은 τ에 대략 **비례**하는 지연 방향(늦게 예측)이다.
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
from scripts.run_2e3_stepE import run_one, OUTDIR          # ★ 밴드 기계 원본
from scripts.run_2e3_stepF import derive_bias_at_W0, EXPAND_R_HI
from scripts._par import pmap, n_workers

# ── 2.J-A와 동일한 조건 ──
TAUS_UNIFORM = (0.0, 2.0, 5.0, 10.0, 11.0, 20.0, 30.0, 50.0, 78.5, 100.0)
TAUS_JITTER = (11.0, 30.0, 78.5)
JITTER_SIGMA = 0.3
T_MAXES = (120.0, 400.0)
FRONTS = [
    ("straight_S1",  {}),
    ("curved_S2a10", {"wind_noise_deg": 10.0}),
    ("curved_S2a20", {"wind_noise_deg": 20.0}),
]
BREACH_LIMIT = 10.0     # E3x2 위험측 실용선 (D-041/D-042 기준, 변경 금지)


def ov_for(front_ov, tau, t_max, jitter=0.0):
    d = dict(front_ov)
    d.update({"sensor_tau_s": tau, "sensor_tau_var_pct": jitter,
              "sensor_tau_var_dist": ("gauss" if jitter > 0 else "uniform"),
              "t_max": t_max})
    return d


def job(a):
    """(front_ov, tau, t_max, jitter, seed) → (eta_rows, speed_summary)"""
    front_ov, tau, t_max, jitter, seed = a
    rows, speed_rows = run_one(seed, ov_for(front_ov, tau, t_max, jitter), floor_pct=0.0)
    sp = None
    if speed_rows:
        s = speed_rows[-1]
        sp = {"med": s["med"], "v_true_bar": s["v_true_bar"],
              # 2.J-A 정의(명목 대비, 부호 포함)
              "speed_err_nominal_pct": (s["med"] - 1.5) / 1.5 * 100.0,
              # 실현된 평균 전선속도 대비(부호 포함)
              "speed_err_realized_pct": (s["med"] - s["v_true_bar"]) / s["v_true_bar"] * 100.0}
    return rows, sp


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
    print(f"  [csv] {path} ({len(rows)} rows)", flush=True)


def band_stats(sub, bias, tau_corr=None):
    """E3x2 밴드 통계. tau_corr 가 주어지면 **추가 τ 보정**을 얹는다.

    E3x2 (D-042 정본): 이른끝 shift = 0, 늦은끝 shift = −q05·EXPAND_R_HI.
    τ 보정은 밴드 **양끝과 점추정을 동일량만큼** 이동시킨다(폭 불변, 위치만 교정).
    """
    q05, q95 = bias
    tr = np.array([x["eta_true"] for x in sub])
    pt = np.array([x["eta_point"] for x in sub])
    lo = np.array([x["e2_early"] for x in sub]) + 0.0
    hi = np.array([x["e2_late"] for x in sub]) + (-q05 * EXPAND_R_HI)
    c = 0.0 if tau_corr is None else tau_corr
    lo, hi, pt = lo - c, hi - c, pt - c
    return {"cov_pct": round(float(((tr >= lo) & (tr <= hi)).mean()) * 100, 1),
            "breach_early_pct": round(float((tr < lo).mean()) * 100, 1),
            "breach_late_pct": round(float((tr > hi).mean()) * 100, 1),
            "width_s": round(float((hi - lo).mean()), 1),
            "point_bias_s": round(float((pt - tr).mean()), 2),
            "point_mae_s": round(float(np.abs(pt - tr).mean()), 2)}


def plot(rows, corr, outdir):
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
    cols = {"straight_S1": "#7f8c8d", "curved_S2a10": "#2980b9", "curved_S2a20": "#c0392b"}

    for tm in T_MAXES:
        fig, axes = plt.subplots(1, 3, figsize=(16.5, 4.9))
        # (a) 속도오차
        ax = axes[0]
        for name, _ in FRONTS:
            u = sorted([r for r in rows if r["front"] == name and r["mode"] == "uniform"
                        and r["t_max"] == tm and r["speed_err_nominal_mean"] is not None],
                       key=lambda r: r["tau_s"])
            if u:
                ax.errorbar([r["tau_s"] for r in u], [r["speed_err_nominal_mean"] for r in u],
                            yerr=[r["speed_err_nominal_std"] or 0 for r in u],
                            marker="o", lw=2, capsize=3, color=cols[name], label=f"{name} 균일")
            j = sorted([r for r in rows if r["front"] == name and r["mode"] == "jitter"
                        and r["t_max"] == tm and r["speed_err_nominal_mean"] is not None],
                       key=lambda r: r["tau_s"])
            if j:
                ax.plot([r["tau_s"] for r in j], [r["speed_err_nominal_mean"] for r in j],
                        marker="s", ls="--", lw=1.8, color=cols[name], label=f"{name} 지터σ0.3")
        ax.axhline(0, color="k", lw=0.8)
        for t in (11.0, 78.5):
            ax.axvline(t, color="#27ae60", ls="-.", lw=1.1, alpha=0.7)
        ax.set_xlabel("센서 τ (s)"); ax.set_ylabel("속도오차 (%, 부호 포함)")
        ax.set_title(f"(a) τ → 속도오차  [t_max={tm:.0f}s]", fontsize=11)
        ax.grid(alpha=0.3); ax.legend(fontsize=7)

        # (b) ETA 점추정 편향(100 m)
        ax = axes[1]
        for name, _ in FRONTS:
            for mode, ls, mk in (("uniform", "-", "o"), ("jitter", "--", "s")):
                s = sorted([r for r in rows if r["front"] == name and r["mode"] == mode
                            and r["t_max"] == tm and r["eta_bias_100_s"] is not None],
                           key=lambda r: r["tau_s"])
                if s:
                    ax.plot([r["tau_s"] for r in s], [r["eta_bias_100_s"] for r in s],
                            ls, marker=mk, lw=1.8, color=cols[name],
                            label=f"{name} {'균일' if mode=='uniform' else '지터'}")
        ax.axhline(0, color="k", lw=0.8)
        ax.set_xlabel("센서 τ (s)"); ax.set_ylabel("ETA 편향 (s)  + = 늦게 예측")
        ax.set_title(f"(b) τ → ETA 편향 @100 m  [t_max={tm:.0f}s]", fontsize=11)
        ax.grid(alpha=0.3); ax.legend(fontsize=7)

        # (c) E3x2 위험측
        ax = axes[2]
        for name, _ in FRONTS:
            for tag, ls, mk in (("E3x2_breach_early_100", "-", "o"),
                                ("E3x2c_breach_early_100", "--", "^")):
                s = sorted([r for r in rows if r["front"] == name and r["mode"] == "uniform"
                            and r["t_max"] == tm and r[tag] is not None],
                           key=lambda r: r["tau_s"])
                if s:
                    ax.plot([r["tau_s"] for r in s], [r[tag] for r in s], ls, marker=mk,
                            lw=1.8, color=cols[name],
                            label=f"{name} {'무보정' if 'c_' not in tag else 'τ보정'}")
        ax.axhline(BREACH_LIMIT, color="k", ls=":", lw=1.5)
        ax.text(2, BREACH_LIMIT + 1, "실용선 10 %", fontsize=9)
        ax.set_xlabel("센서 τ (s)"); ax.set_ylabel("E3x2 위험측 breach_early (%)")
        ax.set_title(f"(c) τ → 위험측 @100 m  [t_max={tm:.0f}s]", fontsize=11)
        ax.grid(alpha=0.3); ax.legend(fontsize=7)

        fig.suptitle(f"2.K-D  속도·ETA의 τ 취약성 (t_max={tm:.0f}s, 시드 30)", fontsize=12)
        fig.tight_layout()
        p = os.path.join(outdir, f"curve_2k_d_speed_eta_tmax{int(tm)}.png")
        fig.savefig(p, dpi=120)
        plt.close(fig)
        print(f"  [png] {p}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))
    W = args.workers or n_workers()

    print("=" * 108)
    print("2.K §4 · 속도·ETA의 지터 τ 취약성 (조건은 2.J-A와 동일, 방향 대신 속도·ETA)")
    print("=" * 108)
    print(f"  균일 τ {TAUS_UNIFORM}\n  지터 τ {TAUS_JITTER} (σ={JITTER_SIGMA}, gauss, 0.5s 클립)")
    print(f"  전선 {[n for n,_ in FRONTS]} · t_max {T_MAXES} · 시드 {args.seeds} · 워커 {W}")
    print(f"  밴드 = E3x2 (stepE/F/G 원본 임포트, 재정의 없음) · 위험측 실용선 {BREACH_LIMIT:.0f} %\n")

    # ── 고정 편향항: S1·W0·τ=0 도출값. 재적합 금지 ──
    bias = derive_bias_at_W0(seeds)
    print("  고정 편향항(S1·W0·τ=0, 재적합 금지):")
    for d in ETA_DISTS:
        print(f"    {d:5.0f} m: q05={bias[d][0]:+7.2f}s  q95={bias[d][1]:+7.2f}s")
    print()

    # ── 전체 스윕 ──
    combos = []
    for tm in T_MAXES:
        for name, ov in FRONTS:
            for tau in TAUS_UNIFORM:
                combos.append((tm, name, ov, "uniform", tau, 0.0))
            for tau in TAUS_JITTER:
                combos.append((tm, name, ov, "jitter", tau, JITTER_SIGMA))
    jobs = [(ov, tau, tm, jit, sd) for (tm, _n, ov, _m, tau, jit) in combos for sd in seeds]
    print(f"  스윕 {len(jobs)} 런", flush=True)
    res = pmap(job, jobs, workers=W, label="2k-d")

    # ── ★ τ 보정치 도출: S1(직선)·균일 τ 에서만. 곡선에서 평가 ──
    corr = {}
    idx = 0
    packed = {}
    for (tm, name, ov, mode, tau, jit) in combos:
        packed[(tm, name, mode, tau)] = res[idx:idx + len(seeds)]
        idx += len(seeds)
    for (tm, name, mode, tau), rs in packed.items():
        if name != "straight_S1" or mode != "uniform":
            continue
        allr = [x for r, _s in rs for x in r]
        for d in ETA_DISTS:
            sub = [x for x in allr if x["dist"] == d]
            corr[(tm, tau, d)] = (round(float(np.mean([x["eta_point"] - x["eta_true"]
                                                       for x in sub])), 3) if sub else None)

    print("\n" + "=" * 108)
    print("★ 도출 — 균일 τ의 ETA 편향(부호 포함) = **필요한 보정치**   [S1 직선에서만 도출]")
    print("   + = 예측이 참보다 늦다(늦게 온다고 말함) / − = 이르다")
    print("=" * 108)
    for tm in T_MAXES:
        print(f"\n  [t_max={tm:.0f}s]")
        print(f"  {'τ(s)':>7s} " + "".join(f"{'ETA편향 @'+str(int(d))+'m':>18s}" for d in ETA_DISTS)
              + f"{'편향/τ @100m':>14s}")
        for tau in TAUS_UNIFORM:
            line = f"  {tau:7.1f} "
            for d in ETA_DISTS:
                v = corr.get((tm, tau, d))
                line += f"{v:+18.2f}" if v is not None else f"{'추정불가':>18s}"
            v100 = corr.get((tm, tau, 100.0))
            line += (f"{v100/tau:14.3f}" if (v100 is not None and tau > 0) else f"{'-':>14s}")
            print(line)

    # ── 집계 ──
    rows, raw = [], []
    for (tm, name, ov, mode, tau, jit) in combos:
        rs = packed[(tm, name, mode, tau)]
        allr = [x for r, _s in rs for x in r]
        sps = [s for _r, s in rs if s is not None]
        rec = {"t_max": tm, "front": name, "mode": mode, "tau_s": tau,
               "n_seeds_valid_speed": len(sps), "n_eta_samples": len(allr)}
        for k, kk in (("speed_err_nominal_pct", "speed_err_nominal"),
                      ("speed_err_realized_pct", "speed_err_realized")):
            v = [s[k] for s in sps]
            rec[f"{kk}_mean"] = round(float(np.mean(v)), 3) if v else None
            rec[f"{kk}_std"] = round(float(np.std(v)), 3) if v else None
            rec[f"{kk}_absmean"] = round(float(np.mean(np.abs(v))), 3) if v else None
        for d in ETA_DISTS:
            sub = [x for x in allr if x["dist"] == d]
            tag = int(d)
            if not sub:
                rec[f"eta_bias_{tag}_s"] = rec[f"eta_mae_{tag}_s"] = None
                rec[f"E3x2_cov_{tag}"] = rec[f"E3x2_breach_early_{tag}"] = None
                rec[f"E3x2c_cov_{tag}"] = rec[f"E3x2c_breach_early_{tag}"] = None
                rec[f"E3x2_width_{tag}"] = rec[f"E3x2c_width_{tag}"] = None
                continue
            e = np.array([x["eta_point"] - x["eta_true"] for x in sub])
            rec[f"eta_bias_{tag}_s"] = round(float(e.mean()), 3)
            rec[f"eta_mae_{tag}_s"] = round(float(np.abs(e).mean()), 3)
            b0 = band_stats(sub, bias[d], tau_corr=None)
            bc = band_stats(sub, bias[d], tau_corr=corr.get((tm, tau, d)))
            rec[f"E3x2_cov_{tag}"] = b0["cov_pct"]
            rec[f"E3x2_breach_early_{tag}"] = b0["breach_early_pct"]
            rec[f"E3x2_width_{tag}"] = b0["width_s"]
            rec[f"E3x2_point_mae_{tag}"] = b0["point_mae_s"]
            rec[f"E3x2c_cov_{tag}"] = bc["cov_pct"]
            rec[f"E3x2c_breach_early_{tag}"] = bc["breach_early_pct"]
            rec[f"E3x2c_width_{tag}"] = bc["width_s"]
            rec[f"E3x2c_point_mae_{tag}"] = bc["point_mae_s"]
        rows.append(rec)
        for i, (_r, s) in enumerate(rs):
            if s:
                raw.append({"t_max": tm, "front": name, "mode": mode, "tau_s": tau,
                            "seed": seeds[i], **s})
    write_csv(os.path.join(args.outdir, "summary_2k_d_speed_eta_vs_tau.csv"), rows)
    write_csv(os.path.join(args.outdir, "raw_2k_d_speed.csv"), raw)
    write_csv(os.path.join(args.outdir, "summary_2k_d_eta_tau_correction.csv"),
              [{"t_max": tm, "tau_s": tau, "dist_m": d, "eta_bias_s": corr.get((tm, tau, d))}
               for tm in T_MAXES for tau in TAUS_UNIFORM for d in ETA_DISTS])
    plot(rows, corr, args.outdir)

    # ════════════ 표 1 · 속도오차 ════════════
    for tm in T_MAXES:
        print("\n" + "=" * 108)
        print(f"속도오차 (%, 부호 포함, 명목 1.5 m/s 대비)   [t_max={tm:.0f}s]   · 2.J-A 방향과 나란히 볼 것")
        print("=" * 108)
        print(f"  {'τ(s)':>7s} {'모드':8s}" + "".join(f"{n:>26s}" for n, _ in FRONTS))
        for tau in TAUS_UNIFORM:
            for mode in ("uniform", "jitter"):
                sel = [r for r in rows if r["tau_s"] == tau and r["mode"] == mode
                       and r["t_max"] == tm]
                if not sel:
                    continue
                line = f"  {tau:7.1f} {mode:8s}"
                for n, _ in FRONTS:
                    r = next((x for x in sel if x["front"] == n), None)
                    if r and r["speed_err_nominal_mean"] is not None:
                        line += (f"{r['speed_err_nominal_mean']:+16.2f}"
                                 f"±{r['speed_err_nominal_std']:<7.2f}"
                                 f"({r['n_seeds_valid_speed']:2d})")
                    else:
                        line += f"{'추정불가':>26s}"
                print(line)

    # ════════════ 표 2 · ETA 편향 균일 vs 지터 ════════════
    for tm in T_MAXES:
        print("\n" + "=" * 108)
        print(f"ETA 점추정 편향(s) @100 m · 균일 vs 지터   [t_max={tm:.0f}s]   + = 늦게 예측")
        print("=" * 108)
        print(f"  {'τ(s)':>7s} " + "".join(f"{n+' 균일':>20s}{n+' 지터':>20s}" for n, _ in FRONTS))
        for tau in TAUS_UNIFORM:
            line = f"  {tau:7.1f} "
            for n, _ in FRONTS:
                for mode in ("uniform", "jitter"):
                    r = next((x for x in rows if x["tau_s"] == tau and x["mode"] == mode
                              and x["front"] == n and x["t_max"] == tm), None)
                    v = r["eta_bias_100_s"] if r else None
                    line += f"{v:+20.2f}" if v is not None else f"{'-':>20s}"
            print(line)

    # ════════════ 표 3 · 보정 전/후 밴드 ════════════
    for tm in T_MAXES:
        print("\n" + "=" * 108)
        print(f"★ τ 보정 전/후 · E3x2 밴드 @100 m   [t_max={tm:.0f}s]   ·  위험측 실용선 {BREACH_LIMIT:.0f} %")
        print("   보정치는 **S1 직선에서만 도출**, 아래 곡선 전선은 평가 세계(재적합 없음)")
        print("=" * 108)
        for n, _ in FRONTS:
            print(f"\n  ── {n} ──")
            print(f"  {'τ(s)':>7s} {'모드':8s} {'MAE무보정':>10s} {'MAE보정':>9s} "
                  f"{'커버무보정':>11s} {'커버보정':>10s} {'★위험무보정':>12s} {'★위험보정':>11s} {'폭(s)':>8s}")
            for tau in TAUS_UNIFORM:
                for mode in ("uniform", "jitter"):
                    r = next((x for x in rows if x["tau_s"] == tau and x["mode"] == mode
                              and x["front"] == n and x["t_max"] == tm), None)
                    if not r or r["eta_bias_100_s"] is None:
                        continue
                    f0, fc = r["E3x2_breach_early_100"], r["E3x2c_breach_early_100"]
                    print(f"  {tau:7.1f} {mode:8s} {r['E3x2_point_mae_100']:10.2f} "
                          f"{r['E3x2c_point_mae_100']:9.2f} {r['E3x2_cov_100']:10.1f}% "
                          f"{r['E3x2c_cov_100']:9.1f}% "
                          f"{f0:10.1f}%{'*' if f0 > BREACH_LIMIT else ' '} "
                          f"{fc:9.1f}%{'*' if fc > BREACH_LIMIT else ' '} "
                          f"{r['E3x2_width_100']:8.1f}")
            print("  (* = 위험측 실용선 초과)")

    # ════════════ 표 4 · 실용선 이탈 지점 ════════════
    print("\n" + "=" * 108)
    print("★ 실용선 이탈 — 지터 τ에서 속도·ETA가 언제 무너지는가 (t_max=400s, 절단 배제)")
    print("=" * 108)
    print(f"  {'전선':16s} {'모드':8s} {'지표':26s} " +
          "".join(f"{'τ='+str(t):>10s}" for t in TAUS_JITTER))
    for n, _ in FRONTS:
        for mode in ("uniform", "jitter"):
            for key, lab in (("speed_err_nominal_absmean", "속도 |오차| (%)"),
                             ("eta_mae_100_s", "ETA MAE @100m (s)"),
                             ("E3x2_breach_early_100", "E3x2 위험측 (%)"),
                             ("E3x2c_breach_early_100", "E3x2+τ보정 위험측 (%)")):
                line = f"  {n:16s} {mode:8s} {lab:26s} "
                for tau in TAUS_JITTER:
                    r = next((x for x in rows if x["tau_s"] == tau and x["mode"] == mode
                              and x["front"] == n and x["t_max"] == 400.0), None)
                    v = r[key] if r else None
                    line += f"{v:10.2f}" if v is not None else f"{'-':>10s}"
                print(line)

    # ════════════ 예측 대조 ════════════
    print("\n" + "=" * 108)
    print("★ 사전등록 예측 대조 (해석 없이 일치/불일치만)")
    print("=" * 108)
    print("  D1: 속도가 방향보다 지터에 더 취약한가 — 균일 대비 지터 열화 배율로 비교")
    print(f"  {'전선':16s} {'τ':>7s} {'속도 균일':>12s} {'속도 지터':>12s} {'배율':>9s}"
          f"   (2.J-A 방향 배율: τ=78.5에서 ~190배)")
    for n, _ in FRONTS:
        for tau in TAUS_JITTER:
            u = next((x for x in rows if x["tau_s"] == tau and x["mode"] == "uniform"
                      and x["front"] == n and x["t_max"] == 400.0), None)
            j = next((x for x in rows if x["tau_s"] == tau and x["mode"] == "jitter"
                      and x["front"] == n and x["t_max"] == 400.0), None)
            if not u or not j or u["speed_err_nominal_absmean"] is None:
                continue
            a, b = u["speed_err_nominal_absmean"], j["speed_err_nominal_absmean"]
            print(f"  {n:16s} {tau:7.1f} {a:12.3f} {b:12.3f} "
                  f"{(b/a if a > 1e-9 else float('inf')):9.2f}")
    print()
    print("  D2: 균일 τ의 ETA 편향이 τ에 비례하는 지연 방향인가 (S1·t_max=400·100 m)")
    vals = [(tau, corr.get((400.0, tau, 100.0))) for tau in TAUS_UNIFORM]
    vals = [(t, v) for t, v in vals if v is not None]
    signs = {("+" if v > 0 else ("0" if abs(v) < 1e-9 else "−")) for _t, v in vals}
    mono = all(vals[i][1] <= vals[i + 1][1] + 1e-9 for i in range(len(vals) - 1))
    print(f"    부호 집합 {signs}  ·  τ에 대해 단조증가 {'일치' if mono else '★불일치'}")
    print(f"    값 {[(t, v) for t, v in vals]}")
    if len(vals) > 2:
        tt = np.array([t for t, _v in vals if t > 0])
        vv = np.array([v for t, v in vals if t > 0])
        if tt.size > 1:
            k = float(np.polyfit(tt, vv, 1)[0])
            r2 = float(np.corrcoef(tt, vv)[0, 1] ** 2)
            print(f"    선형 적합 편향 ≈ {k:+.4f}·τ  (R²={r2:.4f})  → 비례 예측 "
                  f"{'일치' if r2 > 0.9 else '★불일치'}")


if __name__ == "__main__":
    main()
