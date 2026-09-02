"""run_stress.py — 추정기 강건성 스트레스 테스트 하네스 (구현지시서 #2).

철학(§7): 측정이 먼저. 방어 파라미터(K_confirm·silence_timeout·dt_window)·추정기 알고리즘은 손대지 않는다.
스트레스는 ground-truth(화재·배치·통신)에만 가한다.

시나리오 S1~S7을 강도 스윕 × 다중 시드로 돌려:
  results/stress/raw_<S>.csv       각 시드·레벨 원자료
  results/stress/summary_<S>.csv   레벨별 평균±표준편차
  results/stress/curve_*.png       저하 곡선(에러바) — 최소 S2·S4·S5·S6
사람이 읽는 요약(STRESS_REPORT.md)은 이 CSV를 근거로 별도 작성.
"""
import argparse
import csv
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from sim.config import Config
from sim.engine import Engine
from sim.metrics import angle_deg

OUTDIR = os.path.join("results", "stress")
N_SEEDS_DEFAULT = 20

# 시드마다 다른 화재 실현을 만들기 위한 스트레스 위상 오프셋은 seed에 반영.
GRIDS = {9: (3, 3), 12: (4, 3), 16: (4, 4), 20: (4, 5), 25: (5, 5)}


# ---------------- 단일 실행 → 지표 ----------------
# [#2e-2] 전 시나리오에 공통으로 얹는 변이 플래그(--variant). 빈 dict면 기존 동작과 완전 동일.
BASE_OV: dict = {}


def run_metrics(seed, radial=False, nonfire=False, **overrides) -> dict:
    cfg = Config(mode="ours", seed=seed, **{**BASE_OV, **overrides})
    eng = Engine(cfg)
    for _ in eng.stream():
        pass
    s = eng.summarize()

    n_deaths = len(eng.estimator.deaths)
    coverage = (len(eng.estimator.per_node) / n_deaths) if n_deaths else 0.0

    m = {
        "dir_err_deg": s["final_dir_err_deg"],
        "speed_err_pct": s["final_speed_err_pct"],
        "eta_err_s": s["final_arrival_err_s"],
        "delivery_rate": s["final_delivery_rate"],
        "fp_rate": s["false_positive_rate"],
        "detect_lag_s": s["detect_lag_s_mean"],
        "coverage": round(coverage, 4),
        "reroute_ms_mean": s["reroute_delay_ms_mean"],
        "confirmed_deaths": s["confirmed_deaths"],
    }
    if radial:
        # S3: 노드별 국소 방향오차 vs 방사 방향, 국소 속도오차 vs 참 비등방 속도 [D-013, D-017]
        derrs, serrs = [], []
        for v in eng.estimator.per_node.values():
            rd = eng.fire.radial_dir(v["pos"])
            if rd is not None:
                derrs.append(angle_deg(v["dir"], rd))
            ts = eng.fire.true_local_speed(v["pos"])
            if ts > 1e-9:
                serrs.append(abs(v["speed"] - ts) / ts * 100.0)
        m["local_dir_median_deg"] = round(float(np.median(derrs)), 3) if derrs else None
        m["local_dir_p90_deg"] = round(float(np.percentile(derrs, 90)), 3) if derrs else None
        m["local_speed_median_pct"] = round(float(np.median(serrs)), 3) if serrs else None
        m["local_speed_p90_pct"] = round(float(np.percentile(serrs, 90)), 3) if serrs else None
    if nonfire:
        # 비화재 사망 '화선 오염률': 주입 노드가 사망확정(=화선 신호)으로 오분류된 비율 [D-028]
        inj = eng.nonfire_ids
        conf = inj & eng.verifier.confirmed
        m["nonfire_injected"] = len(inj)
        m["nonfire_confirmed"] = len(conf)
        m["nonfire_pollution_rate"] = round(len(conf) / len(inj), 4) if inj else 0.0
        # [#2e-1, D-032] 정정 지표(추가만, 위 정의는 불변):
        # nonfire_ids는 '예약' 집합이라, 주입 시각 전에 불에 타 죽은 노드도 포함된다.
        # 그런 노드는 진짜 화재사망이므로 확정되는 게 정상인데 위 분자에 잡혀 오염률을 부풀린다.
        # 실제로 강제 비화재 사망이 성립한 노드(nd.nonfire=True)만으로 다시 센다.
        act = {nd.id for nd in eng.nodes if nd.nonfire}
        conf_a = act & eng.verifier.confirmed
        m["nonfire_actual"] = len(act)
        m["nonfire_actual_confirmed"] = len(conf_a)
        m["nonfire_pollution_rate_actual"] = round(len(conf_a) / len(act), 4) if act else 0.0
    return m


