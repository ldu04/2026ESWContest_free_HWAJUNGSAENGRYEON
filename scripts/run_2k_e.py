"""run_2k_e.py — 2.K §5 · **바람-결합 검증** (τ와 펄스폭을 독립 축으로 본 게 틀렸을 가능성).

배경: 지금까지 τ와 확산속도(→펄스폭)를 **독립 스윕**했다. 그러나 실제로는 둘 다 **'바람' 하나**에
묶여 있다. 바람↓ → τ↑(자연대류) 이지만 불도 느려져 펄스폭↑(유리). 바람↑ → 펄스폭↓ 이지만
τ↓(강제대류, 유리). 즉 2.J-B의 파국 셀(τ=78.5 s × v=1.5 m/s)은 **물리적으로 도달 불가능한
조합일 수 있다.** 그 격자 위의 어느 점이 실제로 밟을 수 있는 점인지 잰다.

═══════════════════════════════════════════════════════════════════════════════
★★ 이 스크립트가 쓰는 **가정** (측정값 아님 — 반드시 가정으로 읽을 것)
═══════════════════════════════════════════════════════════════════════════════
 A1. **τ(u) = 24.6 · u^(−0.5)**
     실측 **2점**(11.07 s @ 강제대류 ≈5 m/s, 78.48 s @ '정지공기' ≈0.1 m/s)에 맞춘 관계식.
     지수 −0.5는 강제대류 열전달의 통상 스케일링(Nu ∝ Re^0.5)에서 가져왔다.
     **2점으로 2모수를 맞췄으므로 자유도가 0 — 이 곡선은 검증된 적이 없다.**
     ⇒ 풍속계 실측으로 교체 예정. [D-045의 '열린 항목' = τ의 기류 의존성 정량화]
     ※ 실측 조건의 풍속 자체가 추정치다("에어컨 켠 방" ≈ 0.1 m/s, "드라이기" ≈ 5 m/s).
 A2. **v_spread = c · u**, c ∈ {0.05, 0.10, 0.15}
     문헌상 지표화(surface fire) 확산속도가 풍속의 5~15 % 범위라는 통상값. **가정이다.**
 A3. 확산속도 외 화재 형상(warm_scale·burn_scale·peak)은 바람과 무관하다고 둔다.
     실제로는 바람이 화염 경사·대류 예열을 바꿔 warm_scale도 건드릴 것이다. **미모형화 한계.**

★ 강령 준수
  · `sim/estimator.py` **불변**. 임계 80 ℃·warm_scale·burn_scale·estimator 전부 2.J-B 그대로.
  · 결론 문장 없음. 원자료·그래프·예측 어긋난 지점 플래그만.

★ 수치 처리 — **절단 아티팩트 방지**(2.J-A의 t_max 이중 실행과 같은 취지)
  느린 바람에서 전선이 격자를 건너는 데 수천 초가 걸린다. t_max를 120 s로 두면 전부
  '시간 절단'이지 물리가 아니다. 그래서 t_max를 **전선이 격자를 다 건널 만큼** 잡는다.
  그러면 틱 수가 폭발하므로 dt를 함께 키우되:
    · dt를 키우면 **틱당** dropout 확률이 초당 확률을 바꾼다 → `p_eff = 1−(1−p)^(dt/0.1)` 로
      **초당 hazard를 보존**한다(프로토콜 조건 불변).
    · dt 상향이 결과를 바꾸지 않는지 **dt 수렴 점검**을 별도로 돌려 같이 싣는다.

★ Cowork 가설 (신뢰도 낮음, 이 부류에서 이미 4번 틀림)
  E1: 도달 가능한 궤적 위에서는 미탐지가 대부분 실용선(≤5 %) 안에 들어온다.
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
from scripts.run_2e3_diagnose import TrueFront
from scripts._par import pmap, n_workers

OUTDIR = os.path.join("results", "stress")

WINDS = (0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0)     # m/s
C_SPREAD = (0.05, 0.10, 0.15)                      # v_spread = c·u  [가정 A2]
TAU_A, TAU_B = 24.6, -0.5                          # τ = TAU_A·u^TAU_B  [가정 A1]
BURN = 10.0                                        # 2.J-B 그대로
PEAKS = (150.0, 300.0, 500.0)                      # 유효피크(2.J-B 축의 부분집합)
MAX_TICKS = 40000                                  # dt 상향 트리거
SCENARIOS = [
    ("S1", {}),
    ("S2a_10", {"wind_noise_deg": 10.0}),
    ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                  "placement_jitter": 0.2, "p_dropout": 0.10}),
]


def tau_of(u):
    return TAU_A * (u ** TAU_B)


def pulse_width_s(v, thr=80.0, amb=25.0, peak=300.0, L=6.0):
    """임계 이상 구간의 이론 폭(초). (warm_scale + burn_scale)·ln((peak−amb)/(thr−amb)) / v"""
    if peak <= thr:
        return 0.0
    return (L + BURN) * math.log((peak - amb) / (thr - amb)) / v


def plan_time(v, tau, cfg0):
    """전선이 격자를 다 건널 t_max 와, 틱 수를 MAX_TICKS 이하로 두는 dt."""
    # 격자의 진행방향 투영 폭 + 시작 마진
    n = np.array(cfg0.direction())
    pts = np.array([(c * cfg0.spacing_m, r * cfg0.spacing_m)
                    for r in range(cfg0.grid_rows) for c in range(cfg0.grid_cols)])
    proj = pts @ n
    span = float(proj.max() - proj.min()) + cfg0.spacing_m * 0.5
    t_cross = span / v
    t_max = t_cross * 1.15 + 3.0 * tau + 10.0
    dt = max(0.1, t_max / MAX_TICKS)
    dt = round(dt, 4)
    return round(t_max, 1), dt


def p_dropout_for(base_p, dt):
    """dt를 키워도 **초당** 두절 hazard를 보존."""
    if dt <= 0.1 + 1e-9:
        return base_p
    return 1.0 - (1.0 - base_p) ** (dt / 0.1)


def job(a):
    sname, ov, u, c, peak, seed = a
    cfg0 = Config()
    v = c * u
    tau = tau_of(u)
    t_max, dt = plan_time(v, tau, cfg0)
    ov2 = dict(ov)
    ov2["p_dropout"] = p_dropout_for(ov.get("p_dropout", cfg0.p_dropout), dt)
    cfg = Config(mode="ours", seed=seed, peak=peak, sensor_tau_s=tau,
                 speed_true=v, burn_scale_m=BURN, t_max=t_max, dt=dt, **ov2)
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
    dir_err = (angle_deg(eng.estimator.dir_global, cfg.direction())
               if eng.estimator.dir_global else None)
    speed_err = ((eng.estimator.speed_global - v) / v * 100.0
                 if eng.estimator.speed_global else None)
    return {"exposed": exposed, "miss": miss,
            "miss_rate": (miss / exposed * 100.0) if exposed else 0.0,
            "dir_err": dir_err, "speed_err": speed_err,
            "n_confirmed": len(eng.estimator.deaths),
            "t_max": t_max, "dt": dt}


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

    fig, axes = plt.subplots(1, 3, figsize=(17.0, 5.0))
    cs = {0.05: "#2980b9", 0.10: "#27ae60", 0.15: "#c0392b"}

    ax = axes[0]
    for c in C_SPREAD:
        for pk, ls in zip(PEAKS, ("-", "--", ":")):
            ys = [np.mean([r["miss_rate_mean"] for r in rows
                           if r["wind_u"] == u and r["c_spread"] == c and r["peak_C"] == pk])
                  for u in WINDS]
            ax.plot(WINDS, ys, ls, marker="o", color=cs[c], lw=1.9,
                    label=f"c={c:.2f} peak={pk:.0f}℃")
    ax.axhline(5.0, color="k", ls=":", lw=1.5)
    ax.text(0.12, 6.5, "실용선 5 %", fontsize=9)
    ax.set_xscale("log")
    ax.set_xlabel("풍속 u (m/s)"); ax.set_ylabel("미탐지율 (%)")
    ax.set_title("(a) ★도달 가능한 궤적 위의 미탐지율", fontsize=11)
    ax.grid(alpha=0.3, which="both"); ax.legend(fontsize=6.5, ncol=2)

    ax = axes[1]
    taus = [tau_of(u) for u in WINDS]
    ax.plot(WINDS, taus, marker="o", color="#8e44ad", lw=2, label="τ(u)=24.6·u^−0.5 [가정]")
    ax.plot([5.0], [11.07], "k*", ms=15, label="실측 11.07 s")
    ax.plot([0.1], [78.48], "k*", ms=15, label="실측 78.48 s")
    ax2 = ax.twinx()
    for c in C_SPREAD:
        ax2.plot(WINDS, [pulse_width_s(c * u) for u in WINDS], "--", color=cs[c], lw=1.6,
                 label=f"펄스폭 c={c:.2f}")
    ax.set_xscale("log"); ax.set_yscale("log"); ax2.set_yscale("log")
    ax.set_xlabel("풍속 u (m/s)"); ax.set_ylabel("τ (s)")
    ax2.set_ylabel("임계이상 펄스폭 (s)")
    ax.set_title("(b) 두 축은 같은 바람에 묶여 있다", fontsize=11)
    ax.grid(alpha=0.3, which="both")
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=6.5, loc="upper right")

    ax = axes[2]
    for c in C_SPREAD:
        ax.plot(WINDS, [tau_of(u) / pulse_width_s(c * u) for u in WINDS],
                marker="s", color=cs[c], lw=2, label=f"c={c:.2f}")
    ax.axhline(1.2, color="k", ls=":", lw=1.5)
    ax.text(0.12, 1.3, "D-044 파단선 τ/폭=1.2", fontsize=8)
    ax.axhline(4.6, color="#c0392b", ls="-.", lw=1.2)
    ax.text(0.12, 5.0, "2.J-B 파국 셀 τ/폭=4.6", fontsize=8, color="#c0392b")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("풍속 u (m/s)"); ax.set_ylabel("τ / 펄스폭")
    ax.set_title("(c) ★결합하면 이 비가 어디까지 가는가 (peak 300℃)", fontsize=11)
    ax.grid(alpha=0.3, which="both"); ax.legend(fontsize=8)

    fig.suptitle("2.K-E  바람-결합 — τ와 펄스폭을 독립 축으로 본 것이 물리적으로 옳았는가", fontsize=12)
    fig.tight_layout()
    p = os.path.join(outdir, "curve_2k_e_wind_coupled.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    print(f"  [png] {p}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=15)
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))
    W = args.workers or n_workers()
    cfg0 = Config()

    print("=" * 108)
    print("2.K §5 · 바람-결합 검증 (τ와 v_spread를 하나의 바람 축에 묶는다)")
    print("=" * 108)
    print(f"  u {WINDS} m/s · c {C_SPREAD} · 피크 {PEAKS} ℃ · 시드 {args.seeds} · 워커 {W}")
    print(f"  τ(u) = {TAU_A}·u^{TAU_B}   ← ★가정(실측 2점 적합, 자유도 0). 풍속계 실측으로 교체 예정")
    print(f"  v_spread = c·u             ← ★가정(문헌 5~15 %)")
    print(f"  burn_scale={BURN} m · 임계 {cfg0.temp_threshold:.0f}℃ · warm_scale {cfg0.warm_scale:.0f} m"
          f"  (전부 2.J-B 그대로)\n")

    print("  --- 결합 궤적(측정 전 계산) : 각 u가 강제하는 (τ, v, 펄스폭, τ/폭) ---")
    print(f"  {'u(m/s)':>7s} {'τ(s)':>8s} " +
          "".join(f"{'v@c='+str(c):>11s}{'폭(s)':>10s}{'τ/폭':>8s}" for c in C_SPREAD) +
          f"{'t_max(s)':>11s}{'dt(s)':>8s}")
    for u in WINDS:
        tau = tau_of(u)
        line = f"  {u:7.2f} {tau:8.2f} "
        for c in C_SPREAD:
            v = c * u
            w = pulse_width_s(v)
            line += f"{v:11.4f}{w:10.1f}{tau/w:8.3f}"
        tm, dt = plan_time(C_SPREAD[0] * u, tau, cfg0)
        line += f"{tm:11.0f}{dt:8.4f}"
        print(line)
    print()
    print(f"  참고 · 2.J-B 격자의 파국 셀 = τ=78.5 s × v=1.5 m/s → 폭 {pulse_width_s(1.5):.1f} s,"
          f" τ/폭 {78.5/pulse_width_s(1.5):.2f}")
    print(f"        그 v=1.5 m/s 는 c=0.10 이면 u={1.5/0.10:.0f} m/s 를 요구하고,"
          f" 그 u에서 A1이 주는 τ = {tau_of(15.0):.2f} s 다.")
    print()

    # ─────────────────────────────────────────────────────────────────────
    # ★★ 착수 중 발견 — 느린 바람에서는 **τ가 아니라 dt_window가** 먼저 무너진다
    # ─────────────────────────────────────────────────────────────────────
    print("=" * 108)
    print("★★ 예비 진단(측정 전) — 느린 바람에서 방향 추정을 막는 것은 τ가 아니라 `dt_window` 다")
    print("=" * 108)
    print("  estimator._fit_local 은 이웃 j를 |t_j − t_i| ≤ dt_window 일 때만 국소 평면에 넣는다.")
    print(f"  현재 dt_window = {cfg0.dt_window:.1f} s 이고, 이 값은 **v=1.5 m/s 기준으로 잡혀 있다.**")
    print(f"  그런데 이웃 노드의 사망 간격 ≈ 노드간격({cfg0.spacing_m:.0f} m) / v 이므로 v가 느려지면")
    print("  간격이 dt_window를 넘어 **이웃이 한 명도 안 들어오고 → per_node 공집합 → 방향 None** 이 된다.")
    print("  (τ 문제와 완전히 별개의 실패 모드다. 미탐지율은 0 %인데 방향이 안 나온다.)")
    print()
    print(f"  {'u(m/s)':>7s} " + "".join(f"{'c='+str(c):>26s}" for c in C_SPREAD))
    print(f"  {'':>7s} " + "".join(f"{'이웃사망간격(s)':>15s}{'창내?':>11s}" for _c in C_SPREAD))
    for u in WINDS:
        line = f"  {u:7.2f} "
        for c in C_SPREAD:
            gap = cfg0.spacing_m / (c * u)
            line += f"{gap:15.1f}{('예' if gap <= cfg0.dt_window else '★아니오'):>11s}"
        print(line)
    print()
    print("  ⇒ 아래 방향오차 표의 '추정불가'는 **τ 때문이 아니라 이 창 때문**일 수 있다.")
    print("     둘을 구분하려고 '방향 추정 가능률' 표를 따로 낸다. dt_window는 **변경하지 않는다**(변수 오염 금지).")
    print()

    jobs = [(sn, ov, u, c, pk, sd)
            for sn, ov in SCENARIOS for u in WINDS for c in C_SPREAD
            for pk in PEAKS for sd in seeds]
    print(f"  스윕 {len(jobs)} 런", flush=True)
    res = pmap(job, jobs, workers=W, label="2k-e")

    raw, rows = [], []
    idx = 0
    for sn, ov in SCENARIOS:
        for u in WINDS:
            for c in C_SPREAD:
                for pk in PEAKS:
                    rs = res[idx:idx + len(seeds)]
                    idx += len(seeds)
                    for i, r in enumerate(rs):
                        raw.append({"scenario": sn, "wind_u": u, "c_spread": c, "peak_C": pk,
                                    "seed": seeds[i], "tau_s": round(tau_of(u), 3),
                                    "v_spread": round(c * u, 5), **r})
                    de = [r["dir_err"] for r in rs if r["dir_err"] is not None]
                    se = [r["speed_err"] for r in rs if r["speed_err"] is not None]
                    rows.append({
                        "scenario": sn, "wind_u": u, "c_spread": c, "peak_C": pk,
                        "tau_s": round(tau_of(u), 3), "v_spread": round(c * u, 5),
                        "pulse_width_s": round(pulse_width_s(c * u, peak=pk), 2),
                        "tau_over_width": round(tau_of(u) / pulse_width_s(c * u, peak=pk), 4),
                        "miss_rate_mean": round(float(np.mean([r["miss_rate"] for r in rs])), 2),
                        "miss_rate_std": round(float(np.std([r["miss_rate"] for r in rs])), 2),
                        "dir_err_mean": round(float(np.mean(de)), 3) if de else None,
                        "dir_err_std": round(float(np.std(de)), 3) if de else None,
                        "speed_err_mean": round(float(np.mean(se)), 3) if se else None,
                        "n_valid_dir": len(de),
                        "t_max": rs[0]["t_max"], "dt": rs[0]["dt"],
                        "exposed_mean": round(float(np.mean([r["exposed"] for r in rs])), 1)})
    write_csv(os.path.join(args.outdir, "raw_2k_e_wind_coupled.csv"), raw)
    write_csv(os.path.join(args.outdir, "summary_2k_e_wind_coupled.csv"), rows)
    plot(rows, args.outdir)

    def mm(key, **f):
        sel = [r for r in rows if all(r[k] == v for k, v in f.items()) and r[key] is not None]
        return float(np.mean([r[key] for r in sel])) if sel else float("nan")

    print("\n" + "=" * 108)
    print("★ 도달 가능한 궤적 위의 미탐지율 (%)  · 3 시나리오 평균  · * = 실용선 5 % 초과")
    print("=" * 108)
    for pk in PEAKS:
        print(f"\n  --- 피크 {pk:.0f} ℃ ---")
        print(f"  {'c':>6s} " + "".join(f"{'u='+str(u):>13s}" for u in WINDS))
        for c in C_SPREAD:
            line = f"  {c:6.2f} "
            for u in WINDS:
                v = mm("miss_rate_mean", c_spread=c, wind_u=u, peak_C=pk)
                line += f"{v:11.1f}{'*' if v > 5.0 else ' '} "
            print(line)

    print("\n" + "=" * 108)
    print("방향오차 (°)  · 3 시나리오 평균  · * = 실용선 5° 초과")
    print("=" * 108)
    for pk in PEAKS:
        print(f"\n  --- 피크 {pk:.0f} ℃ ---")
        print(f"  {'c':>6s} " + "".join(f"{'u='+str(u):>13s}" for u in WINDS))
        for c in C_SPREAD:
            line = f"  {c:6.2f} "
            for u in WINDS:
                v = mm("dir_err_mean", c_spread=c, wind_u=u, peak_C=pk)
                if math.isnan(v):
                    line += f"{'추정불가':>13s}"
                else:
                    line += f"{v:11.2f}{'*' if v > 5.0 else ' '} "
            print(line)

    print("\n" + "=" * 108)
    print("★★ 방향 추정 **가능률** (%) — 30런 중 dir_global 이 나온 비율 (0 % = 전부 추정불가)")
    print("   미탐지율과 나란히 볼 것: 미탐지 0 %인데 여기가 0 %면 '탐지는 됐으나 방향을 못 낸다'는 뜻")
    print("=" * 108)
    n_runs = len(seeds)
    for pk in PEAKS:
        print(f"\n  --- 피크 {pk:.0f} ℃ ---")
        print(f"  {'c':>6s} " + "".join(f"{'u='+str(u):>13s}" for u in WINDS))
        for c in C_SPREAD:
            line = f"  {c:6.2f} "
            for u in WINDS:
                sel = [r for r in rows if r["c_spread"] == c and r["wind_u"] == u
                       and r["peak_C"] == pk]
                tot_v = sum(r["n_valid_dir"] for r in sel)
                tot_n = n_runs * len(sel)
                v = (tot_v / tot_n * 100) if tot_n else float("nan")
                line += f"{v:11.0f}{'*' if v < 100 else ' '} "
            print(line)
    print("  (* = 일부/전부 추정불가)")

    print("\n" + "=" * 108)
    print("★ 핵심 판정 — 도달 가능한 (u, τ, v) 궤적 위에서 미탐지가 실용선(≤5 %)을 넘는 u 구간")
    print("=" * 108)
    verdict = []
    for c in C_SPREAD:
        for pk in PEAKS:
            bad = [u for u in WINDS if mm("miss_rate_mean", c_spread=c, wind_u=u, peak_C=pk) > 5.0]
            # 별개 실패 모드: 탐지는 되는데 방향이 안 나오는 u
            blind = []
            for u in WINDS:
                sel = [r for r in rows if r["c_spread"] == c and r["wind_u"] == u
                       and r["peak_C"] == pk]
                tot_v = sum(r["n_valid_dir"] for r in sel)
                if sel and tot_v == 0:
                    blind.append(u)
            verdict.append({"c_spread": c, "peak_C": pk,
                            "u_miss_over_line": ";".join(str(u) for u in bad) or "없음",
                            "n_u_miss_over": len(bad),
                            "u_no_direction": ";".join(str(u) for u in blind) or "없음",
                            "n_u_no_direction": len(blind), "n_u_total": len(WINDS)})
            print(f"  c={c:.2f}  peak={pk:3.0f}℃ → 미탐지 초과 " +
                  (f"★{bad} m/s ({len(bad)}/{len(WINDS)})" if bad else f"없음 (0/{len(WINDS)})") +
                  "   |  방향 전부 추정불가 " +
                  (f"★{blind} m/s ({len(blind)}/{len(WINDS)})" if blind
                   else f"없음 (0/{len(WINDS)})"))
    write_csv(os.path.join(args.outdir, "summary_2k_e_verdict.csv"), verdict)

    print("\n" + "=" * 108)
    print("★ 2.J-B 전체 격자와의 대조 — 격자 위의 (τ, v) 조합 중 A1·A2가 허용하는 것은 어디인가")
    print("=" * 108)
    print(f"  A1을 뒤집으면 u = ({TAU_A}/τ)^2 · 그 u가 강제하는 v = c·u")
    print(f"  {'τ(s)':>8s} {'⇒ u(m/s)':>10s} " +
          "".join(f"{'v@c='+str(c)+'(m/s)':>16s}" for c in C_SPREAD) +
          f"{'2.J-B가 쓴 v':>14s}")
    for tau in (11.0, 30.0, 50.0, 78.5, 100.0):
        u_req = (TAU_A / tau) ** 2
        line = f"  {tau:8.1f} {u_req:10.4f} "
        for c in C_SPREAD:
            line += f"{c*u_req:16.4f}"
        line += f"{1.5:14.1f}"
        print(line)
    print("\n  (2.J-B는 모든 τ에서 v=1.5 m/s 를 썼다. 위 표의 v와 1.5의 격차가 곧 '독립 축 가정'의 크기다.)")

    print("\n" + "=" * 108)
    print("★ 사전등록 가설 대조 (해석 없이 일치/불일치만)")
    print("=" * 108)
    tot = sum(v["n_u_miss_over"] for v in verdict)
    cells = sum(v["n_u_total"] for v in verdict)
    blindtot = sum(v["n_u_no_direction"] for v in verdict)
    print(f"  E1 '도달 가능 궤적에서는 미탐지가 대부분 실용선 안' → "
          f"실용선 초과 셀 {tot}/{cells} ({tot/cells*100:.1f} %)  "
          f"→ {'일치' if tot / cells < 0.2 else '★불일치'}")
    print(f"  ★예측에 없던 항목: **방향 전부 추정불가** 셀 {blindtot}/{cells} "
          f"({blindtot/cells*100:.1f} %) — 미탐지가 아니라 `dt_window`가 만든 별개 실패 모드")

    # ---------------- dt 수렴 점검 ----------------
    print("\n" + "=" * 108)
    print("★ dt 수렴 점검 — dt 상향이 결과를 바꾸지 않는지 (같은 조건을 dt 두 값으로)")
    print("=" * 108)
    probe = []
    for u in (2.0, 5.0):
        for c in (0.10,):
            v = c * u
            tau = tau_of(u)
            t_max, dt_auto = plan_time(v, tau, cfg0)
            for dt in sorted({0.1, dt_auto}):
                mr, de = [], []
                for sd in seeds[:10]:
                    cfg = Config(mode="ours", seed=sd, peak=300.0, sensor_tau_s=tau,
                                 speed_true=v, burn_scale_m=BURN, t_max=t_max, dt=dt,
                                 p_dropout=p_dropout_for(cfg0.p_dropout, dt))
                    eng = Engine(cfg)
                    for _ in eng.stream():
                        pass
                    tf = TrueFront(eng.fire)
                    ex = ms = 0
                    for nd in eng.nodes:
                        if nd.is_sink or tf.arrival(nd.pos) is None:
                            continue
                        ex += 1
                        if nd.death_t is None:
                            ms += 1
                    mr.append(ms / ex * 100 if ex else 0.0)
                    if eng.estimator.dir_global:
                        de.append(angle_deg(eng.estimator.dir_global, cfg.direction()))
                probe.append({"wind_u": u, "c_spread": c, "dt": dt, "t_max": t_max,
                              "miss_rate_mean": round(float(np.mean(mr)), 2),
                              "dir_err_mean": round(float(np.mean(de)), 3) if de else None})
                print(f"  u={u:.1f} c={c:.2f} dt={dt:<7.4f} t_max={t_max:8.1f} → "
                      f"미탐지 {np.mean(mr):6.2f} %  방향 "
                      f"{(f'{np.mean(de):.3f}°' if de else '추정불가')}")
    write_csv(os.path.join(args.outdir, "summary_2k_e_dt_convergence.csv"), probe)


if __name__ == "__main__":
    main()
