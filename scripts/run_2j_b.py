"""run_2j_b.py — 2.J 파트 B · **미탐지율 × 불 피크온도** 스윕.

배경: 2.I-a의 "τ/펄스폭 > 1.2 부터 미탐지"는 **특정 피크온도**를 가정한 숫자였다.
1차 지연에서 임계 교차 시각 `t = −τ·ln(1−f)`, `f = (임계−상온)/(피크−상온)`.
피크가 높을수록 f가 작아 같은 임계를 **훨씬 빨리** 밟는다 → 미탐지 걱정이 갉인다.
그게 **얼마나** 갉이는지 표면으로 잰다.

★ 강령 준수
  · 2.I-a의 **임계(80℃)·펄스형태(burn_scale)·전선·estimator 전부 불변**. 피크온도 축만 추가.
  · 체리피킹 금지 — 유리한 고피크만 강조하지 않고 **표면 전체**를 낸다.
  · 결론 문장 없음. 데이터·그래프만.

★ 사전등록 예측
  B1: 피크↑ → 미탐지율↓ (단조).
  B2: 노드가 겪는 피크는 화염온도가 아니라 **warm_scale 감쇠로 낮아진 값**이다.
      멀리 스치는 노드는 저피크 → 미탐지 위험이 되살아난다. 단일 피크로 "안전" 결론 금지.

★ 실행 중 발견하면 플래그할 것 (예측에 없던 결합)
  피크를 낮추면 임계 교차가 느려질 뿐 아니라 **80℃ 이상 구간(펄스폭) 자체가 짧아진다**.
  T(d) = amb + (peak−amb)·exp(−d/L) 에서 80℃가 되는 거리가 피크와 함께 줄기 때문.
  → 이중 벌점. 그래서 각 피크의 **이론 펄스폭**을 같이 계산해 표에 싣는다.
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
from scripts.run_2e3_stepE import OUTDIR

PEAKS = (100.0, 150.0, 200.0, 300.0, 500.0)      # 센서 위치 유효 피크(℃)
TAUS = (11.0, 30.0, 50.0, 78.5, 100.0)           # 실측 11 / 78.5 포함
BURN = 10.0                                       # 2.I-a 펄스 형태 그대로
T_MAX = 250.0                                     # 느린 센서가 응답을 끝낼 시간
SCENARIOS = [
    ("S1", {}),
    ("S2a_10", {"wind_noise_deg": 10.0}),
    ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                  "placement_jitter": 0.2, "p_dropout": 0.10}),
]


def theory(peak, cfg):
    """이론값: 임계 교차 배율 t/τ 와 80℃ 이상 펄스폭(초)."""
    amb, thr, L, v = cfg.ambient, cfg.temp_threshold, cfg.warm_scale, cfg.speed_true
    if peak <= thr:
        return None, 0.0
    f = (thr - amb) / (peak - amb)
    t_over_tau = -math.log(1.0 - f) if f < 1 else float("inf")
    # 80℃ 이상 구간: 전선 앞 L·ln((peak-amb)/(thr-amb)), 뒤 BURN·ln(...)
    k = math.log((peak - amb) / (thr - amb))
    width_m = (L + BURN) * k
    return t_over_tau, width_m / v


def run_one(seed, ov, peak, tau):
    cfg = Config(mode="ours", seed=seed, peak=peak, sensor_tau_s=tau,
                 burn_scale_m=BURN, t_max=T_MAX, **ov)
    eng = Engine(cfg)
    smax = {nd.id: nd.temp for nd in eng.nodes}
    for _ in eng.stream():
        for nd in eng.nodes:
            if nd.temp > smax[nd.id]:
                smax[nd.id] = nd.temp
    tf = TrueFront(eng.fire)

    exposed = miss = 0
    peaks = []
    for nd in eng.nodes:
        if nd.is_sink:
            continue
        if tf.arrival(nd.pos) is None:      # 전선이 안 닿은 노드는 대상 아님
            continue
        exposed += 1
        peaks.append(smax[nd.id])
        if nd.death_t is None:
            miss += 1
    return {"exposed": exposed, "miss": miss,
            "miss_rate": (miss / exposed * 100.0) if exposed else 0.0,
            "sensor_peak": float(np.mean(peaks)) if peaks else None}


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


def plot(rows, outdir, cfg0):
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

    # 시나리오 평균 히트맵
    M = np.zeros((len(TAUS), len(PEAKS)))
    S = np.zeros_like(M)
    for i, tau in enumerate(TAUS):
        for j, pk in enumerate(PEAKS):
            sel = [r for r in rows if r["tau_s"] == tau and r["peak_C"] == pk]
            M[i, j] = np.mean([r["miss_rate_mean"] for r in sel])
            S[i, j] = np.mean([r["sensor_peak_mean"] for r in sel if r["sensor_peak_mean"]])

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.0))
    im = axes[0].imshow(M, cmap="RdYlGn_r", vmin=0, vmax=100, aspect="auto", origin="lower")
    axes[0].set_xticks(range(len(PEAKS)))
    axes[0].set_xticklabels([f"{p:.0f}" for p in PEAKS])
    axes[0].set_yticks(range(len(TAUS)))
    axes[0].set_yticklabels([f"{t:.1f}" for t in TAUS])
    axes[0].set_xlabel("센서 위치 유효 피크온도 (℃)")
    axes[0].set_ylabel("센서 시상수 τ (s)")
    axes[0].set_title("(a) 미탐지율 (%)  · 3 시나리오 평균", fontsize=11)
    for i in range(len(TAUS)):
        for j in range(len(PEAKS)):
            axes[0].text(j, i, f"{M[i,j]:.0f}", ha="center", va="center",
                         fontsize=10, color="black")
    fig.colorbar(im, ax=axes[0], label="미탐지율 %")

    im2 = axes[1].imshow(S - cfg0.temp_threshold, cmap="RdYlGn", vmin=-60, vmax=60,
                         aspect="auto", origin="lower")
    axes[1].set_xticks(range(len(PEAKS)))
    axes[1].set_xticklabels([f"{p:.0f}" for p in PEAKS])
    axes[1].set_yticks(range(len(TAUS)))
    axes[1].set_yticklabels([f"{t:.1f}" for t in TAUS])
    axes[1].set_xlabel("센서 위치 유효 피크온도 (℃)")
    axes[1].set_ylabel("센서 시상수 τ (s)")
    axes[1].set_title("(b) 센서 도달최고온 − 임계 80℃ (마진, ℃)", fontsize=11)
    for i in range(len(TAUS)):
        for j in range(len(PEAKS)):
            axes[1].text(j, i, f"{S[i,j]-cfg0.temp_threshold:+.0f}", ha="center",
                         va="center", fontsize=9, color="black")
    fig.colorbar(im2, ax=axes[1], label="마진 ℃")

    fig.suptitle("2.J-B  미탐지율 × 불 피크온도  (임계 80℃ 고정, 펄스형태 2.I-a 그대로)",
                 fontsize=12)
    fig.tight_layout()
    p = os.path.join(outdir, "heat_2j_b_miss_vs_peak_tau.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    print(f"  [png] {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--outdir", default=OUTDIR)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))
    cfg0 = Config()

    print("2.J-B · 미탐지율 × 피크온도 (임계·펄스형태·estimator 불변, 피크 축만 추가)")
    print(f"  피크 {PEAKS} ℃ · τ {TAUS} s · burn_scale={BURN} m · t_max={T_MAX} s · 시드 {args.seeds}")
    print(f"  시나리오 {[n for n,_ in SCENARIOS]}")
    print()
    print("  --- 이론(측정 전): 피크가 낮으면 이중 벌점 ---")
    print(f"  {'피크℃':>7s} {'f=(80-25)/(pk-25)':>18s} {'임계교차 t/τ':>13s} {'80℃이상 펄스폭(s)':>18s}")
    for pk in PEAKS:
        tot, w = theory(pk, cfg0)
        f = (cfg0.temp_threshold - cfg0.ambient) / (pk - cfg0.ambient)
        print(f"  {pk:7.0f} {f:18.3f} {tot:13.3f} {w:18.2f}")
    print()

    rows = []
    for name, ov in SCENARIOS:
        for pk in PEAKS:
            for tau in TAUS:
                rs = [run_one(sd, ov, pk, tau) for sd in seeds]
                mr = float(np.mean([r["miss_rate"] for r in rs]))
                sp = [r["sensor_peak"] for r in rs if r["sensor_peak"] is not None]
                rows.append({"scenario": name, "peak_C": pk, "tau_s": tau,
                             "miss_rate_mean": round(mr, 2),
                             "miss_rate_std": round(float(np.std([r["miss_rate"] for r in rs])), 2),
                             "sensor_peak_mean": round(float(np.mean(sp)), 2) if sp else None,
                             "margin_vs_thr": (round(float(np.mean(sp)) - cfg0.temp_threshold, 2)
                                               if sp else None),
                             "exposed_mean": round(float(np.mean([r["exposed"] for r in rs])), 1)})
        print(f"  [{name:10s}] 완료")
    write_csv(os.path.join(args.outdir, "summary_2j_b_miss_vs_peak.csv"), rows)
    plot(rows, args.outdir, cfg0)

    # ---------- 표 ----------
    print("\n" + "=" * 100)
    print("미탐지율 (%)  · 3 시나리오 평균  · 임계 80℃ 고정")
    print("=" * 100)
    print(f"  {'τ(s)':>7s} " + "".join(f"{'peak '+str(int(p))+'℃':>14s}" for p in PEAKS))
    for tau in TAUS:
        line = f"  {tau:7.1f} "
        for pk in PEAKS:
            sel = [r for r in rows if r["tau_s"] == tau and r["peak_C"] == pk]
            line += f"{np.mean([r['miss_rate_mean'] for r in sel]):14.1f}"
        print(line)

    print("\n" + "=" * 100)
    print("센서 도달최고온 − 임계 80℃  (마진, ℃)  · 음수 = 임계 미달")
    print("=" * 100)
    print(f"  {'τ(s)':>7s} " + "".join(f"{'peak '+str(int(p))+'℃':>14s}" for p in PEAKS))
    for tau in TAUS:
        line = f"  {tau:7.1f} "
        for pk in PEAKS:
            sel = [r for r in rows if r["tau_s"] == tau and r["peak_C"] == pk
                   and r["margin_vs_thr"] is not None]
            line += f"{np.mean([r['margin_vs_thr'] for r in sel]):+14.1f}" if sel else f"{'-':>14s}"
        print(line)

    print("\n" + "=" * 100)
    print("실용선 미탐지율 ≤5 % 를 지키는 τ 상한 (피크별)")
    print("=" * 100)
    print(f"  {'피크℃':>7s} {'τ 상한(s)':>12s}   (스윕점 {TAUS} 기준)")
    for pk in PEAKS:
        ok = [t for t in TAUS
              if np.mean([r["miss_rate_mean"] for r in rows
                          if r["tau_s"] == t and r["peak_C"] == pk]) <= 5.0]
        print(f"  {pk:7.0f} {(max(ok) if ok else 0):12}   " +
              ("(전 τ 통과)" if len(ok) == len(TAUS) else
               ("(전 τ 실패)" if not ok else "")))

    # ---------- 현실 운영점 오버레이 (해석 없이 계산만) ----------
    print("\n" + "=" * 100)
    print("★ 현실 운영점 — warm_scale 감쇠로 본 '센서 위치 유효 피크'")
    print("=" * 100)
    L = cfg0.warm_scale
    print(f"  T_eff(d) = {cfg0.ambient:.0f} + (T_flame − {cfg0.ambient:.0f})·exp(−d/{L:.0f})")
    print(f"  {'화염℃':>7s} " + "".join(f"{'d for '+str(int(p))+'℃':>14s}" for p in PEAKS))
    for flame in (600.0, 800.0, 1000.0, 1200.0):
        line = f"  {flame:7.0f} "
        for pk in PEAKS:
            if pk >= flame:
                line += f"{'-':>14s}"
            else:
                d = L * math.log((flame - cfg0.ambient) / (pk - cfg0.ambient))
                line += f"{d:12.2f} m"
        print(line)
    print()
    print(f"  참고: 노드 간격 {cfg0.spacing_m:.0f} m, 무선거리 {cfg0.radio_range_m:.0f} m")
    print("  (위 거리 = 화염 중심으로부터 그 유효피크가 되는 수직거리. 불이 노드 바로 위를")
    print("   지나면 d≈0 이라 유효피크=화염온도에 가깝고, 비껴가면 d가 커져 유효피크가 급감한다.)")


if __name__ == "__main__":
    main()