# ---------------- 스윕 ----------------
def sweep(scenario, levels, seeds, radial=False, nonfire=False):
    """levels: [(level_value, level_label, overrides_dict), ...]"""
    raw = []
    for lv, label, ov in levels:
        for seed in seeds:
            m = run_metrics(seed, radial=radial, nonfire=nonfire, **ov)
            row = {"scenario": scenario, "level": lv, "level_label": label, "seed": seed}
            row.update(m)
            raw.append(row)
        print(f"  [{scenario}] level={label:16s} 완료 ({len(seeds)} seeds)")
    return raw


def summarize(raw, metric_keys):
    """레벨별 평균±표준편차(nan 무시)."""
    out = []
    levels = []
    for r in raw:
        key = (r["level"], r["level_label"])
        if key not in levels:
            levels.append(key)
    for lv, label in levels:
        sub = [r for r in raw if r["level"] == lv and r["level_label"] == label]
        agg = {"scenario": sub[0]["scenario"], "level": lv, "level_label": label,
               "n_seeds": len(sub)}
        for k in metric_keys:
            vals = np.array([r[k] for r in sub if r.get(k) is not None], dtype=float)
            if vals.size:
                agg[f"{k}_mean"] = round(float(np.mean(vals)), 4)
                agg[f"{k}_std"] = round(float(np.std(vals)), 4)
            else:
                agg[f"{k}_mean"] = None
                agg[f"{k}_std"] = None
        out.append(agg)
    return out


def write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fields = list(rows[0].keys())
    # 모든 행의 키 합집합(레벨마다 키가 조금 다를 수 있음)
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  [csv] {path} ({len(rows)} rows)")


# ---------------- 저하 곡선 ----------------
def curve(summary_rows, xkey_label, ykey, ylabel, title, path):
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
    xs = [r["level"] for r in summary_rows]
    ys = [r.get(f"{ykey}_mean") for r in summary_rows]
    es = [r.get(f"{ykey}_std") or 0 for r in summary_rows]
    xs2 = [x for x, y in zip(xs, ys) if y is not None]
    ys2 = [y for y in ys if y is not None]
    es2 = [e for e, y in zip(es, ys) if y is not None]
    if not xs2:
        return
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.errorbar(xs2, ys2, yerr=es2, marker="o", capsize=4, lw=2, color="#c0392b")
    ax.set_xlabel(xkey_label)
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11)
    ax.grid(True, alpha=0.3)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"  [png] {path}")


# ---------------- 시나리오 정의 ----------------
METRIC_KEYS = ["dir_err_deg", "speed_err_pct", "eta_err_s", "delivery_rate",
               "fp_rate", "detect_lag_s", "coverage", "reroute_ms_mean"]


# ---------------- 시나리오 러너(레지스트리) ----------------
def scen_S1(seeds, outdir):
    s = sweep("S1", [(0, "baseline", {})], seeds)
    write_csv(os.path.join(outdir, "raw_S1.csv"), s)
    summ = summarize(s, METRIC_KEYS)
    write_csv(os.path.join(outdir, "summary_S1.csv"), summ)
    return summ


