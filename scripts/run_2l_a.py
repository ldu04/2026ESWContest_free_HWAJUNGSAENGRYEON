"""run_2l_a.py — 2.L §2 · **속도·ETA·방향 절대값 표** (배율이 만든 착시 제거).

문제: 2.K §4([D-051])는 지터 취약성을 **배율**로 보고했다(속도 1.2~23배 vs 방향 196배).
**기준선이 다르면 배율은 오해를 부른다.** 방향의 균일 기준선은 0.345°(≈0.006 rad)로 극히 작고
각오차는 90°에서 포화하므로, 같은 절대 교란이라도 방향 쪽 배율만 커 보인다.

명세(`명세_FailurePattern_수학적정식화.md` §6)에 따르면 방향 각오차 δφ와 속도 상대오차 δs/s는
**둘 다 1/|∇T|에 비례**해 등방성 노이즈 아래서 절대 민감도가 비슷해야 한다. 그 예측을 표로 검증한다.

★ 강령 준수
  · `sim/estimator.py` **불변**. 밴드는 `run_2e3_stepE`의 `speed_band`/`nearest_local`을 **원본 임포트**.
  · 조건은 2.K §4와 **동일**(τ 10점 × 균일/지터σ0.3 × 전선 3종 × 시드 30 × t_max 이중).
  · 세 지표를 **같은 런에서** 뽑는다 → 방향·속도·ETA가 같은 시드·같은 궤적에서 나온 값임이 보장된다.
  · **교차검증:** 산출된 방향·속도를 기존 원자료(`raw_2j_a_dir_vs_tau.csv`, `raw_2k_d_speed.csv`)와
    셀 단위로 대조해 **재현 여부를 표로 낸다**(강령 §A-1 '수치는 전사하지 말고 원자료에서 재확인').
  · 배율을 낼 때는 **분자·분모를 함께** 적는다(강령 §A-3).
  · 결론 문장 없음. 표와 플래그만.

★ ETA 정의는 2.K §4와 동일하게 유지한다(정의를 바꾸면 비교가 성립하지 않는다):
    국소 평면의 방향 û와 밴드 중앙 속도 med로  eta_point = (t_i − t_now) + (û·(p − p_i)) / med
  `run_2e3_stepE.run_one`의 샘플링 루프를 그대로 옮겼고, 밴드 함수 자체는 원본을 임포트해 쓴다.
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
from scripts.run_2e3_stepE import speed_band, nearest_local, OUTDIR   # ★ 밴드 원본
from scripts._par import pmap, n_workers

TAUS_UNIFORM = (0.0, 2.0, 5.0, 10.0, 11.0, 20.0, 30.0, 50.0, 78.5, 100.0)
TAUS_JITTER = (11.0, 30.0, 78.5)
JITTER_SIGMA = 0.3
T_MAXES = (120.0, 400.0)
FRONTS = [
    ("straight_S1",  {}),
    ("curved_S2a10", {"wind_noise_deg": 10.0}),
    ("curved_S2a20", {"wind_noise_deg": 20.0}),
]
V_TRUE = 1.5            # 명목 전선 속도(m/s) — 속도오차의 분모이자 절대값 환산 기준


def job(a):
    """한 런에서 **방향·속도·ETA를 동시에** 뽑는다(같은 시드·같은 궤적 보장)."""
    front_ov, tau, t_max, jitter, seed = a
    cfg = Config(mode="ours", seed=seed, sensor_tau_s=tau, sensor_tau_var_pct=jitter,
                 sensor_tau_var_dist=("gauss" if jitter > 0 else "uniform"),
                 t_max=t_max, **front_ov)
    eng = Engine(cfg)
    tf = None
    eta_err = {d: [] for d in ETA_DISTS}         # eta_point − eta_true (초, 부호 포함)
    for snap in eng.stream():
        t = snap["t"]
        if tf is None:
            tf = TrueFront(eng.fire)
        if not eng.estimator.per_node or abs(t - round(t)) > 1e-9:
            continue
        band = speed_band(eng.estimator)
        if band is None:
            continue
        _v_lo, _v_hi, med = band
        front = np.array(eng.fire.front_pos(t), dtype=float)
        nvec = np.array(eng.fire._dir_at(t), dtype=float)
        for d in ETA_DISTS:
            p = front + nvec * d
            ta = tf.arrival(p)
            loc = nearest_local(eng.estimator, p)
            if ta is None or loc is None:
                continue
            u = np.array(loc["dir"], dtype=float)
            s_axis = float(u @ (p - np.array(loc["pos"], dtype=float)))
            if s_axis <= 0:
                continue
            eta_point = (loc["t"] - t) + s_axis / med
            eta_err[d].append(eta_point - (ta - t))

    dir_err = (angle_deg(eng.estimator.dir_global, cfg.direction())
               if eng.estimator.dir_global else None)
    sp = eng.estimator.speed_global
    out = {"dir_err_deg": dir_err,
           "speed_est_ms": sp,
           "speed_err_pct": ((sp - V_TRUE) / V_TRUE * 100.0) if sp else None,
           "speed_err_ms": (sp - V_TRUE) if sp else None,
           "n_pernode": len(eng.estimator.per_node)}
    for d in ETA_DISTS:
        out[f"eta_err_{int(d)}_s"] = (float(np.mean(eta_err[d])) if eta_err[d] else None)
    return out


def ms(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return None, None, 0
    return float(np.mean(v)), float(np.std(v)), len(v)


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


def crosscheck(rows, outdir):
    """★ 강령 §A-1 — 산출값을 **기존 원자료**와 셀 단위로 대조한다(전사 금지).

    raw_2j_a_dir_vs_tau.csv (2.J-A 방향, 시드별) · raw_2k_d_speed.csv (2.K-D 속도, 시드별).
    두 스윕 모두 같은 Config로 같은 시드를 돌렸으므로 **결정론상 동일해야 한다.**
    다르면 그 사실을 그대로 표에 낸다.
    """
    print("\n" + "=" * 112)
    print("★ 교차검증 — 이번 산출값 vs 기존 원자료 (같은 Config·같은 시드 → 결정론상 동일해야 함)")
    print("=" * 112)
    out = []

    def load(path, keyf, valf):
        p = os.path.join(outdir, path)
        if not os.path.exists(p):
            print(f"  [!] {path} 없음 — 대조 불가(.gitignore로 raw 제외 시 정상)")
            return None
        acc = {}
        for r in csv.DictReader(open(p, encoding="utf-8")):
            try:
                acc.setdefault(keyf(r), []).append(float(valf(r)))
            except (TypeError, ValueError):
                continue
        return {k: float(np.mean(v)) for k, v in acc.items()}

    ref_dir = load("raw_2j_a_dir_vs_tau.csv",
                   lambda r: (float(r["t_max"]), r["front"], r["mode"], float(r["tau_s"])),
                   lambda r: r["dir_err"])
    ref_sp = load("raw_2k_d_speed.csv",
                  lambda r: (float(r["t_max"]), r["front"], r["mode"], float(r["tau_s"])),
                  lambda r: r["speed_err_nominal_pct"])

    for tag, ref, mine_key in (("방향(°) vs 2.J-A", ref_dir, "dir_err_deg_exact"),
                               ("속도(%) vs 2.K-D", ref_sp, "speed_err_pct_exact")):
        if ref is None:
            continue
        diffs, n_ok, n_cmp = [], 0, 0
        for r in rows:
            k = (r["t_max"], r["front"], r["mode"], r["tau_s"])
            if k not in ref or r[mine_key] is None:
                continue
            n_cmp += 1
            d = abs(ref[k] - r[mine_key])
            diffs.append(d)
            if d < 1e-6:
                n_ok += 1
            out.append({"metric": tag, "t_max": r["t_max"], "front": r["front"],
                        "mode": r["mode"], "tau_s": r["tau_s"],
                        "ref": round(ref[k], 6), "mine": round(r[mine_key], 6),
                        "abs_diff": round(d, 9)})
        if n_cmp:
            print(f"  {tag:22s} 대조 {n_cmp}셀 · 완전일치 {n_ok}셀 · "
                  f"최대차 {max(diffs):.2e} → {'IDENTICAL' if max(diffs) < 1e-6 else '★불일치'}")
    write_csv(os.path.join(outdir, "summary_2l_a_crosscheck.csv"), out)


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
    cols = {"straight_S1": "#7f8c8d", "curved_S2a10": "#2980b9", "curved_S2a20": "#c0392b"}

    fig, axes = plt.subplots(1, 3, figsize=(16.5, 4.9))
    specs = [("dir_err_deg_mean", "방향오차 (°)", "(a) 방향"),
             ("speed_err_pct_mean", "속도오차 (%, 부호 포함)", "(b) 속도 — 같은 축 스케일 아님에 주의"),
             ("eta_err_100_s_mean", "ETA 오차 @100 m (s)", "(c) ETA")]
    for ax, (key, ylab, ttl) in zip(axes, specs):
        for name, _ in FRONTS:
            for mode, ls, mk in (("uniform", "-", "o"), ("jitter", "--", "s")):
                s = sorted([r for r in rows if r["front"] == name and r["mode"] == mode
                            and r["t_max"] == 400.0 and r[key] is not None],
                           key=lambda r: r["tau_s"])
                if s:
                    ax.plot([r["tau_s"] for r in s], [r[key] for r in s], ls, marker=mk,
                            lw=1.8, color=cols[name],
                            label=f"{name} {'균일' if mode == 'uniform' else '지터'}")
        ax.axhline(0, color="k", lw=0.8)
        for t in (11.0, 78.5):
            ax.axvline(t, color="#27ae60", ls="-.", lw=1.0, alpha=0.6)
        ax.set_xlabel("센서 τ (s)"); ax.set_ylabel(ylab)
        ax.set_title(ttl, fontsize=11); ax.grid(alpha=0.3); ax.legend(fontsize=6.5)
    fig.suptitle("2.L-A  방향·속도·ETA **절대값** 나란히 (t_max=400 s, 시드 30) — 배율 아님",
                 fontsize=12)
    fig.tight_layout()
    p = os.path.join(outdir, "curve_2l_a_absolute.png")
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

    print("=" * 112)
    print("2.L §2 · 방향·속도·ETA 절대값 표 (2.K §4와 동일 조건, 세 지표를 같은 런에서)")
    print("=" * 112)
    print(f"  τ 균일 {TAUS_UNIFORM}\n  τ 지터 {TAUS_JITTER} (σ={JITTER_SIGMA})")
    print(f"  전선 {[n for n, _ in FRONTS]} · t_max {T_MAXES} · 시드 {args.seeds} · 워커 {W}")
    print(f"  속도 절대값 기준 v_true = {V_TRUE} m/s · ETA 정의는 2.K §4와 동일(밴드 원본 임포트)\n")

    combos = []
    for tm in T_MAXES:
        for name, ov in FRONTS:
            for tau in TAUS_UNIFORM:
                combos.append((tm, name, ov, "uniform", tau, 0.0))
            for tau in TAUS_JITTER:
                combos.append((tm, name, ov, "jitter", tau, JITTER_SIGMA))
    jobs = [(ov, tau, tm, jit, sd) for (tm, _n, ov, _m, tau, jit) in combos for sd in seeds]
    print(f"  스윕 {len(jobs)} 런", flush=True)
    res = pmap(job, jobs, workers=W, label="2l-a")

    raw, rows = [], []
    idx = 0
    for (tm, name, ov, mode, tau, jit) in combos:
        rs = res[idx:idx + len(seeds)]
        idx += len(seeds)
        for i, r in enumerate(rs):
            raw.append({"t_max": tm, "front": name, "mode": mode, "tau_s": tau,
                        "seed": seeds[i], **r})
        rec = {"t_max": tm, "front": name, "mode": mode, "tau_s": tau, "n_seeds": len(seeds)}
        for key in ("dir_err_deg", "speed_err_pct", "speed_err_ms", "speed_est_ms",
                    "eta_err_30_s", "eta_err_60_s", "eta_err_100_s"):
            m, s, n = ms([r[key] for r in rs])
            # ★ 교차검증용 **무반올림** 값을 따로 남긴다. 표시는 반올림하되, 원자료 대조는
            #   반올림 전 값으로 해야 한다 — 4자리 반올림(±5e-5)이 '불일치'로 오판되기 때문.
            #   (초판이 실제로 그렇게 오판했다: 156셀 전부 ≤5e-5인데 '★불일치'로 찍혔다.)
            rec[f"{key}_exact"] = m
            rec[f"{key}_mean"] = round(m, 4) if m is not None else None
            rec[f"{key}_std"] = round(s, 4) if s is not None else None
            rec[f"{key}_n"] = n
        # |오차| 평균(부호 상쇄 없는 크기)
        for key in ("dir_err_deg", "speed_err_pct", "eta_err_100_s"):
            v = [abs(r[key]) for r in rs if r[key] is not None]
            rec[f"{key}_absmean"] = round(float(np.mean(v)), 4) if v else None
        rows.append(rec)
    write_csv(os.path.join(args.outdir, "raw_2l_a_absolute.csv"), raw)
    write_csv(os.path.join(args.outdir, "summary_2l_a_absolute.csv"), rows)
    crosscheck(rows, args.outdir)
    plot(rows, args.outdir)

    # ═══════════════ 절대값 표 ═══════════════
    for tm in T_MAXES:
        for name, _ in FRONTS:
            print("\n" + "=" * 112)
            print(f"★ 절대값 — {name}  [t_max={tm:.0f}s, 시드 {args.seeds}]  · 평균 ± 표준편차")
            print("=" * 112)
            print(f"  {'τ(s)':>6s} {'모드':8s} {'방향(°)':>18s} {'속도(%)':>19s} "
                  f"{'속도(m/s)':>19s} {'ETA@100m(s)':>20s}")
            for tau in TAUS_UNIFORM:
                for mode in ("uniform", "jitter"):
                    r = next((x for x in rows if x["tau_s"] == tau and x["mode"] == mode
                              and x["front"] == name and x["t_max"] == tm), None)
                    if not r or r["dir_err_deg_mean"] is None:
                        continue
                    f = lambda a, b, w, p: (f"{r[a]:{w}.{p}f}±{r[b]:<.{p}f}"
                                            if r[a] is not None else "-")
                    print(f"  {tau:6.1f} {mode:8s} "
                          f"{f('dir_err_deg_mean','dir_err_deg_std',9,3):>18s} "
                          f"{f('speed_err_pct_mean','speed_err_pct_std',9,2):>19s} "
                          f"{f('speed_err_ms_mean','speed_err_ms_std',9,4):>19s} "
                          f"{f('eta_err_100_s_mean','eta_err_100_s_std',9,2):>20s}")

    # ═══════════════ 지터 열화: 분자·분모 함께 (강령 §A-3) ═══════════════
    print("\n" + "=" * 112)
    print("★ 지터 열화 — **배율에는 분자·분모를 반드시 함께 적는다** (강령 §A-3)")
    print("   |오차| 평균 기준, t_max=400 s")
    print("=" * 112)
    print(f"  {'전선':15s} {'τ':>6s} {'지표':13s} {'균일(분모)':>13s} {'지터(분자)':>13s} "
          f"{'배율':>8s} {'절대 증가분':>13s}")
    for name, _ in FRONTS:
        for tau in TAUS_JITTER:
            for key, lab, unit in (("dir_err_deg_absmean", "방향", "°"),
                                   ("speed_err_pct_absmean", "속도", "%"),
                                   ("eta_err_100_s_absmean", "ETA@100m", "s")):
                u = next((x for x in rows if x["tau_s"] == tau and x["mode"] == "uniform"
                          and x["front"] == name and x["t_max"] == 400.0), None)
                j = next((x for x in rows if x["tau_s"] == tau and x["mode"] == "jitter"
                          and x["front"] == name and x["t_max"] == 400.0), None)
                if not u or not j or u[key] is None or j[key] is None:
                    continue
                a, b = u[key], j[key]
                print(f"  {name:15s} {tau:6.1f} {lab:13s} {a:11.3f}{unit:>2s} "
                      f"{b:11.3f}{unit:>2s} "
                      f"{(b/a if a > 1e-9 else float('inf')):8.2f} {b-a:+11.3f}{unit:>2s}")

    # ═══════════════ 실용선 이탈 (E3x2 기준, 변경 금지) ═══════════════
    print("\n" + "=" * 112)
    print("★ 실용선 대조 — 방향 5° / 속도 밴드폭 대비 / ETA는 E3x2 위험측(=[D-051] 표 참조)")
    print("   ※ E3x2 위험측 자체는 [D-051]에서 이미 산출됐다. 여기서는 **절대 오차**가")
    print("      실용선을 넘는 지점만 표시한다(밴드 규칙은 손대지 않는다).")
    print("=" * 112)
    print(f"  {'전선':15s} {'모드':8s} {'첫 방향>5° τ':>14s} {'첫 |속도|>20 % τ':>18s} "
          f"{'첫 |ETA@100|>30 s τ':>21s}")
    for name, _ in FRONTS:
        for mode in ("uniform", "jitter"):
            taus = TAUS_UNIFORM if mode == "uniform" else TAUS_JITTER
            firsts = []
            for key, lim in (("dir_err_deg_absmean", 5.0),
                             ("speed_err_pct_absmean", 20.0),
                             ("eta_err_100_s_absmean", 30.0)):
                hit = None
                for tau in taus:
                    r = next((x for x in rows if x["tau_s"] == tau and x["mode"] == mode
                              and x["front"] == name and x["t_max"] == 400.0), None)
                    if r and r[key] is not None and r[key] > lim:
                        hit = tau
                        break
                firsts.append(f"{hit:.1f}" if hit is not None else "없음")
            print(f"  {name:15s} {mode:8s} {firsts[0]:>14s} {firsts[1]:>18s} {firsts[2]:>21s}")
    print("\n  (속도 20 %·ETA 30 s는 **표시용 눈금**이지 승인된 실용선이 아니다 —")
    print("   승인된 ETA 실용선은 E3x2 위험측 ≤10 %이며 [D-051]에 이미 산출돼 있다.)")


if __name__ == "__main__":
    main()
