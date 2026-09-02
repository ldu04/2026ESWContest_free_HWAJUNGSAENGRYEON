"""run_night_experiments.py — 추정기 강건성 합성 실험 (a)~(f). 2026-08-31 야간.

★ 모든 산출물은 합성이다. CSV 행마다 fake=1 을 찍는다. 실측으로 인용하지 말 것.
★ sim/estimator.py 는 수정하지 않는다. 동결된 추정기를 그대로 돌린다.

돌리는 법:  python scripts/run_night_experiments.py
산출물   :  results/night/*.csv , results/night/summary.json
"""
from __future__ import annotations

import itertools
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from night_robustness import (ALERT_HORIZON, _center, ORIGIN, OUTDIR, RADIO, SPACING,  # noqa: E402
                              V_FRONT, ang_deg, ang_err, estimate, lead_times,
                              make_cfg, neighbors, positions, summarize,
                              true_death_times, truth_center_deg, write_csv)

# ★ 표준출력/표준오류 고정 — cp949 콘솔에서 문자 하나로 죽지 않게, 튕겨도 줄이 남게.
#   근거: docs/n07_사망시험_판정_20260901.md §7
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

RNG = np.random.default_rng(20260831)
POS = positions()          # ★ 실측 좌표(deploy_config.json)
CENTER = _center(POS)     # 외곽 중점 — 참값 ① 의 기준
NB = neighbors(POS)
CFG = make_cfg()
TT = true_death_times(POS)


# ── 참값 세 정의 ─────────────────────────────────────────────────────────
def truth_local_normal_deg(pos=POS, origin=ORIGIN):
    """② 참 필드의 국소 법선 r-hat 을 16노드에 대해 벡터평균."""
    vs = []
    for p in pos.values():
        dx, dy = p[0] - origin[0], p[1] - origin[1]
        n = math.hypot(dx, dy)
        vs.append((dx / n, dy / n))
    return ang_deg((float(np.mean([v[0] for v in vs])), float(np.mean([v[1] for v in vs]))))


def truth_plane_fit_deg(tt=None, pos=POS):
    """③ 참 사망시각 (x,y,t) 의 전역 단일 평면 최소제곱 기울기."""
    tt = TT if tt is None else tt
    ids = sorted(pos)
    A = np.array([[pos[i][0], pos[i][1], 1.0] for i in ids])
    b = np.array([tt[i] for i in ids])
    c, *_ = np.linalg.lstsq(A, b, rcond=None)
    return ang_deg((float(c[0]), float(c[1])))


TRUTHS = {"center": truth_center_deg(),
          "local_normal": truth_local_normal_deg(),
          "plane_fit": truth_plane_fit_deg()}


def errs(g, loc):
    """추정기 두 출력 x 참값 세 정의 = 6개 오차."""
    out = {}
    for tname, tv in TRUTHS.items():
        out["global_vs_" + tname] = ang_err(g, tv) if g is not None else float("nan")
        out["local_vs_" + tname] = ang_err(loc, tv) if loc is not None else float("nan")
    return out


def run_once(deaths):
    g, loc, est, nl = estimate(deaths, POS, CFG, NB)
    e = errs(g, loc)
    e.update(dir_global_deg=g, dir_local_deg=loc, n_local=nl,
             speed_est=est.get("speed"), n_deaths=len(deaths))
    return e


BASE_FIELDS = ["dir_global_deg", "dir_local_deg", "n_local", "speed_est", "n_deaths"] + \
              [f"{a}_vs_{b}" for a in ("global", "local") for b in TRUTHS]

SUMMARY: dict = {"_주의": "전부 합성(fake=1). 실측 아님.",
                 "참값_정의": {k: round(v, 4) for k, v in TRUTHS.items()},
                 "격자": {"rows": 4, "cols": 4, "spacing_m": SPACING, "radio_range_m": RADIO},
                 "전선": {"origin_m": list(ORIGIN), "v_m_s": V_FRONT,
                          "alert_horizon_s": round(ALERT_HORIZON, 1)}}


# ── 0. 기하학적 하한 — 잡음 0에서도 오차는 0이 아니다 ────────────────────
def exp_floor():
    r = run_once(dict(TT))
    rows = []
    for est_name, est_val in (("global(속도가중)", r["dir_global_deg"]),
                              ("local(국소평균)", r["dir_local_deg"])):
        for tname, tv in TRUTHS.items():
            rows.append({"estimator": est_name, "estimator_deg": round(est_val, 4),
                         "truth": tname, "truth_deg": round(tv, 4),
                         "floor_err_deg": round(ang_err(est_val, tv), 4)})
    write_csv("exp0_geometric_floor.csv", rows,
              ["estimator", "estimator_deg", "truth", "truth_deg", "floor_err_deg", "fake"])
    SUMMARY["0_기하학적_하한"] = {"추정기_무잡음": {"global": round(r["dir_global_deg"], 4),
                                                    "local": round(r["dir_local_deg"], 4)},
                                  "표": rows}
    return r