def scen_S2a(seeds, outdir):
    lv = [(d, f"wind_{d}deg", {"wind_noise_deg": float(d)}) for d in (0, 5, 10, 20)]
    s = sweep("S2a", lv, seeds)
    write_csv(os.path.join(outdir, "raw_S2a_wind.csv"), s)
    summ = summarize(s, METRIC_KEYS)
    write_csv(os.path.join(outdir, "summary_S2a_wind.csv"), summ)
    curve(summ, "바람 θ 요동 표준편차 (deg)", "dir_err_deg", "방향오차 (°)",
          "S2a 바람 → 방향오차 (#2b: seed별 실현)",
          os.path.join(outdir, "curve_S2_wind_dir.png"))
    return summ


def scen_S2b(seeds, outdir):
    lv = [(int(p * 100), f"gust_{int(p*100)}pct", {"wind_speed_var_pct": p})
          for p in (0.0, 0.2, 0.4)]
    s = sweep("S2b", lv, seeds)
    write_csv(os.path.join(outdir, "raw_S2b_gust.csv"), s)
    summ = summarize(s, METRIC_KEYS)
    write_csv(os.path.join(outdir, "summary_S2b_gust.csv"), summ)
    curve(summ, "돌풍 속도변동 std (%)", "speed_err_pct", "속도오차 (%)",
          "S2b 돌풍 → 속도오차 (#2b: seed별 실현)",
          os.path.join(outdir, "curve_S2b_gust_speed.png"))
    return summ


def scen_S3(seeds, outdir):
    # #2b: 방사-바람 결합(비등방). 국소 방향+국소 속도로 평가. [D-017]
    lv = [(0, "radial", {"radial_fire": True}),
          (1, "radial_wind", {"radial_fire": True, "wind_bias": 0.4,
                              "wind_speed_var_pct": 0.2, "wind_noise_deg": 10.0})]
    s = sweep("S3", lv, seeds, radial=True)
    write_csv(os.path.join(outdir, "raw_S3_radial.csv"), s)
    summ = summarize(s, METRIC_KEYS + ["local_dir_median_deg", "local_dir_p90_deg",
                                       "local_speed_median_pct", "local_speed_p90_pct"])
    write_csv(os.path.join(outdir, "summary_S3_radial.csv"), summ)
    return summ


def scen_S4(seeds, outdir):
    lv = [(int(p * 100), f"jitter_{int(p*100)}pct", {"placement_jitter": p})
          for p in (0.0, 0.1, 0.2, 0.4)]
    s = sweep("S4", lv, seeds)
    write_csv(os.path.join(outdir, "raw_S4_jitter.csv"), s)
    summ = summarize(s, METRIC_KEYS)
    write_csv(os.path.join(outdir, "summary_S4_jitter.csv"), summ)
    curve(summ, "배치 흔들림 (spacing 대비 %)", "dir_err_deg", "방향오차 (°)",
          "S4 배치흔들림 → 방향오차", os.path.join(outdir, "curve_S4_jitter_dir.png"))
    return summ


def scen_S5(seeds, outdir):
    lv = [(int(p * 100), f"drop_{p}", {"p_dropout": p})
          for p in (0.02, 0.05, 0.10, 0.20, 0.30)]
    s = sweep("S5", lv, seeds)
    write_csv(os.path.join(outdir, "raw_S5_dropout.csv"), s)
    summ = summarize(s, METRIC_KEYS)
    write_csv(os.path.join(outdir, "summary_S5_dropout.csv"), summ)
    curve(summ, "dropout 확률 (%)", "delivery_rate", "전달률",
          "S5 dropout → 전달률", os.path.join(outdir, "curve_S5_dropout_delivery.png"))
    curve(summ, "dropout 확률 (%)", "fp_rate", "오탐률",
          "S5 dropout → 오탐률", os.path.join(outdir, "curve_S5_dropout_fp.png"))
    return summ


