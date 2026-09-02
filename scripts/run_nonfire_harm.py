"""run_nonfire_harm.py — #2e-1 비화재 사망 '해악' 재측정 (찬/뜨거운 구역 분리).

문제의식(지시서 #2e-1): 기존 지표 `nonfire_pollution_rate`(오분류율)는 "화재사망으로
분류됐나"만 센다. 그러나 **뜨거운 구역에서 죽은 비화재 노드는 그 자리에 불이 실제로 와 있어**
도착시각 평면에 대체로 맞을 수 있고, 반대로 **찬 구역 비화재**는 엉뚱한 가짜 화선을 만든다.
→ '오분류율'이 아니라 **실제 해악**을 잰다.

★ 규율: **측정만**. sim/ 아래 estimator·verification·방어 파라미터를 단 한 줄도 바꾸지 않는다.
  해악은 Engine이 이미 노출하는 값(estimator.deaths / verifier.confirmed / fire.temp_at)만 읽고,
  **신선한 Estimator 인스턴스에 사망 이벤트 부분집합을 재투입**하는 반사실(counterfactual)
  재적합으로 계산한다(estimator를 라이브러리로 호출할 뿐, 로직 불변).

측정 정의
---------
* 그룹 분류(사망 시점 **참 국소온도** T = fire.temp_at(pos, death_t)):
    HOT : T >= warn_temp(60)            — 접근 중인 불에 이미 가열됨
    WARM: warn_temp-Δ <= T < warn_temp  — 경계 밴드(따로 보고)
    COOL: T <  warn_temp-Δ (Δ=10℃)      — 불에서 뚜렷이 먼 자리
  Δ=10℃는 테스트 점수가 아니라 **물리**에서 도출: 온도장 T=ambient+(peak-ambient)e^(-d/warm_scale),
  warm_scale=6m → T=60℃는 전선 12.4m 앞, T=50℃는 14.4m 앞. 즉 COOL = "전선이 노드간격(10m)
  한 칸 이상 밖". 방어 파라미터가 아니라 **보고용 구간**이다.
* (a) 통과율 = 그 그룹 중 verifier.confirmed 에 든 비율(화재사망으로 오분류돼 estimator에 들어감).
* (b) 해악  = err(전부 포함) − err(그 그룹의 confirmed 노드만 제외하고 재적합).  양수 = 그 그룹이 해롭다.
       그룹 단위 + **노드별 leave-one-out** 둘 다.
* (c) 공간 변위 2종:
       c1 (노드별) = 주입 노드 ↔ 사망시점 **참 화선**까지의 부호 거리(m). 가짜 화선 점이 실제와 얼마나 떨어졌나.
       c2 (전역)  = mean_p |T_pred(p) − T_true(p)| × speed_true  [m] — 추정 도착시각면이 참 화선에서 밀린 거리.
                    (전 비-sink 노드 위치 p에서 평균. metrics의 arrival_err_s를 거리로 환산한 형태)

산출물 (results/stress/)
  raw_2e1_nonfire_nodes.csv     주입 노드 1개당 1행(그룹·통과·거리·LOO 해악)
  summary_2e1_group.csv         (주입수 × 그룹)별 통과율·거리·LOO 해악
  summary_2e1_group_overall.csv 그룹별 전체 집계 — ★ COOL 통과율 헤드라인
  summary_2e1_groupexcl.csv     (주입수 × 그룹)별 '그룹 통째 제외' 해악
  summary_2e1_scale.csv         주입수별 해악 스케일(포함 / COOL제외 / HOT제외 / 전부제외)
  curve_2e1_harm_scale.png      해악 곡선(현실성 맥락 주석 포함)
  curve_2e1_group_passrate.png  그룹별 통과율 막대 + 그룹 해악
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
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from sim.config import Config
from sim.engine import Engine
from sim.estimator import Estimator
from sim.metrics import angle_deg

OUTDIR = os.path.join("results", "stress")
COUNTS = (1, 2, 4, 8)

# ★ [D-036] 이후 프로젝트 기본값은 Fix A(nonfire_strict_gate=True)로 바뀌었다.
# 그러나 #2e-1은 **그 이전(#2d) 기본값에서의 해악**을 잰 측정이고 STRESS_REPORT §1d가 그 수치를 인용한다.
# 기본값 변경에 산출물이 조용히 따라 움직이지 않도록 여기서 레거시 설정을 **명시 고정**한다.
# (변이 비교는 run_2e2_variants.py가 이 값을 덮어써서 수행한다.)
LEGACY = {"nonfire_strict_gate": False, "dtdt_gate": False}
COOL_MARGIN_C = 10.0          # Δ: warn_temp 대비 '뚜렷이 낮음' 기준(물리 도출, 위 docstring)
GROUPS = ("COOL", "WARM", "HOT")


# ---------------- 반사실 재적합 (estimator를 라이브러리로 호출, 로직 불변) ----------------
def refit(cfg, neighbors, deaths_map, drop_ids, fire, nodes, t_final):
    """deaths_map(id->(x,y,t_est))에서 drop_ids를 뺀 집합으로 신선한 Estimator를 적합.

    반환: (dir_err_deg, speed_err_pct, disp_m, n_used)
    """
    est = Estimator(cfg, neighbors=neighbors)
    events = [{"id": i, "pos": (x, y), "death_t_est": t}
              for i, (x, y, t) in deaths_map.items() if i not in drop_ids]
    out = est.update(events, t_final, None)

    dir_err = angle_deg(out["dir"], cfg.direction()) if out["dir"] is not None else float("nan")
    sp = out["speed"]
    speed_err = (abs(sp - cfg.speed_true) / cfg.speed_true * 100.0) if sp else float("nan")

    errs = []
    for nd in nodes:
        if nd.is_sink:
            continue
        tp = est.predict_arrival(nd.pos)
        if tp is not None:
            errs.append(abs(tp - fire.T_true(nd.pos)))
    disp = (float(np.mean(errs)) * cfg.speed_true) if errs else float("nan")
    return dir_err, speed_err, disp, len(events)


def classify(temp_c, warn_c):
    if temp_c >= warn_c:
        return "HOT"
    if temp_c >= warn_c - COOL_MARGIN_C:
        return "WARM"
    return "COOL"


# ---------------- 단일 실행 ----------------
def _confirmed_with_orgate(seed, n_inject):
    """같은 시드를 #2d 이전 OR게이트(nonfire_gate=False)로 돌려 confirmed 집합만 얻는다.

    물리(화재·노드사망·라우팅·dropout)는 gate와 무관하게 동일 스트림이므로 노드 단위 대조가 성립.
    → '찬 구역 비화재를 #2d 게이트가 실제로 막았는가'를 노드별로 판정할 수 있다.
    """
    cfg = Config(mode="ours", seed=seed, n_nonfire_deaths=n_inject, nonfire_gate=False, **LEGACY)
    eng = Engine(cfg)
    for _ in eng.stream():
        pass
    return set(eng.verifier.confirmed)


def run_one(seed, n_inject, variant_ov=None):
    cfg = Config(mode="ours", seed=seed, n_nonfire_deaths=n_inject,
                 **{**LEGACY, **(variant_ov or {})})
    eng = Engine(cfg)
    t_final = 0.0
    for snap in eng.stream():
        t_final = snap["t"]
    s = eng.summarize()
    conf_or = _confirmed_with_orgate(seed, n_inject)

    deaths_map = dict(eng.estimator.deaths)          # id -> (x, y, t_est)  (estimator가 실제로 쓴 값)
    confirmed = set(eng.verifier.confirmed)
    n0 = np.array(cfg.direction(), dtype=float)

    # --- 주입 노드 목록: 실제로 강제 사망이 성립한 것(불에 먼저 타 죽으면 nonfire=False) ---
    inj = []
    for nd in eng.nodes:
        if not nd.nonfire:
            continue
        t_d = float(nd.death_t)
        T_loc = float(eng.fire.temp_at(nd.pos, t_d))
        front = np.array(eng.fire.front_pos(t_d), dtype=float)
        dist_front = float((np.array(nd.pos, dtype=float) - front) @ n0)   # +면 전선 앞(미연소)
        rep = float(eng.net.rep_peak.get(nd.id, cfg.ambient))
        # 누수 경로 진단(읽기 전용): 분기③은 accepted 이웃 <min_samples 면 residual을 못 구해 '관대 채택'.
        #  - n_acc_nbrs_at_death: 이 노드보다 먼저 확정된 이웃 수(확정 시점 residual 가용성의 대리지표)
        #  - resid_final_s: 최종 accepted 집합 기준 residual(확정 시점 값이 아님 — 사후 진단용)
        t_est = deaths_map.get(nd.id, (None, None, t_d))[2]
        n_acc_nbrs = sum(1 for j in eng.net.neighbors.get(nd.id, [])
                         if j in eng.verifier.accepted and eng.verifier.accepted[j][2] <= t_est)
        resid_fin = eng.verifier._residual(nd.id, nd.pos, t_est)
        # 사망 후엔 보고가 끊겨 rep_peak가 동결되므로, 종료 시점 값 = 확정 시점 값(정확).
        # rep_peak>=warn 이면 #2d 분기①(자기 고온)으로 **무조건 채택**된 것 → 게이트가 손댈 수 없는 죽음.
        self_hot = rep >= cfg.warn_temp
        inj.append({
            "id": nd.id, "pos": nd.pos, "death_t": t_d,
            "local_temp_c": T_loc, "rep_peak_c": rep,
            "self_hot": self_hot,
            "group": classify(T_loc, cfg.warn_temp),
            "confirmed": nd.id in confirmed,
            "confirmed_orgate": nd.id in conf_or,
            "gate_blocked": (nd.id in conf_or) and (nd.id not in confirmed),
            "dist_to_front_m": dist_front,
            "n_acc_nbrs_at_death": n_acc_nbrs,
            "resid_final_s": resid_fin,
        })

    # --- 전부 포함(=엔진 실제 상태) 기준값 ---
    full = refit(cfg, eng.net.neighbors, deaths_map, set(), eng.fire, eng.nodes, t_final)
    dir_full, sp_full, disp_full, _ = full

    # 재적합이 엔진 최종값을 재현하는지 자기검증(추정기 불변 확인)
    check = None
    if s["final_dir_err_deg"] is not None and not math.isnan(dir_full):
        check = abs(round(dir_full, 3) - s["final_dir_err_deg"])

    # --- 그룹 통째 제외 / 노드별 LOO ---
    conf_by_group = {g: {d["id"] for d in inj if d["group"] == g and d["confirmed"]} for g in GROUPS}
    conf_all = set().union(*conf_by_group.values()) if inj else set()

    group_excl = {}
    for g in GROUPS:
        ids = conf_by_group[g]
        if not ids:
            group_excl[g] = None
            continue
        d_e, s_e, p_e, _ = refit(cfg, eng.net.neighbors, deaths_map, ids,
                                 eng.fire, eng.nodes, t_final)
        group_excl[g] = {"n": len(ids),
                         "dir_harm": dir_full - d_e, "speed_harm": sp_full - s_e,
                         "disp_harm": disp_full - p_e,
                         "dir_excl": d_e, "speed_excl": s_e, "disp_excl": p_e}

    if conf_all:
        d_c, s_c, p_c, _ = refit(cfg, eng.net.neighbors, deaths_map, conf_all,
                                 eng.fire, eng.nodes, t_final)
    else:
        d_c, s_c, p_c = dir_full, sp_full, disp_full

    for d in inj:
        if d["confirmed"]:
            d_i, s_i, p_i, _ = refit(cfg, eng.net.neighbors, deaths_map, {d["id"]},
                                     eng.fire, eng.nodes, t_final)
            d["loo_dir_harm_deg"] = dir_full - d_i
            d["loo_speed_harm_pct"] = sp_full - s_i
            d["loo_disp_harm_m"] = disp_full - p_i
        else:
            d["loo_dir_harm_deg"] = None
            d["loo_speed_harm_pct"] = None
            d["loo_disp_harm_m"] = None

    run = {
        "seed": seed, "n_inject": n_inject,
        "n_injected_actual": len(inj),
        "n_confirmed_nonfire": len(conf_all),
        "dir_full": dir_full, "speed_full": sp_full, "disp_full": disp_full,
        "dir_clean": d_c, "speed_clean": s_c, "disp_clean": p_c,
        "group_excl": group_excl,
        "refit_check": check,
        # 기존 지표(비교용, 정의 불변)
        "pollution_scheduled": (len(eng.nonfire_ids & confirmed) / len(eng.nonfire_ids)
                                if eng.nonfire_ids else 0.0),
        "pollution_actual": (len(conf_all) / len(inj)) if inj else 0.0,
        "fp_rate": s["false_positive_rate"],
        "engine_dir_err": s["final_dir_err_deg"],
        "engine_speed_err": s["final_speed_err_pct"],
        # (#2e-2 변이 비교용) 커버리지 비용 추적
        "confirmed_deaths": s["confirmed_deaths"],
        "coverage": (len(eng.estimator.per_node) / len(deaths_map)) if deaths_map else 0.0,
        "delivery_rate": s["final_delivery_rate"],
    }
    return run, inj


# ---------------- 집계 유틸 ----------------
def ms(vals):
    v = np.array([x for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x))],
                 dtype=float)
    if v.size == 0:
        return None, None, 0
    return round(float(v.mean()), 4), round(float(v.std()), 4), int(v.size)


def write_csv(path, rows):
    if not rows:
        print(f"  [csv] {path} — 행 없음(건너뜀)")
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fields = list(rows[0].keys())
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  [csv] {path} ({len(rows)} rows)")


def _font():
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
    return plt


# ---------------- 회귀(세기 0) 확인 ----------------
def regression_check():
    """n_nonfire_deaths=0 이면 기존 baseline과 완전히 동일해야 한다."""
    a = Config(mode="ours", seed=42, **LEGACY)
    b = Config(mode="ours", seed=42, n_nonfire_deaths=0, **LEGACY)
    out = []
    for cfg in (a, b):
        eng = Engine(cfg)
        for _ in eng.stream():
            pass
        out.append(eng.summarize())
    same = out[0] == out[1]
    print(f"  세기0 회귀: baseline == n_nonfire_deaths=0 → {same}")
    print(f"    dir={out[0]['final_dir_err_deg']}°  speed={out[0]['final_speed_err_pct']}%  "
          f"delivery={out[0]['final_delivery_rate']}  fp={out[0]['false_positive_rate']}")
    if not same:
        diff = {k: (out[0][k], out[1][k]) for k in out[0] if out[0][k] != out[1][k]}
        print(f"    ★ 불일치: {diff}")
    return same, out[0]


# ---------------- 메인 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--outdir", default=OUTDIR)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))

    print(f"#2e-1 비화재 사망 해악 재측정 — 주입수={COUNTS}, seeds={args.seeds}")
    print(f"  분류: HOT >= warn(60℃) / WARM [50,60) / COOL < 50℃  (Δ={COOL_MARGIN_C}℃, 물리 도출)\n")

    print("== 회귀 확인 ==")
    reg_ok, base = regression_check()
    print()

    all_nodes, all_runs = [], []
    max_check = 0.0
    for n in COUNTS:
        for sd in seeds:
            run, inj = run_one(sd, n)
            all_runs.append(run)
            for d in inj:
                all_nodes.append({
                    "seed": sd, "n_inject": n, "node_id": d["id"],
                    "x": round(d["pos"][0], 3), "y": round(d["pos"][1], 3),
                    "death_t": round(d["death_t"], 3),
                    "local_temp_c": round(d["local_temp_c"], 2),
                    "rep_peak_c": round(d["rep_peak_c"], 2),
                    "group": d["group"],
                    "self_hot": int(d["self_hot"]),
                    "confirmed": int(d["confirmed"]),
                    "confirmed_orgate": int(d["confirmed_orgate"]),
                    "gate_blocked": int(d["gate_blocked"]),
                    "dist_to_front_m": round(d["dist_to_front_m"], 3),
                    "n_acc_nbrs_at_death": d["n_acc_nbrs_at_death"],
                    "resid_final_s": (None if d["resid_final_s"] is None
                                      else round(d["resid_final_s"], 3)),
                    "loo_dir_harm_deg": (None if d["loo_dir_harm_deg"] is None
                                         else round(d["loo_dir_harm_deg"], 4)),
                    "loo_speed_harm_pct": (None if d["loo_speed_harm_pct"] is None
                                           else round(d["loo_speed_harm_pct"], 4)),
                    "loo_disp_harm_m": (None if d["loo_disp_harm_m"] is None
                                        else round(d["loo_disp_harm_m"], 4)),
                })
            if run["refit_check"] is not None:
                max_check = max(max_check, run["refit_check"])
        print(f"  [주입 {n}개] {len(seeds)} seeds 완료")
    print(f"\n  반사실 재적합 자기검증: 엔진 최종 방향오차와 최대 편차 = {max_check:.4f}° (0이어야 정상)\n")

    write_csv(os.path.join(args.outdir, "raw_2e1_nonfire_nodes.csv"), all_nodes)

    # --- (주입수 × 그룹) 집계 ---
    rows_g = []
    for n in COUNTS:
        for g in GROUPS:
            sub = [d for d in all_nodes if d["n_inject"] == n and d["group"] == g]
            if not sub:
                continue
            passed = [d for d in sub if d["confirmed"]]
            dm, ds, _ = ms([d["dist_to_front_m"] for d in sub])
            hd, hds, _ = ms([d["loo_dir_harm_deg"] for d in passed])
            hs, hss, _ = ms([d["loo_speed_harm_pct"] for d in passed])
            hp, hps, _ = ms([d["loo_disp_harm_m"] for d in passed])
            rows_g.append({
                "n_inject": n, "group": g, "n_nodes": len(sub), "n_passed": len(passed),
                "pass_rate": round(len(passed) / len(sub), 4),
                "self_hot_share": round(sum(d["self_hot"] for d in sub) / len(sub), 4),
                "orgate_pass_rate": round(sum(d["confirmed_orgate"] for d in sub) / len(sub), 4),
                "gate_blocked_n": sum(d["gate_blocked"] for d in sub),
                "dist_to_front_m_mean": dm, "dist_to_front_m_std": ds,
                "loo_dir_harm_deg_mean": hd, "loo_dir_harm_deg_std": hds,
                "loo_speed_harm_pct_mean": hs, "loo_speed_harm_pct_std": hss,
                "loo_disp_harm_m_mean": hp, "loo_disp_harm_m_std": hps,
            })
    write_csv(os.path.join(args.outdir, "summary_2e1_group.csv"), rows_g)

    # --- ★ 그룹 전체 집계 (COOL 통과율 헤드라인) ---
    rows_o = []
    for g in GROUPS:
        sub = [d for d in all_nodes if d["group"] == g]
        if not sub:
            continue
        passed = [d for d in sub if d["confirmed"]]
        tm, tstd, _ = ms([d["local_temp_c"] for d in sub])
        rm, rstd, _ = ms([d["rep_peak_c"] for d in sub])
        dm, ds, _ = ms([d["dist_to_front_m"] for d in sub])
        hd, hds, _ = ms([d["loo_dir_harm_deg"] for d in passed])
        hs, hss, _ = ms([d["loo_speed_harm_pct"] for d in passed])
        hp, hps, _ = ms([d["loo_disp_harm_m"] for d in passed])
        rows_o.append({
            "group": g, "n_nodes": len(sub), "n_passed": len(passed),
            "pass_rate": round(len(passed) / len(sub), 4),
            "share_of_all": round(len(sub) / len(all_nodes), 4),
            # 진단: 왜 통과/차단됐나
            "self_hot_share": round(sum(d["self_hot"] for d in sub) / len(sub), 4),
            "orgate_pass_rate": round(sum(d["confirmed_orgate"] for d in sub) / len(sub), 4),
            "gate_blocked_n": sum(d["gate_blocked"] for d in sub),
            "gate_blocked_rate": round(sum(d["gate_blocked"] for d in sub) / len(sub), 4),
            # 통과분 중 '확정 시점에 residual 표본부족(<3)이라 관대 채택됐을' 비율 = 분기③ 누수 경로
            "passed_lenient_share": (round(sum(1 for d in passed if d["n_acc_nbrs_at_death"] < 3)
                                           / len(passed), 4) if passed else None),
            "passed_resid_final_s_mean": ms([d["resid_final_s"] for d in passed])[0],
            "local_temp_c_mean": tm, "local_temp_c_std": tstd,
            "rep_peak_c_mean": rm, "rep_peak_c_std": rstd,
            "dist_to_front_m_mean": dm, "dist_to_front_m_std": ds,
            "loo_dir_harm_deg_mean": hd, "loo_dir_harm_deg_std": hds,
            "loo_speed_harm_pct_mean": hs, "loo_speed_harm_pct_std": hss,
            "loo_disp_harm_m_mean": hp, "loo_disp_harm_m_std": hps,
        })
    write_csv(os.path.join(args.outdir, "summary_2e1_group_overall.csv"), rows_o)

    # --- (주입수 × 그룹) 통째 제외 해악 ---
    rows_x = []
    for n in COUNTS:
        for g in GROUPS:
            sub = [r["group_excl"][g] for r in all_runs
                   if r["n_inject"] == n and r["group_excl"].get(g)]
            if not sub:
                continue
            hd, hds, k = ms([x["dir_harm"] for x in sub])
            hs, hss, _ = ms([x["speed_harm"] for x in sub])
            hp, hps, _ = ms([x["disp_harm"] for x in sub])
            rows_x.append({
                "n_inject": n, "group": g, "n_seeds_with_group": k,
                "group_excl_dir_harm_deg_mean": hd, "group_excl_dir_harm_deg_std": hds,
                "group_excl_speed_harm_pct_mean": hs, "group_excl_speed_harm_pct_std": hss,
                "group_excl_disp_harm_m_mean": hp, "group_excl_disp_harm_m_std": hps,
            })
    write_csv(os.path.join(args.outdir, "summary_2e1_groupexcl.csv"), rows_x)

    # --- 주입수별 해악 스케일 ---
    rows_s = []
    for n in COUNTS:
        sub = [r for r in all_runs if r["n_inject"] == n]
        rec = {"n_inject": n, "n_seeds": len(sub),
               "pct_of_16_nodes": round(n / 16 * 100, 1)}
        for key, lbl in (("dir", "dir_err_deg"), ("speed", "speed_err_pct"), ("disp", "disp_m")):
            f_m, f_s, _ = ms([r[f"{key}_full"] for r in sub])
            c_m, c_s, _ = ms([r[f"{key}_clean"] for r in sub])
            rec[f"{lbl}_full_mean"] = f_m
            rec[f"{lbl}_full_std"] = f_s
            rec[f"{lbl}_clean_mean"] = c_m
            rec[f"{lbl}_clean_std"] = c_s
            rec[f"{lbl}_harm_mean"] = (None if (f_m is None or c_m is None) else round(f_m - c_m, 4))
        for g in GROUPS:
            gx = [r["group_excl"][g] for r in sub if r["group_excl"].get(g)]
            m, sdv, k = ms([x["dir_harm"] for x in gx])
            rec[f"dir_harm_{g}_mean"] = m
            rec[f"dir_harm_{g}_seeds"] = k
        pm, ps, _ = ms([r["pollution_actual"] for r in sub])
        rec["pollution_actual_mean"] = pm
        rec["pollution_scheduled_mean"], _, _ = ms([r["pollution_scheduled"] for r in sub])
        rec["fp_rate_mean"], _, _ = ms([r["fp_rate"] for r in sub])
        rows_s.append(rec)
    write_csv(os.path.join(args.outdir, "summary_2e1_scale.csv"), rows_s)

    # ---------------- 곡선 ----------------
    plt = _font()
    xs = [r["n_inject"] for r in rows_s]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    for key, lab, col, mk in (("full", "포함(현재 방어 통과분 그대로)", "#c0392b", "o"),
                              ("clean", "오라클: 비화재 전부 제외", "#2980b9", "s")):
        ys = [r[f"dir_err_deg_{key}_mean"] for r in rows_s]
        es = [r[f"dir_err_deg_{key}_std"] or 0 for r in rows_s]
        ax.errorbar(xs, ys, yerr=es, marker=mk, capsize=4, lw=2, color=col, label=lab)
    ax.axvspan(0.8, 2.2, color="#27ae60", alpha=0.12)
    ax.annotate("현실적 범위(1~2개)", xy=(1.5, ax.get_ylim()[1] * 0.92),
                ha="center", fontsize=9, color="#1e8449")
    ax.annotate("8개 = 16노드의 50%\n(적대적 스트레스)", xy=(8, ax.get_ylim()[1] * 0.55),
                ha="right", fontsize=9, color="#7f8c8d")
    ax.set_xlabel("비화재 사망 주입 수 (16노드 중)")
    ax.set_ylabel("방향오차 (°)")
    # 한글 폰트(Malgun Gothic)에 U+2212가 없어 제목엔 ASCII 하이픈을 쓴다(두부 글자 방지).
    ax.set_title("#2e-1 비화재 사망 해악 스케일 (해악 = 포함 - 오라클 제외)", fontsize=11)
    ax.set_xticks(xs)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)
    fig.tight_layout()
    p = os.path.join(args.outdir, "curve_2e1_harm_scale.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    print(f"  [png] {p}")

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.2))
    gl = [r["group"] for r in rows_o]
    cols = {"COOL": "#2980b9", "WARM": "#f39c12", "HOT": "#c0392b"}
    axes[0].bar(gl, [r["pass_rate"] for r in rows_o], color=[cols[g] for g in gl])
    for i, r in enumerate(rows_o):
        axes[0].text(i, r["pass_rate"] + 0.02, f"{r['pass_rate']*100:.0f}%\n(n={r['n_nodes']})",
                     ha="center", fontsize=9)
    axes[0].set_ylim(0, 1.15)
    axes[0].set_ylabel("교차검증 통과율(=화재사망 오분류)")
    axes[0].set_title("(a) 그룹별 통과율 — 낮을수록 방어됨", fontsize=10)
    axes[0].grid(True, axis="y", alpha=0.3)
    axes[1].bar(gl, [r["loo_dir_harm_deg_mean"] or 0 for r in rows_o],
                yerr=[r["loo_dir_harm_deg_std"] or 0 for r in rows_o],
                capsize=4, color=[cols[g] for g in gl])
    axes[1].axhline(0, color="k", lw=0.8)
    axes[1].set_ylabel("노드 1개당 방향오차 해악 (°)")
    axes[1].set_title("(b) 통과한 노드 1개의 실제 해악(LOO)", fontsize=10)
    axes[1].grid(True, axis="y", alpha=0.3)
    fig.suptitle("#2e-1 찬/뜨거운 구역 비화재 사망: 통과율 vs 실제 해악", fontsize=11)
    fig.tight_layout()
    p = os.path.join(args.outdir, "curve_2e1_group_passrate.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    print(f"  [png] {p}")

    # ---------------- 콘솔 요약 ----------------
    print("\n" + "=" * 78)
    print("★ 헤드라인 — 그룹별 통과율 (사용자 요청: COOL 통과율을 가장 크게)")
    print("=" * 78)
    for r in rows_o:
        mark = "  ← ★ 안전 주장의 핵심 근거" if r["group"] == "COOL" else ""
        print(f"  {r['group']:5s}  n={r['n_nodes']:4d}  통과율 {r['pass_rate']*100:6.1f}%"
              f"  (통과 {r['n_passed']}개)  [OR게이트 {r['orgate_pass_rate']*100:5.1f}% → "
              f"#2d가 막은 수 {r['gate_blocked_n']}, 자기고온(분기①) {r['self_hot_share']*100:5.1f}%]{mark}")
    cool = next((r for r in rows_o if r["group"] == "COOL"), None)
    if cool:
        if cool["pass_rate"] > 0.5:
            print(f"\n  ⚠ COOL 통과율 {cool['pass_rate']*100:.1f}% > 50% → **방어 누수**. "
                  f"'위험한 찬-구역은 방어된다'는 주장 성립 안 함.")
        elif cool["pass_rate"] > 0.2:
            print(f"\n  ⚠ COOL 통과율 {cool['pass_rate']*100:.1f}% — 부분 누수. 완전 방어 아님.")
        else:
            print(f"\n  ✓ COOL 통과율 {cool['pass_rate']*100:.1f}% — 찬-구역 비화재는 대체로 방어됨.")

    print("\n그룹별 상세 (전체 집계)")
    print(f"  {'그룹':5s} {'통과율':>7s} {'국소온도℃':>10s} {'전선거리m':>10s} "
          f"{'LOO방향해악°':>13s} {'LOO속도해악%':>13s} {'LOO변위해악m':>13s}")
    for r in rows_o:
        print(f"  {r['group']:5s} {r['pass_rate']*100:6.1f}% {r['local_temp_c_mean']:10.1f} "
              f"{r['dist_to_front_m_mean']:10.2f} "
              f"{(r['loo_dir_harm_deg_mean'] if r['loo_dir_harm_deg_mean'] is not None else float('nan')):13.3f} "
              f"{(r['loo_speed_harm_pct_mean'] if r['loo_speed_harm_pct_mean'] is not None else float('nan')):13.3f} "
              f"{(r['loo_disp_harm_m_mean'] if r['loo_disp_harm_m_mean'] is not None else float('nan')):13.3f}")

    print("\n누수 경로 진단 (통과한 노드 기준)")
    print(f"  {'그룹':5s} {'자기고온(분기①)':>14s} {'관대채택(분기③,표본<3)':>22s} {'최종평면 residual s':>19s}")
    for r in rows_o:
        pl = r["passed_lenient_share"]
        rf = r["passed_resid_final_s_mean"]
        print(f"  {r['group']:5s} {r['self_hot_share']*100:13.1f}% "
              f"{(pl * 100 if pl is not None else float('nan')):21.1f}% "
              f"{(rf if rf is not None else float('nan')):19.2f}")

    print("\n주입 개수별 해악 스케일  (해악 = 포함 − 오라클전부제외)")
    print(f"  {'주입':>4s} {'%of16':>6s} {'방향(포함)':>11s} {'방향(clean)':>12s} {'방향해악':>9s} "
          f"{'속도해악%':>10s} {'변위해악m':>10s} {'오염률':>7s}")
    for r in rows_s:
        print(f"  {r['n_inject']:4d} {r['pct_of_16_nodes']:5.1f}% "
              f"{r['dir_err_deg_full_mean']:11.2f} {r['dir_err_deg_clean_mean']:12.2f} "
              f"{r['dir_err_deg_harm_mean']:9.2f} {r['speed_err_pct_harm_mean']:10.2f} "
              f"{r['disp_m_harm_mean']:10.2f} {r['pollution_actual_mean']*100:6.1f}%")

    print("\n(a)통과율·(b)해악 가설 검정")
    hot = next((r for r in rows_o if r["group"] == "HOT"), None)
    if cool and hot:
        h1 = cool["pass_rate"] < hot["pass_rate"]
        ch = cool["loo_dir_harm_deg_mean"]
        hh = hot["loo_dir_harm_deg_mean"]
        h2 = (ch is not None and hh is not None and ch > hh)
        print(f"  가설1 'COOL 통과율 < HOT 통과율' → {h1}  "
              f"(COOL {cool['pass_rate']*100:.1f}% vs HOT {hot['pass_rate']*100:.1f}%)")
        print(f"  가설2 '통과 시 COOL 해악 > HOT 해악' → {h2}  "
              f"(COOL {ch}° vs HOT {hh}°)")
        if not h1:
            print("  ★ 가설1 반증 — 찬-구역이 방어된다는 주장은 이 측정으로 뒷받침되지 않음. 그대로 보고할 것.")
        if not h2:
            print("  ★ 가설2 반증 — 뜨거운-구역이 무해하다는 주장은 이 측정으로 뒷받침되지 않음. 그대로 보고할 것.")
    print(f"\n  세기0 회귀 통과: {reg_ok}   반사실 재적합 편차: {max_check:.4f}°")
    print("\n완료. results/stress/ 에 CSV·PNG 저장.")


if __name__ == "__main__":
    main()