# ── (a) 사망시각 지터 σ 스윕 ─────────────────────────────────────────────
def exp_a(n=1000, sigmas=(0.0, 5.0, 12.13, 20.0, 30.0)):
    rows, summ = [], {}
    for s in sigmas:
        acc = {k: [] for k in BASE_FIELDS if k.endswith(tuple(TRUTHS))}
        for k in range(n):
            d = {i: TT[i] + (RNG.normal(0.0, s) if s > 0 else 0.0) for i in TT}
            r = run_once(d)
            r["sigma_s"] = s
            r["rep"] = k
            rows.append(r)
            for kk in acc:
                acc[kk].append(r[kk])
            if s == 0.0:      # 잡음 0 은 결정론이라 1회면 충분
                break
        summ[f"sigma_{s}"] = {kk: {m: round(v, 4) for m, v in summarize(vv).items()}
                              for kk, vv in acc.items()}
    write_csv("expA_jitter.csv", rows, ["sigma_s", "rep"] + BASE_FIELDS + ["fake"])
    SUMMARY["a_사망시각_지터"] = summ
    return summ


# ── (b) 결측 노드 — 전수 조사 ────────────────────────────────────────────
def exp_b(kmax=4):
    """무작위 500회 대신 **전수 조사**를 한다(C(16,1..4)=2516 < 2000). 상위집합이다."""
    ids = sorted(TT)
    rows, summ = [], {}
    for k in range(1, kmax + 1):
        combos = list(itertools.combinations(ids, k))
        recs = []
        for cmb in combos:
            d = {i: TT[i] for i in ids if i not in cmb}
            r = run_once(d)
            r["k_missing"] = k
            r["missing_ids"] = "|".join(str(x) for x in cmb)
            r["missing_labels"] = "|".join("n%02d" % (x + 1) for x in cmb)
            rows.append(r)
            recs.append(r)
        key = "global_vs_center"
        vals = [x[key] for x in recs]
        worst = max(recs, key=lambda x: x[key])
        summ[f"k_{k}"] = {"조합수": len(combos),
                          "분포": {m: round(v, 4) for m, v in summarize(vals).items()},
                          "최악": {"labels": worst["missing_labels"],
                                   "err_deg": round(worst[key], 4)},
                          "최악_상위5": [{"labels": x["missing_labels"],
                                          "err_deg": round(x[key], 4)}
                                         for x in sorted(recs, key=lambda z: -z[key])[:5]]}
    write_csv("expB_missing.csv", rows,
              ["k_missing", "missing_ids", "missing_labels"] + BASE_FIELDS + ["fake"])
    SUMMARY["b_결측_노드"] = summ
    return summ


# ── (c) 동시 사망 ────────────────────────────────────────────────────────
def exp_c(n=500, ms=(2, 3, 4)):
    ids = sorted(TT)
    rows, summ = [], {}
    for m in ms:
        vals = []
        for k in range(n):
            grp = list(RNG.choice(ids, size=m, replace=False))
            tbar = round(float(np.mean([TT[i] for i in grp])))
            d = dict(TT)
            for i in grp:
                d[i] = float(tbar)
            r = run_once(d)
            r["m_simultaneous"] = m
            r["group_labels"] = "|".join("n%02d" % (int(x) + 1) for x in sorted(grp))
            r["rep"] = k
            rows.append(r)
            vals.append(r["global_vs_center"])
        summ[f"m_{m}"] = {m2: round(v, 4) for m2, v in summarize(vals).items()}
    write_csv("expC_simultaneous.csv", rows,
              ["m_simultaneous", "group_labels", "rep"] + BASE_FIELDS + ["fake"])
    SUMMARY["c_동시_사망"] = summ
    return summ


# ── (d) 패킷 유실 ────────────────────────────────────────────────────────
def exp_d(n=500, ps=(0.10, 0.20, 0.30)):
    ids = sorted(TT)
    rows, summ = [], {}
    for p in ps:
        vals, nd, failed = [], [], 0
        for k in range(n):
            keep = [i for i in ids if RNG.random() >= p]
            if len(keep) < 3:
                failed += 1
                continue
            d = {i: TT[i] for i in keep}
            r = run_once(d)
            r["loss_p"] = p
            r["rep"] = k
            rows.append(r)
            vals.append(r["global_vs_center"])
            nd.append(len(keep))
        summ[f"p_{p}"] = {"오차": {m: round(v, 4) for m, v in summarize(vals).items()},
                          "남은_사망_평균": round(float(np.mean(nd)), 2) if nd else None,
                          "추정_불가_횟수": failed}
    write_csv("expD_packetloss.csv", rows, ["loss_p", "rep"] + BASE_FIELDS + ["fake"])
    SUMMARY["d_패킷_유실"] = summ
    return summ