def scen_S6(seeds, outdir):
    lv = [(n, f"n{n}", {"grid_rows": GRIDS[n][1], "grid_cols": GRIDS[n][0],
                         "p_dropout": 0.05}) for n in (9, 12, 16, 20, 25)]
    s = sweep("S6", lv, seeds)
    write_csv(os.path.join(outdir, "raw_S6_density.csv"), s)
    summ = summarize(s, METRIC_KEYS)
    write_csv(os.path.join(outdir, "summary_S6_density.csv"), summ)
    curve(summ, "노드 수", "dir_err_deg", "방향오차 (°)",
          "S6 밀도 → 방향오차", os.path.join(outdir, "curve_S6_density_dir.png"))
    curve(summ, "노드 수", "speed_err_pct", "속도오차 (%)",
          "S6 밀도 → 속도오차", os.path.join(outdir, "curve_S6_density_speed.png"))
    return summ


def scen_S7(seeds, outdir):
    lv = [(1, "worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                        "placement_jitter": 0.2, "p_dropout": 0.10})]
    s = sweep("S7", lv, seeds)
    write_csv(os.path.join(outdir, "raw_S7_worst.csv"), s)
    summ = summarize(s, METRIC_KEYS)
    write_csv(os.path.join(outdir, "summary_S7_worst.csv"), summ)
    return summ


# ---- 지시서 #2c: 실물 괴리 환경 4요인 ----
def scen_S8(seeds, outdir):
    # ① 시계 지터(노드별 death_t_est 오프셋)
    lv = [(m, f"clock_{m}ms", {"clock_jitter_ms": float(m)}) for m in (0, 50, 100, 300)]
    s = sweep("S8", lv, seeds)
    write_csv(os.path.join(outdir, "raw_S8_clock.csv"), s)
    summ = summarize(s, METRIC_KEYS)
    write_csv(os.path.join(outdir, "summary_S8_clock.csv"), summ)
    curve(summ, "시계 지터 std (ms)", "dir_err_deg", "방향오차 (°)",
          "S8 시계 지터 → 방향오차 (실물 A-1)", os.path.join(outdir, "curve_S8_clock_dir.png"))
    curve(summ, "시계 지터 std (ms)", "speed_err_pct", "속도오차 (%)",
          "S8 시계 지터 → 속도오차", os.path.join(outdir, "curve_S8_clock_speed.png"))
    return summ


def scen_S9(seeds, outdir):
    # ② 온도 감지 지터(사망 검출 시각 노이즈)
    lv = [(int(x * 1000), f"temp_{x}s", {"temp_jitter_s": x}) for x in (0.0, 0.2, 0.5)]
    s = sweep("S9", lv, seeds)
    write_csv(os.path.join(outdir, "raw_S9_temp.csv"), s)
    summ = summarize(s, METRIC_KEYS)
    write_csv(os.path.join(outdir, "summary_S9_temp.csv"), summ)
    curve(summ, "온도 감지 지터 std (ms)", "dir_err_deg", "방향오차 (°)",
          "S9 온도 지터 → 방향오차 (실물 A-4)", os.path.join(outdir, "curve_S9_temp_dir.png"))
    return summ


def scen_S10(seeds, outdir):
    # ③ 비화(spot fire): 단일 전선 가정 붕괴
    lv = [(n, f"spots_{n}", {"n_spot_fires": n}) for n in (0, 1, 2, 3)]
    s = sweep("S10", lv, seeds)
    write_csv(os.path.join(outdir, "raw_S10_spot.csv"), s)
    summ = summarize(s, METRIC_KEYS)
    write_csv(os.path.join(outdir, "summary_S10_spot.csv"), summ)
    curve(summ, "비화 발화점 수", "dir_err_deg", "방향오차 (°)",
          "S10 비화 → 방향오차 (실물 A-5)", os.path.join(outdir, "curve_S10_spot_dir.png"))
    curve(summ, "비화 발화점 수", "coverage", "추정 커버리지",
          "S10 비화 → 커버리지", os.path.join(outdir, "curve_S10_spot_cov.png"))
    return summ


def scen_S11(seeds, outdir):
    # ④ 비화재 사망: #2d 전(OR게이트)/후(3분기) 나란히
    counts = (0, 2, 4, 8)
    extra = ["nonfire_injected", "nonfire_confirmed", "nonfire_pollution_rate",
             "nonfire_actual", "nonfire_actual_confirmed", "nonfire_pollution_rate_actual"]
    # before: 기존 OR게이트(nonfire_gate=False = #2c 상태)
    lv_off = [(n, f"nonfire_{n}", {"n_nonfire_deaths": n, "nonfire_gate": False})
              for n in counts]
    s_off = sweep("S11off", lv_off, seeds, nonfire=True)
    summ_off = _add_pooled_pollution(s_off, summarize(s_off, METRIC_KEYS + extra))
    write_csv(os.path.join(outdir, "summary_S11_nonfire_before.csv"), summ_off)
    # after: #2d 3분기(기본)
    lv_on = [(n, f"nonfire_{n}", {"n_nonfire_deaths": n}) for n in counts]
    s_on = sweep("S11on", lv_on, seeds, nonfire=True)
    write_csv(os.path.join(outdir, "raw_S11_nonfire.csv"), s_on)
    summ_on = _add_pooled_pollution(s_on, summarize(s_on, METRIC_KEYS + extra))
    write_csv(os.path.join(outdir, "summary_S11_nonfire_after.csv"), summ_on)
    # 전/후 겹친 오염률 곡선
    _curve_before_after(summ_off, summ_on, "비화재 사망 주입 수", "nonfire_pollution_rate",
                        "화선 오염률", "S11 비화재 사망 오염률: #2d 전(OR)/후(3분기)",
                        os.path.join(outdir, "curve_S11_nonfire_pollution_beforeafter.png"))
    _curve_before_after(summ_off, summ_on, "비화재 사망 주입 수", "dir_err_deg",
                        "방향오차 (°)", "S11 방향오차: #2d 전/후",
                        os.path.join(outdir, "curve_S11_nonfire_dir_beforeafter.png"))
    return summ_on


def _add_pooled_pollution(raw, summ):
    """[#2e-1, D-032] 레벨별 '노드 풀링' 오염률을 요약행에 추가.

    런 단위 평균은 '주입이 0건 성립한 런'을 0%로 세어 오염률을 저평가한다.
    Σ(확정된 실제 비화재) / Σ(실제 비화재) 로 노드를 통째로 모아 세는 쪽이 정본. (열 추가만)
    """
    for row in summ:
        sub = [r for r in raw if r["level"] == row["level"] and r["level_label"] == row["level_label"]]
        tot = sum(r.get("nonfire_actual", 0) or 0 for r in sub)
        cf = sum(r.get("nonfire_actual_confirmed", 0) or 0 for r in sub)
        row["nonfire_actual_total"] = tot
        row["nonfire_actual_confirmed_total"] = cf
        row["nonfire_pollution_pooled"] = round(cf / tot, 4) if tot else None
    return summ


def _curve_before_after(before, after, xlabel, ykey, ylabel, title, path):
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
    fig, ax = plt.subplots(figsize=(6, 4))
    for rows, lab, col in ((before, "#2d 전(OR게이트)", "#888"), (after, "#2d 후(3분기)", "#c0392b")):
        xs = [r["level"] for r in rows]
        ys = [r.get(f"{ykey}_mean") for r in rows]
        es = [r.get(f"{ykey}_std") or 0 for r in rows]
        xs2 = [x for x, y in zip(xs, ys) if y is not None]
        ys2 = [y for y in ys if y is not None]
        es2 = [e for e, y in zip(es, ys) if y is not None]
        ax.errorbar(xs2, ys2, yerr=es2, marker="o", capsize=4, lw=2, color=col, label=lab)
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel); ax.set_title(title, fontsize=11)
    ax.grid(True, alpha=0.3); ax.legend()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fig.tight_layout(); fig.savefig(path, dpi=120); plt.close(fig)
    print(f"  [png] {path}")


def scen_S2Dcheck(seeds, outdir):
    # #2d 비열화 증명: 대표 시나리오를 gate off/on 으로 돌려 방향·속도 오차 대조
    cases = [("S1", {}), ("S2a10", {"wind_noise_deg": 10.0}),
             ("S5_0.1", {"p_dropout": 0.10}), ("S8_100", {"clock_jitter_ms": 100.0}),
             ("S9_0.2", {"temp_jitter_s": 0.2}), ("S10_2", {"n_spot_fires": 2})]
    rows = []
    for name, ov in cases:
        for gate in (False, True):
            raw = [run_metrics(sd, **{**ov, "nonfire_gate": gate}) for sd in seeds]
            de = np.array([r["dir_err_deg"] for r in raw if r["dir_err_deg"] is not None])
            se = np.array([r["speed_err_pct"] for r in raw if r["speed_err_pct"] is not None])
            rows.append({"case": name, "gate": "on" if gate else "off",
                         "dir_err_mean": round(float(de.mean()), 3),
                         "dir_err_std": round(float(de.std()), 3),
                         "speed_err_mean": round(float(se.mean()), 3)})
    write_csv(os.path.join(outdir, "summary_2d_nondegradation.csv"), rows)
    print("  #2d 비열화 대조 (gate off vs on): case | gate | dir_mean±std | speed_mean")
    for r in rows:
        print(f"    {r['case']:8s} {r['gate']:3s}  {r['dir_err_mean']:6}±{r['dir_err_std']:5}  {r['speed_err_mean']}")
    return rows


def scen_S2Echeck(seeds, outdir):
    """[#2e-2] 세 변이(before / Fix A / Fix B)를 대표 시나리오에 나란히 — baseline 비열화·커버리지 비용.

    S11(비화재 주입)은 '고쳐야 할 대상'이라 여기 포함하지 않는다(효과는 run_2e2_variants.py 담당).
    여기 있는 건 전부 **해치면 안 되는** 시나리오다.
    """
    cases = [("S1", {}), ("S2a_10", {"wind_noise_deg": 10.0}),
             ("S2b_40", {"wind_speed_var_pct": 0.4}), ("S3_radial", {"radial_fire": True}),
             ("S4_20", {"placement_jitter": 0.2}), ("S5_0.1", {"p_dropout": 0.10}),
             ("S5_0.3", {"p_dropout": 0.30}),
             ("S6_n9", {"grid_rows": 3, "grid_cols": 3, "p_dropout": 0.05}),
             ("S6_n12", {"grid_rows": 3, "grid_cols": 4, "p_dropout": 0.05}),
             ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                           "placement_jitter": 0.2, "p_dropout": 0.10}),
             ("S8_300", {"clock_jitter_ms": 300.0}), ("S9_0.5", {"temp_jitter_s": 0.5}),
             ("S10_2", {"n_spot_fires": 2})]
    # 플래그 명시 — [D-036] 이후 빈 dict는 기본값(Fix A)이지 레거시가 아니다.
    variants = [("legacy_lenient", {"nonfire_strict_gate": False, "dtdt_gate": False}),
                ("FixA_strict", {"nonfire_strict_gate": True, "dtdt_gate": False}),
                ("FixB_dtdt", {"nonfire_strict_gate": False, "dtdt_gate": True})]
    rows = []
    for name, ov in cases:
        for vname, vov in variants:
            raw = [run_metrics(sd, **{**vov, **ov}) for sd in seeds]
            def agg(k):
                v = np.array([r[k] for r in raw if r.get(k) is not None], dtype=float)
                return (round(float(v.mean()), 4), round(float(v.std()), 4)) if v.size else (None, None)
            dm, ds = agg("dir_err_deg")
            sm, _ = agg("speed_err_pct")
            cm, _ = agg("coverage")
            dl, _ = agg("delivery_rate")
            fp, _ = agg("fp_rate")
            cd, _ = agg("confirmed_deaths")
            rows.append({"case": name, "variant": vname, "dir_err_mean": dm, "dir_err_std": ds,
                         "speed_err_mean": sm, "coverage_mean": cm, "delivery_mean": dl,
                         "fp_rate_mean": fp, "confirmed_deaths_mean": cd})
    write_csv(os.path.join(outdir, "summary_2e2_nondegradation.csv"), rows)
    ref = variants[0][0]        # 대조 기준 = 레거시 관대 채택
    print(f"  #2e-2 비열화 대조 ({' / '.join(v for v, _ in variants)})  · 기준={ref}")
    print(f"    {'case':10s} {'variant':12s} {'dir°':>9s} {'speed%':>9s} {'cover':>8s} "
          f"{'deliv':>8s} {'fp':>6s} {'confirmed':>10s}")
    for r in rows:
        flag = ""
        if r["variant"] != ref:
            b = next(x for x in rows if x["case"] == r["case"] and x["variant"] == ref)
            if b["dir_err_mean"] is not None and r["dir_err_mean"] is not None:
                d = r["dir_err_mean"] - b["dir_err_mean"]
                flag = f"   Δdir={d:+.3f}" + ("  ★열화" if d > 0.05 else "")
        print(f"    {r['case']:10s} {r['variant']:12s} {r['dir_err_mean']:9} {r['speed_err_mean']:9} "
              f"{r['coverage_mean']:8} {r['delivery_mean']:8} {r['fp_rate_mean']:6} "
              f"{r['confirmed_deaths_mean']:10}{flag}")
    return rows


