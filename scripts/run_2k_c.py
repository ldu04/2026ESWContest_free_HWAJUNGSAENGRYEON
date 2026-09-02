"""run_2k_c.py — 2.K §3 · **탐지 임계값 하향 스윕** (미탐지 ↔ 오탐 교환곡선).

배경: 2.J-B는 임계 80 ℃를 **고정**하고 τ·피크만 스윕했다. τ가 크다 = 센서가 목표를 못 따라간다
이므로, 목표선(임계)을 낮추면 굼뜬 센서도 펄스가 지나가기 전에 그 선을 밟을 수 있다.
τ=78.5 s를 구제할 **유일한 소프트웨어 카드**이므로, 그 대가(오탐)까지 같이 잰다.

★ 강령 준수
  · `sim/estimator.py` **불변**. 임계 외 파라미터(펄스형태 burn_scale=10, warm_scale, 전선,
    estimator, t_max=250)는 **전부 2.J-B 그대로**.
  · 미탐지만 보고 "임계 낮추면 좋다"고 결론내지 않는다 — **오탐을 같은 임계에서 반드시 측정**한다.
  · 결론 문장 없음. 원자료·그래프·예측 어긋난 지점 플래그만.

★ 피크 100 ℃ 제외 (지시서가 허용, 사실 명시)
  임계 40 ℃와 너무 가까워(f=0.20) 해석이 꼬이므로 뺐다. 피크 축 = {150,200,300,500} ℃.

═══════════════════════════════════════════════════════════════════════════════
★★ 착수 시 발견한 **구조적 결합** — 측정 전에 플래그 (지시서 예측에 없던 항목)
═══════════════════════════════════════════════════════════════════════════════
 F1. **임계를 낮추면 화재사망이 "비화재"로 분류돼 estimator에서 버려진다.**
     `verification.py`의 3분기 선별은 `temp_threshold`(80 ℃)가 아니라 **`warn_temp`(60 ℃)**로
     화재/비화재를 가른다(분기① `rep_peak >= warn_temp`). 임계만 40 ℃로 낮추면 45 ℃에서 죽은
     **진짜 화재사망**이 `rep_peak < 60` 이라 분기②로 빠져 **제외**된다.
     ⇒ 탐지는 늘지만 추정기가 그 죽음을 **못 본다**. "미탐지율↓"이 곧 "시스템 작동"이 아니다.
     그래서 두 팔을 **모두** 돌린다:
       · `warn_fixed`   : warn_temp=60 고정 — 지시서의 '임계 축만' 문자 그대로.
       · `warn_coupled` : warn_temp = 임계−20 (기본값의 80−60=20 ℃ 간격 보존) — 물리적으로 정합.
     어느 쪽도 숨기지 않는다.

 F2. **기존 모델에는 '불이 아닌 더운 것'이 없다.** 유일한 열원이 불이므로, 임계 하향의 **가장 중요한
     오탐 경로**(햇볕·기기발열이 낮아진 선을 밟는다)를 원리적으로 생성할 수 없다. 2.D의 비화재
     '사망'(강제 사망, **저온**)은 그것과 다른 것을 잰다. ⇒ 지시서가 지정한 2.D 오탐을 **주 측정**으로
     내되, 그것이 임계 하향 비용을 **과소평가**한다는 사실을 명시하고, 보조축으로 `benign_heat_c`
     (0이면 비트 동일)를 넣어 그 경로를 별도 측정한다. 보조축은 **주 표와 섞지 않는다.**

★ 사전등록 예측 (Cowork, 본인 표기 신뢰도 낮음 — 이 부류에서 이미 4번 빗나감)
  C1: 임계↓ → 미탐지 단조 감소, 오탐 단조 증가.
  C2: τ=78.5 s에서도 임계 45~50 ℃면 미탐지가 실용선(≤5 %) 안으로 들어온다.
  (이중 벌점 논리상 C2는 성립하지 않을 수 있다 — 그 경우 그대로 보고.)
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
from scripts.run_2e3_diagnose import TrueFront
from scripts._par import pmap, n_workers

OUTDIR = os.path.join("results", "stress")

THRESHOLDS = (40.0, 45.0, 50.0, 60.0, 70.0, 80.0)   # 80 = 대조군(2.J-B 조건)
TAUS = (11.0, 30.0, 50.0, 78.5, 100.0)              # 2.J-B 그대로
PEAKS = (150.0, 200.0, 300.0, 500.0)                # 100 제외(위 명시)
BURN = 10.0                                          # 2.J-B 그대로
T_MAX = 250.0                                        # 2.J-B 그대로
WARN_GAP = 20.0                                      # 기본값 80−60

SCENARIOS = [                                        # 2.J-B 그대로
    ("S1", {}),
    ("S2a_10", {"wind_noise_deg": 10.0}),
    ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                  "placement_jitter": 0.2, "p_dropout": 0.10}),
]

# 오탐 축
FP_TAUS = (11.0, 78.5)          # 실측 두 점
N_NONFIRE = 8                   # 2.D/S11 최고 주입 수준(기존 정의 그대로)
BENIGN_C = (0.0, 20.0, 30.0, 40.0)   # 보조축: 상온+Δ ℃ 인 비화재 열원(0=대조)
BENIGN_FRAC = 0.25


def warn_for(thr, arm):
    return 60.0 if arm == "warn_fixed" else max(1.0, thr - WARN_GAP)


# ───────────────────────── 주 측정 ①: 미탐지율 ─────────────────────────
def job_miss(a):
    arm, sname, ov, thr, tau, peak, seed = a
    cfg = Config(mode="ours", seed=seed, peak=peak, sensor_tau_s=tau,
                 temp_threshold=thr, warn_temp=warn_for(thr, arm),
                 burn_scale_m=BURN, t_max=T_MAX, **ov)
    eng = Engine(cfg)
    for _ in eng.stream():
        pass
    tf = TrueFront(eng.fire)

    exposed = miss = 0
    for nd in eng.nodes:
        if nd.is_sink or tf.arrival(nd.pos) is None:
            continue
        exposed += 1
        if nd.death_t is None:
            miss += 1
    # ★ F1: 죽었더라도 estimator가 채택했는가(= 추정에 실제로 쓰였는가)
    n_conf = len(eng.estimator.deaths)
    return {"exposed": exposed, "miss": miss,
            "miss_rate": (miss / exposed * 100.0) if exposed else 0.0,
            "n_confirmed": n_conf,
            "excluded_nonfire": len(eng.verifier.excluded_nonfire),
            # 추정 불능률 = 노출 노드 중 estimator에 안 들어간 비율(미탐지 + 게이트 탈락)
            "blind_rate": ((exposed - n_conf) / exposed * 100.0) if exposed else 0.0,
            "dir_ok": 1 if eng.estimator.dir_global is not None else 0}


# ───────────────────────── 주 측정 ②: 2.D 오탐(비화재 사망 오염) ─────────────────────────
def job_fp_nonfire(a):
    arm, sname, ov, thr, tau, seed = a
    cfg = Config(mode="ours", seed=seed, peak=300.0, sensor_tau_s=tau,
                 temp_threshold=thr, warn_temp=warn_for(thr, arm),
                 burn_scale_m=BURN, t_max=T_MAX,
                 n_nonfire_deaths=N_NONFIRE, **ov)
    eng = Engine(cfg)
    for _ in eng.stream():
        pass
    # 실제로 비화재로 죽은 노드(스케줄됐어도 불이 먼저 죽였으면 화재사망이다)
    actual = {nid for nid in eng.nonfire_ids if eng.by_id[nid].nonfire}
    polluted = actual & set(eng.estimator.deaths.keys())
    return {"nonfire_actual": len(actual), "nonfire_polluted": len(polluted),
            "pollution_rate": (len(polluted) / len(actual) * 100.0) if actual else 0.0,
            "fp_verifier": eng.verifier.false_positives,
            "n_confirmed": len(eng.estimator.deaths)}


# ───────────────────────── 보조 측정: 비화재 열원 오탐 (F2) ─────────────────────────
def job_fp_benign(a):
    arm, sname, ov, thr, bc, seed = a
    cfg = Config(mode="ours", seed=seed, peak=300.0, sensor_tau_s=11.0,
                 temp_threshold=thr, warn_temp=warn_for(thr, arm),
                 burn_scale_m=BURN, t_max=T_MAX,
                 benign_heat_c=bc, benign_heat_frac=(BENIGN_FRAC if bc > 0 else 0.0), **ov)
    eng = Engine(cfg)
    for _ in eng.stream():
        pass
    # 오탐 정의(명시): **죽은 시각에 그 자리의 '불 온도'가 임계 미만**이면 불 때문에 죽은 게 아니다.
    fire_fp = 0
    n_dead = 0
    for nd in eng.nodes:
        if nd.is_sink or nd.death_t is None:
            continue
        n_dead += 1
        # 사망 = DYING 진입 + last_gasp_delay. 임계를 밟은 시각은 dying_t.
        t_cross = nd.dying_t if nd.dying_t is not None else nd.death_t
        if eng.fire.temp_at(nd.pos, t_cross) < thr:
            fire_fp += 1
    confirmed_fp = 0
    for nid in eng.estimator.deaths:
        nd = eng.by_id[nid]
        t_cross = nd.dying_t if nd.dying_t is not None else nd.death_t
        if t_cross is not None and eng.fire.temp_at(nd.pos, t_cross) < thr:
            confirmed_fp += 1
    n_conf = len(eng.estimator.deaths)
    return {"n_dead": n_dead, "benign_fp": fire_fp,
            "benign_fp_rate": (fire_fp / n_dead * 100.0) if n_dead else 0.0,
            "n_confirmed": n_conf, "confirmed_fp": confirmed_fp,
            "confirmed_fp_rate": (confirmed_fp / n_conf * 100.0) if n_conf else 0.0}


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


def theory_row(thr, peak, cfg0):
    """이중 벌점 이론값: 임계교차 t/τ 와 임계 이상 펄스폭(s)."""
    amb, L, v = cfg0.ambient, cfg0.warm_scale, cfg0.speed_true
    if peak <= thr:
        return float("inf"), 0.0
    f = (thr - amb) / (peak - amb)
    k = math.log((peak - amb) / (thr - amb))
    return -math.log(1.0 - f), (L + BURN) * k / v


def plot(miss_rows, fp_rows, ben_rows, outdir):
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

    for arm in ("warn_fixed", "warn_coupled"):
        fig, axes = plt.subplots(2, len(PEAKS), figsize=(4.0 * len(PEAKS), 8.4))
        for j, pk in enumerate(PEAKS):
            for row, key, ttl, vmaxc in ((0, "miss_rate_mean", "미탐지율", "RdYlGn_r"),
                                         (1, "blind_rate_mean", "추정 불능률(미탐지+게이트탈락)",
                                          "RdYlGn_r")):
                M = np.zeros((len(TAUS), len(THRESHOLDS)))
                for i, tau in enumerate(TAUS):
                    for k, thr in enumerate(THRESHOLDS):
                        sel = [r for r in miss_rows if r["arm"] == arm and r["peak_C"] == pk
                               and r["tau_s"] == tau and r["threshold_C"] == thr]
                        M[i, k] = np.mean([r[key] for r in sel]) if sel else np.nan
                ax = axes[row][j]
                im = ax.imshow(M, cmap=vmaxc, vmin=0, vmax=100, aspect="auto", origin="lower")
                ax.set_xticks(range(len(THRESHOLDS)))
                ax.set_xticklabels([f"{t:.0f}" for t in THRESHOLDS], fontsize=8)
                ax.set_yticks(range(len(TAUS)))
                ax.set_yticklabels([f"{t:.1f}" for t in TAUS], fontsize=8)
                ax.set_xlabel("탐지 임계 (℃)", fontsize=9)
                if j == 0:
                    ax.set_ylabel("센서 τ (s)", fontsize=9)
                ax.set_title(f"{ttl}  peak={pk:.0f}℃", fontsize=9.5)
                for i in range(len(TAUS)):
                    for k in range(len(THRESHOLDS)):
                        if not np.isnan(M[i, k]):
                            ax.text(k, i, f"{M[i,k]:.0f}", ha="center", va="center", fontsize=8)
        fig.suptitle(f"2.K-C  임계 하향 스윕 [{arm}]  · 3 시나리오 평균 · 위=미탐지 / 아래=추정 불능",
                     fontsize=12)
        fig.tight_layout()
        p = os.path.join(outdir, f"heat_2k_c_miss_vs_threshold_{arm}.png")
        fig.savefig(p, dpi=110)
        plt.close(fig)
        print(f"  [png] {p}", flush=True)

    # 교환곡선: 임계 → (미탐지, 오탐)
    fig, axes = plt.subplots(1, 3, figsize=(16.5, 4.9))
    cols = {"warn_fixed": "#2980b9", "warn_coupled": "#c0392b"}
    ax = axes[0]
    for arm in ("warn_fixed", "warn_coupled"):
        for tau, ls in ((11.0, "-"), (78.5, "--")):
            ys = [np.mean([r["miss_rate_mean"] for r in miss_rows
                           if r["arm"] == arm and r["threshold_C"] == thr and r["tau_s"] == tau])
                  for thr in THRESHOLDS]
            ax.plot(THRESHOLDS, ys, ls, marker="o", color=cols[arm], lw=2,
                    label=f"{arm} τ={tau}")
    ax.axhline(5.0, color="k", ls=":", lw=1.5)
    ax.text(41, 6, "실용선 5 %", fontsize=9)
    ax.set_xlabel("탐지 임계 (℃)"); ax.set_ylabel("미탐지율 (%)")
    ax.set_title("(a) 임계 → 미탐지율 (전 피크 평균)", fontsize=11)
    ax.grid(alpha=0.3); ax.legend(fontsize=7.5)

    ax = axes[1]
    for arm in ("warn_fixed", "warn_coupled"):
        for tau, ls in ((11.0, "-"), (78.5, "--")):
            ys = [np.mean([r["pollution_rate_mean"] for r in fp_rows
                           if r["arm"] == arm and r["threshold_C"] == thr and r["tau_s"] == tau])
                  for thr in THRESHOLDS]
            ax.plot(THRESHOLDS, ys, ls, marker="s", color=cols[arm], lw=2,
                    label=f"{arm} τ={tau}")
    ax.set_xlabel("탐지 임계 (℃)"); ax.set_ylabel("비화재사망 오염률 (%)")
    ax.set_title("(b) 임계 → 2.D 오탐 (주 측정)", fontsize=11)
    ax.grid(alpha=0.3); ax.legend(fontsize=7.5)

    ax = axes[2]
    for bc in BENIGN_C:
        if bc == 0:
            continue
        ys = [np.mean([r["confirmed_fp_rate_mean"] for r in ben_rows
                       if r["arm"] == "warn_coupled" and r["threshold_C"] == thr
                       and r["benign_c"] == bc]) for thr in THRESHOLDS]
        ax.plot(THRESHOLDS, ys, marker="^", lw=2, label=f"비화재열원 +{bc:.0f}℃ (→{25+bc:.0f}℃)")
    ax.set_xlabel("탐지 임계 (℃)"); ax.set_ylabel("채택된 죽음 중 오탐 (%)")
    ax.set_title("(c) 보조축 · 비화재 열원 오탐 [warn_coupled]", fontsize=11)
    ax.grid(alpha=0.3); ax.legend(fontsize=8)

    fig.suptitle("2.K-C  교환곡선 — 미탐지는 내려가나, 그 대가는 무엇인가", fontsize=12)
    fig.tight_layout()
    p = os.path.join(outdir, "curve_2k_c_tradeoff.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    print(f"  [png] {p}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)       # 2.J-B와 동일
    ap.add_argument("--fp-seeds", type=int, default=30)    # 2.D/S11과 동일
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))
    fp_seeds = list(range(1, args.fp_seeds + 1))
    W = args.workers or n_workers()
    cfg0 = Config()
    ARMS = ("warn_fixed", "warn_coupled")

    print("=" * 104)
    print("2.K §3 · 탐지 임계값 하향 스윕 (임계 외 파라미터는 2.J-B 그대로)")
    print("=" * 104)
    print(f"  임계 {THRESHOLDS} ℃ (80=대조군) · τ {TAUS} s · 피크 {PEAKS} ℃ (100 제외)")
    print(f"  burn_scale={BURN} m · t_max={T_MAX} s · 시나리오 {[n for n,_ in SCENARIOS]}")
    print(f"  시드 미탐지 {args.seeds} / 오탐 {args.fp_seeds} · 워커 {W}")
    print(f"  두 팔: warn_fixed(warn=60 고정) / warn_coupled(warn=임계−{WARN_GAP:.0f})   ← F1 결합")
    print()
    print("  --- 이중 벌점 이론(측정 전) : 임계를 낮추면 교차는 빨라지나 펄스폭도 같이 변한다 ---")
    print(f"  {'임계℃':>6s} {'피크℃':>6s} {'f':>7s} {'교차 t/τ':>9s} {'임계이상 펄스폭(s)':>18s}"
          f" {'폭/τ@78.5':>10s}")
    for thr in THRESHOLDS:
        for pk in PEAKS:
            tot, w = theory_row(thr, pk, cfg0)
            f = (thr - cfg0.ambient) / (pk - cfg0.ambient)
            print(f"  {thr:6.0f} {pk:6.0f} {f:7.3f} {tot:9.3f} {w:18.2f} {w/78.5:10.3f}")
    print()

    # ---------------- ① 미탐지 ----------------
    jobs = [(arm, sn, ov, thr, tau, pk, sd)
            for arm in ARMS for sn, ov in SCENARIOS for thr in THRESHOLDS
            for tau in TAUS for pk in PEAKS for sd in seeds]
    print(f"  ① 미탐지 스윕 {len(jobs)} 런", flush=True)
    res = pmap(job_miss, jobs, workers=W, label="miss")
    miss_raw, miss_rows = [], []
    idx = 0
    for arm in ARMS:
        for sn, ov in SCENARIOS:
            for thr in THRESHOLDS:
                for tau in TAUS:
                    for pk in PEAKS:
                        rs = res[idx:idx + len(seeds)]
                        idx += len(seeds)
                        for i, r in enumerate(rs):
                            miss_raw.append({"arm": arm, "scenario": sn, "threshold_C": thr,
                                             "tau_s": tau, "peak_C": pk, "seed": seeds[i], **r})
                        miss_rows.append({
                            "arm": arm, "scenario": sn, "threshold_C": thr, "tau_s": tau,
                            "peak_C": pk,
                            "miss_rate_mean": round(float(np.mean([r["miss_rate"] for r in rs])), 2),
                            "miss_rate_std": round(float(np.std([r["miss_rate"] for r in rs])), 2),
                            "blind_rate_mean": round(float(np.mean([r["blind_rate"] for r in rs])), 2),
                            "n_confirmed_mean": round(float(np.mean([r["n_confirmed"] for r in rs])), 2),
                            "excluded_nonfire_mean": round(
                                float(np.mean([r["excluded_nonfire"] for r in rs])), 2),
                            "dir_ok_rate": round(float(np.mean([r["dir_ok"] for r in rs])) * 100, 1),
                            "exposed_mean": round(float(np.mean([r["exposed"] for r in rs])), 1)})
    write_csv(os.path.join(args.outdir, "raw_2k_c_threshold.csv"), miss_raw)
    write_csv(os.path.join(args.outdir, "summary_2k_c_miss_vs_threshold.csv"), miss_rows)

    # ---------------- ② 2.D 오탐 ----------------
    jobs = [(arm, sn, ov, thr, tau, sd)
            for arm in ARMS for sn, ov in SCENARIOS for thr in THRESHOLDS
            for tau in FP_TAUS for sd in fp_seeds]
    print(f"\n  ② 2.D 비화재사망 오탐 {len(jobs)} 런", flush=True)
    res = pmap(job_fp_nonfire, jobs, workers=W, label="fp2d")
    fp_rows = []
    idx = 0
    for arm in ARMS:
        for sn, ov in SCENARIOS:
            for thr in THRESHOLDS:
                for tau in FP_TAUS:
                    rs = res[idx:idx + len(fp_seeds)]
                    idx += len(fp_seeds)
                    tot_a = sum(r["nonfire_actual"] for r in rs)
                    tot_p = sum(r["nonfire_polluted"] for r in rs)
                    fp_rows.append({
                        "arm": arm, "scenario": sn, "threshold_C": thr, "tau_s": tau,
                        "nonfire_actual_total": tot_a, "nonfire_polluted_total": tot_p,
                        "pollution_rate_pooled": round(tot_p / tot_a * 100, 2) if tot_a else 0.0,
                        "pollution_rate_mean": round(
                            float(np.mean([r["pollution_rate"] for r in rs])), 2),
                        "fp_verifier_total": sum(r["fp_verifier"] for r in rs),
                        "n_confirmed_mean": round(
                            float(np.mean([r["n_confirmed"] for r in rs])), 2)})
    write_csv(os.path.join(args.outdir, "summary_2k_c_fp_nonfire.csv"), fp_rows)

    # ---------------- ③ 보조: 비화재 열원 오탐 ----------------
    BEN_SCEN = [s for s in SCENARIOS if s[0] in ("S1", "S2a_10")]
    jobs = [(arm, sn, ov, thr, bc, sd)
            for arm in ARMS for sn, ov in BEN_SCEN for thr in THRESHOLDS
            for bc in BENIGN_C for sd in fp_seeds]
    print(f"\n  ③ 보조 · 비화재 열원 오탐 {len(jobs)} 런", flush=True)
    res = pmap(job_fp_benign, jobs, workers=W, label="fpben")
    ben_rows = []
    idx = 0
    for arm in ARMS:
        for sn, ov in BEN_SCEN:
            for thr in THRESHOLDS:
                for bc in BENIGN_C:
                    rs = res[idx:idx + len(fp_seeds)]
                    idx += len(fp_seeds)
                    ben_rows.append({
                        "arm": arm, "scenario": sn, "threshold_C": thr, "benign_c": bc,
                        "benign_node_temp_C": 25.0 + bc,
                        "benign_fp_rate_mean": round(
                            float(np.mean([r["benign_fp_rate"] for r in rs])), 2),
                        "confirmed_fp_rate_mean": round(
                            float(np.mean([r["confirmed_fp_rate"] for r in rs])), 2),
                        "n_confirmed_mean": round(
                            float(np.mean([r["n_confirmed"] for r in rs])), 2)})
    write_csv(os.path.join(args.outdir, "summary_2k_c_fp_benign.csv"), ben_rows)

    plot(miss_rows, fp_rows, ben_rows, args.outdir)

    # ═══════════════════════ 표 ═══════════════════════
    def mm(rows, key, **f):
        sel = [r for r in rows if all(r[k] == v for k, v in f.items())]
        return float(np.mean([r[key] for r in sel])) if sel else float("nan")

    for arm in ARMS:
        print("\n" + "=" * 104)
        print(f"미탐지율 (%)  [{arm}]  · 3 시나리오 평균  · * = 실용선 5 % 초과")
        print("=" * 104)
        for pk in PEAKS:
            print(f"\n  --- 피크 {pk:.0f} ℃ ---")
            print(f"  {'τ(s)':>7s} " + "".join(f"{'thr '+str(int(t))+'℃':>13s}" for t in THRESHOLDS))
            for tau in TAUS:
                line = f"  {tau:7.1f} "
                for thr in THRESHOLDS:
                    v = mm(miss_rows, "miss_rate_mean", arm=arm, peak_C=pk,
                           tau_s=tau, threshold_C=thr)
                    line += f"{v:11.1f}{'*' if v > 5.0 else ' '} "
                print(line)

    for arm in ARMS:
        print("\n" + "=" * 104)
        print(f"★ 추정 불능률 (%) = 노출 노드 중 estimator에 **안 들어간** 비율  [{arm}]")
        print("   (미탐지 + 화재/비화재 게이트 탈락. F1 결합이 여기서 드러난다)")
        print("=" * 104)
        for pk in PEAKS:
            print(f"\n  --- 피크 {pk:.0f} ℃ ---")
            print(f"  {'τ(s)':>7s} " + "".join(f"{'thr '+str(int(t))+'℃':>13s}" for t in THRESHOLDS))
            for tau in TAUS:
                line = f"  {tau:7.1f} "
                for thr in THRESHOLDS:
                    v = mm(miss_rows, "blind_rate_mean", arm=arm, peak_C=pk,
                           tau_s=tau, threshold_C=thr)
                    line += f"{v:11.1f}{'*' if v > 5.0 else ' '} "
                print(line)

    print("\n" + "=" * 104)
    print("오탐 · 2.D 비화재사망 오염률 (%)  · 3 시나리오 · 30시드 pooled")
    print("=" * 104)
    print(f"  {'arm':13s} {'τ(s)':>6s} " + "".join(f"{'thr '+str(int(t))+'℃':>12s}"
                                                   for t in THRESHOLDS))
    for arm in ARMS:
        for tau in FP_TAUS:
            line = f"  {arm:13s} {tau:6.1f} "
            for thr in THRESHOLDS:
                sel = [r for r in fp_rows if r["arm"] == arm and r["tau_s"] == tau
                       and r["threshold_C"] == thr]
                ta = sum(r["nonfire_actual_total"] for r in sel)
                tp = sum(r["nonfire_polluted_total"] for r in sel)
                line += f"{(tp/ta*100 if ta else 0):12.2f}"
            print(line)

    print("\n" + "=" * 104)
    print("★ 보조축(F2) · 비화재 열원 오탐 — '채택된 죽음 중 불이 아니었던 비율' (%)")
    print("   (기존 모델엔 이 열원이 없어 주 측정이 임계 하향 비용을 과소평가한다)")
    print("=" * 104)
    print(f"  {'arm':13s} {'열원':>10s} " + "".join(f"{'thr '+str(int(t))+'℃':>12s}"
                                                    for t in THRESHOLDS))
    for arm in ARMS:
        for bc in BENIGN_C:
            line = f"  {arm:13s} {('+%d℃→%d℃' % (bc, 25+bc)) if bc else '없음(대조)':>10s} "
            for thr in THRESHOLDS:
                v = mm(ben_rows, "confirmed_fp_rate_mean", arm=arm, threshold_C=thr, benign_c=bc)
                line += f"{v:12.2f}"
            print(line)

    # ═══════════════════ ★ 핵심 판정표 ═══════════════════
    print("\n" + "=" * 104)
    print("★★ 핵심 판정 — 각 τ에서 '미탐지 ≤5 % AND 오탐 ≤ 임계80℃(대조군) 값' 을 동시 만족하는")
    print("   임계 구간이 존재하는가.  오탐 기준은 **같은 스윕의 80 ℃ 대조군 실측값**(임의 완화 금지)")
    print("=" * 104)
    verdict_rows = []
    for arm in ARMS:
        print(f"\n  ── {arm} ──")
        for tau in FP_TAUS:
            sel80 = [r for r in fp_rows if r["arm"] == arm and r["tau_s"] == tau
                     and r["threshold_C"] == 80.0]
            a80 = sum(r["nonfire_actual_total"] for r in sel80)
            p80 = sum(r["nonfire_polluted_total"] for r in sel80)
            base_fp = (p80 / a80 * 100) if a80 else 0.0
            print(f"    τ={tau:.1f}s · 오탐 기준(80℃ 대조군) = {base_fp:.2f} %")
            print(f"      {'피크℃':>7s} {'통과 임계(미탐지≤5 ∧ 오탐≤기준)':>34s}"
                  f" {'미탐지만 통과':>16s} {'추정불능도 ≤80℃대조군':>22s}")
            for pk in PEAKS:
                ok_miss, ok_both, ok_blind = [], [], []
                # 추정불능 기준도 **80 ℃ 대조군 실측값**. 절대선 5 %는 baseline(K_confirm=3 탓에
                # 항상 ~13 %)조차 못 넘으므로 판정 기준으로 부적합 — 대조군 대비로 잰다.
                base_blind = mm(miss_rows, "blind_rate_mean", arm=arm, peak_C=pk,
                                tau_s=tau, threshold_C=80.0)
                for thr in THRESHOLDS:
                    m = mm(miss_rows, "miss_rate_mean", arm=arm, peak_C=pk,
                           tau_s=tau, threshold_C=thr)
                    b = mm(miss_rows, "blind_rate_mean", arm=arm, peak_C=pk,
                           tau_s=tau, threshold_C=thr)
                    s = [r for r in fp_rows if r["arm"] == arm and r["tau_s"] == tau
                         and r["threshold_C"] == thr]
                    ta = sum(r["nonfire_actual_total"] for r in s)
                    tp = sum(r["nonfire_polluted_total"] for r in s)
                    fp = (tp / ta * 100) if ta else 0.0
                    if m <= 5.0:
                        ok_miss.append(thr)
                        if fp <= base_fp + 1e-9:
                            ok_both.append(thr)
                            if b <= base_blind + 1e-9:
                                ok_blind.append(thr)
                    verdict_rows.append({"arm": arm, "tau_s": tau, "peak_C": pk,
                                         "threshold_C": thr, "miss_rate": round(m, 2),
                                         "blind_rate": round(b, 2),
                                         "blind_baseline_80C": round(base_blind, 2),
                                         "fp_pollution": round(fp, 2),
                                         "fp_baseline_80C": round(base_fp, 2),
                                         "pass_miss": int(m <= 5.0),
                                         "pass_both": int(m <= 5.0 and fp <= base_fp + 1e-9),
                                         "pass_blind": int(m <= 5.0 and fp <= base_fp + 1e-9
                                                           and b <= base_blind + 1e-9)})
                f = lambda L: ("없음" if not L else
                               f"{min(L):.0f}~{max(L):.0f}℃ ({len(L)}점)")
                print(f"      {pk:7.0f} {f(ok_both):>34s} {f(ok_miss):>16s} {f(ok_blind):>20s}")
    write_csv(os.path.join(args.outdir, "summary_2k_c_verdict.csv"), verdict_rows)

    # ═══════════════════ 예측 대조 (플래그만) ═══════════════════
    print("\n" + "=" * 104)
    print("★ 사전등록 예측 대조 (해석 없이 일치/불일치만)")
    print("=" * 104)
    for arm in ARMS:
        for tau in TAUS:
            ys = [mm(miss_rows, "miss_rate_mean", arm=arm, tau_s=tau, threshold_C=thr)
                  for thr in THRESHOLDS]
            mono = all(ys[i] <= ys[i + 1] + 1e-9 for i in range(len(ys) - 1))
            print(f"  C1 단조(임계↑→미탐지↑)  {arm:13s} τ={tau:5.1f}: "
                  f"{'일치' if mono else '★불일치'}   값 {[round(v,1) for v in ys]}")
    print()
    for arm in ARMS:
        for pk in PEAKS:
            v45 = mm(miss_rows, "miss_rate_mean", arm=arm, peak_C=pk, tau_s=78.5, threshold_C=45.0)
            v50 = mm(miss_rows, "miss_rate_mean", arm=arm, peak_C=pk, tau_s=78.5, threshold_C=50.0)
            ok = (v45 <= 5.0) or (v50 <= 5.0)
            print(f"  C2 τ=78.5s·임계45~50℃가 실용선 진입  {arm:13s} peak={pk:3.0f}℃: "
                  f"{'일치' if ok else '★불일치'}  (45℃={v45:.1f}% / 50℃={v50:.1f}%)")


if __name__ == "__main__":
    main()