# ── (e) 점화 방향 12방 스윕 ──────────────────────────────────────────────
def exp_e(ndirs=12, sigma=12.13, n=200):
    """점화점을 판 중심에서 같은 거리로 12방향 돌린다. 참값은 방향마다 재계산한다."""
    R = math.hypot(ORIGIN[0] - CENTER[0], ORIGIN[1] - CENTER[1])
    rows, summ = [], {}
    for k in range(ndirs):
        th = 2 * math.pi * k / ndirs
        o = (CENTER[0] + R * math.cos(th), CENTER[1] + R * math.sin(th))
        tt = true_death_times(POS, origin=o)
        t_center = ang_deg((CENTER[0] - o[0], CENTER[1] - o[1]))
        # 잡음 0
        g0, l0, _e, _n = estimate(dict(tt), POS, CFG, NB)
        base = ang_err(g0, t_center)
        vals = []
        for rep in range(n):
            d = {i: tt[i] + RNG.normal(0.0, sigma) for i in tt}
            g, l, _e2, nl = estimate(d, POS, CFG, NB)
            e = ang_err(g, t_center) if g is not None else float("nan")
            vals.append(e)
            rows.append({"dir_index": k, "origin_deg": round(math.degrees(th) % 360, 2),
                         "origin_x": round(o[0], 4), "origin_y": round(o[1], 4),
                         "truth_center_deg": round(t_center, 4),
                         "rep": rep, "sigma_s": sigma,
                         "dir_global_deg": g, "err_deg": e, "n_local": nl})
        summ[f"dir_{k:02d}_{round(math.degrees(th))}deg"] = {
            "점화점": [round(o[0], 4), round(o[1], 4)],
            "참값_deg": round(t_center, 4),
            "무잡음_오차_deg": round(base, 4),
            "잡음_오차": {m: round(v, 4) for m, v in summarize(vals).items()}}
    write_csv("expE_ignition_sweep.csv", rows,
              ["dir_index", "origin_deg", "origin_x", "origin_y", "truth_center_deg",
               "rep", "sigma_s", "dir_global_deg", "err_deg", "n_local", "fake"])
    SUMMARY["e_점화방향_스윕"] = summ
    return summ


# ── (f) ETA 정확도 + 경보 리드타임 ───────────────────────────────────────
def exp_f(n=300, sigmas=(0.0, 12.13, 30.0)):
    rows, summ = [], {}
    for s in sigmas:
        lead_all, eta_all, covered = [], [], []
        reps = 1 if s == 0.0 else n
        for rep in range(reps):
            d = {i: TT[i] + (RNG.normal(0.0, s) if s > 0 else 0.0) for i in TT}
            lead, eta_err = lead_times(d, POS, CFG, NB)
            covered.append(len(lead))
            for j, lt in lead.items():
                lead_all.append(lt)
                rows.append({"sigma_s": s, "rep": rep, "node_label": "n%02d" % (j + 1),
                             "lead_time_s": round(lt, 2),
                             "eta_err_s": round(eta_err.get(j, float("nan")), 2)
                             if j in eta_err else ""})
            for j, ee in eta_err.items():
                eta_all.append(ee)
        summ[f"sigma_{s}"] = {
            "경보_리드타임_s": {m: round(v, 2) for m, v in summarize(lead_all).items()},
            "ETA_오차_s(예측-실제)": {m: round(v, 2) for m, v in summarize(eta_all).items()},
            "ETA_절대오차_s": {m: round(v, 2) for m, v in summarize(np.abs(eta_all)).items()},
            "경보받은_노드수_평균": round(float(np.mean(covered)), 2),
            "설계_alert_horizon_s": round(ALERT_HORIZON, 1)}
    write_csv("expF_eta_leadtime.csv", rows,
              ["sigma_s", "rep", "node_label", "lead_time_s", "eta_err_s", "fake"])
    SUMMARY["f_ETA_와_리드타임"] = summ
    return summ


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    print("[0] 기하학적 하한"); exp_floor()
    print("[a] 사망시각 지터"); exp_a()
    print("[b] 결측 노드(전수)"); exp_b()
    print("[c] 동시 사망"); exp_c()
    print("[d] 패킷 유실"); exp_d()
    print("[e] 점화방향 스윕"); exp_e()
    print("[f] ETA·리드타임"); exp_f()
    p = os.path.join(OUTDIR, "summary.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(SUMMARY, f, ensure_ascii=False, indent=2)
    print("완료 →", p)


if __name__ == "__main__":
    main()