SCENARIOS = {
    "S1": scen_S1, "S2a": scen_S2a, "S2b": scen_S2b, "S3": scen_S3,
    "S4": scen_S4, "S5": scen_S5, "S6": scen_S6, "S7": scen_S7,
    "S8": scen_S8, "S9": scen_S9, "S10": scen_S10, "S11": scen_S11,
    "S2Dcheck": scen_S2Dcheck, "S2Echeck": scen_S2Echeck,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=N_SEEDS_DEFAULT)
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--only", default=None,
                    help="쉼표로 시나리오 선택(예: S2a,S2b,S3,S7). 미지정 시 전체.")
    ap.add_argument("--variant", default="default", choices=("default", "legacy", "fixA", "fixB"),
                    help="[#2e-2] 전 시나리오에 얹을 선별 게이트 변이. "
                         "default=현재 기본값(Fix A, [D-036]) / legacy=#2d 관대 채택 / fixA / fixB.")
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))
    outdir = args.outdir

    global BASE_OV
    BASE_OV = {"legacy": {"nonfire_strict_gate": False, "dtdt_gate": False},
               "fixA": {"nonfire_strict_gate": True, "dtdt_gate": False},
               "fixB": {"nonfire_strict_gate": False, "dtdt_gate": True}}.get(args.variant, {})
    if BASE_OV:
        print(f"[변이 적용] --variant {args.variant} → {BASE_OV}")

    if args.only:
        names = [x.strip() for x in args.only.split(",") if x.strip()]
    else:
        names = list(SCENARIOS.keys())
    bad = [n for n in names if n not in SCENARIOS]
    if bad:
        raise SystemExit(f"알 수 없는 시나리오: {bad}. 가능: {list(SCENARIOS.keys())}")

    print(f"스트레스 테스트: seeds={args.seeds}, 시나리오={names}, outdir={outdir}\n")
    for n in names:
        print(f"== {n} ==")
        SCENARIOS[n](seeds, outdir)
    print("\n완료. results/stress/ 에 CSV·PNG 저장. STRESS_REPORT.md는 이 자료로 작성.")


if __name__ == "__main__":
    main()
