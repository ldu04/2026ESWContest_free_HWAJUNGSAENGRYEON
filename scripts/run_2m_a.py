"""run_2m_a.py — 2.M §1-3 · 표본 적정성 진단의 **판별력 시험**.

기준의 유도는 `docs/유도_표본적정성_진단기준.md`에 **이 스크립트를 쓰기 전에** 적고 커밋했다.
여기서는 그 기준을 **그대로** 적용해 재고, 결과를 보고 임계를 고치지 않는다(p-해킹 금지).

★ 통과 조건(지시서 §1-3) — 둘 다 만족해야 판별력이다
  · flank W10 (per_node 20~60 %, 방향오차 82~86°) → DEGRADED 또는 INSUFFICIENT
  · head  W10 (per_node 87 %,    방향오차 1.99°)  → OK
  전부 위험으로 찍으면 쓸모없고, 전부 통과시키면 아무것도 안 한 것이다.

★ 혼동행렬 정의 (미리 고정)
  진실  : 방향오차 > 5°(실용선) = **나쁜 답**
  진단  : DEGRADED 또는 INSUFFICIENT = **위험 표시**
  정탐 TP = 나쁜 답을 위험으로 / 오탐 FP = 좋은 답을 위험으로
  미탐 FN = 나쁜 답을 OK로     / 정기각 TN = 좋은 답을 OK로
  ★ FN(안다면서 틀리는 것)이 가장 나쁜 실패다 — 2.M의 출발점이 그것이었다.

★ 개수 지표 vs 조건수 지표를 **둘 다** 산출해 어느 쪽이 오답을 잘 잡는지 비교한다(지시서 요구).
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
from sim.adequacy import diagnose, PRACTICAL_LINE_DEG, OK, DEGRADED, INSUFFICIENT
from scripts.run_2l_b import ellipse_cfg, plan_tmax
from scripts._par import pmap, n_workers

OUTDIR = os.path.join("results", "stress")

# ── 조건 집합 ──
ELL_W = (10.0, 20.0, 30.0, 50.0)
ELL_D = (30.0, 60.0, 120.0)
ELL_GEOM = ("head", "flank")
ELL_TAU = (0.0, 11.0, 78.5)

FRONTS = [("straight_S1", {}), ("curved_S2a10", {"wind_noise_deg": 10.0}),
          ("curved_S2a20", {"wind_noise_deg": 20.0})]
TAU_SWEEP = (0.0, 11.0, 30.0, 78.5)
JITTER = 0.3

WINDS_MS = (0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0)     # D-052 저풍속 조건
C_SPREAD = 0.10


def _grade_of(d):
    """전역 등급 = per-node 진단을 합친 전역 판정."""
    return d["global"]["grade"]


def job(a):
    kind, key, seed = a
    if kind == "ellipse":
        geom, w, dd, tau = key
        cfg = ellipse_cfg(w, dd, geom=geom, tau=tau, seed=seed,
                          t_max=plan_tmax(w, dd, geom))
    elif kind == "tau":
        front_ov, tau, jit = key
        cfg = Config(mode="ours", seed=seed, sensor_tau_s=tau, sensor_tau_var_pct=jit,
                     sensor_tau_var_dist=("gauss" if jit > 0 else "uniform"),
                     t_max=400.0, **dict(front_ov))
    else:                                              # wind-coupled (D-052)
        u, tau, v, t_max, dt, pdrop = key
        cfg = Config(mode="ours", seed=seed, peak=300.0, sensor_tau_s=tau, speed_true=v,
                     burn_scale_m=10.0, t_max=t_max, dt=dt, p_dropout=pdrop)

    eng = Engine(cfg)
    for _ in eng.stream():
        pass

    est_dir = eng.estimator.dir_global
    diag = diagnose(eng.estimator, cfg)

    # 진실 라벨 — 곡선 전선에서는 국소 참 법선 평균 대비(2.L §4와 같은 기준)
    err = None
    if est_dir is not None:
        if kind == "ellipse":
            dv = []
            for nd in eng.nodes:
                if nd.is_sink or nd.death_t is None:
                    continue
                g = eng.fire._ellipse_gradT(nd.pos)
                ng = float(np.linalg.norm(g))
                if ng > 1e-12:
                    dv.append(g / ng)
            if dv:
                m = np.mean(dv, axis=0)
                if float(np.linalg.norm(m)) > 1e-9:
                    err = angle_deg(est_dir, tuple(m / np.linalg.norm(m)))
        else:
            err = angle_deg(est_dir, cfg.direction())

    n_ns = sum(1 for nd in eng.nodes if not nd.is_sink)
    return {"dir_err": err, "estimable": int(est_dir is not None),
            "grade": _grade_of(diag), "count_grade": diag["count_grade"],
            "dphi_hat": diag["global"]["dphi_hat_deg"],
            "dphi_stat": diag["global"]["dphi_stat_deg"],
            "dphi_disp": diag["global"]["dphi_disp_deg"],
            "n_local": diag["global"]["n_local"], "n_ok": diag["global"]["n_ok"],
            "per_node_frac": round(diag["global"]["n_local"] / n_ns * 100, 1) if n_ns else None,
            "s2_med": (round(float(np.median([r["s2"] for r in diag["local"].values()
                                              if r["s2"] is not None])), 4)
                       if any(r["s2"] is not None for r in diag["local"].values()) else None)}


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


def confusion(rows, grade_key):
    """진실(오차>5°) vs 진단(위험 표시)의 혼동행렬.

    ★ 방향을 아예 못 낸 셀(estimable=0)은 **이미 정직하게 실패**한 것이므로 제외한다.
      진단의 목적은 '답을 냈는데 틀린 것'을 잡는 것이기 때문. 제외 수는 따로 보고한다.
    """
    tp = fp = fn = tn = 0
    skipped = 0
    for r in rows:
        if not r["estimable"] or r["dir_err"] is None:
            skipped += 1
            continue
        bad = r["dir_err"] > PRACTICAL_LINE_DEG
        flagged = r[grade_key] in (DEGRADED, INSUFFICIENT)
        if bad and flagged:
            tp += 1
        elif not bad and flagged:
            fp += 1
        elif bad and not flagged:
            fn += 1
        else:
            tn += 1
    n = tp + fp + fn + tn
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "n": n, "skipped_unestimable": skipped,
            "recall": round(tp / (tp + fn), 3) if (tp + fn) else None,
            "precision": round(tp / (tp + fp), 3) if (tp + fp) else None,
            "fn_rate": round(fn / n, 3) if n else None}


def print_confusion(title, c):
    print(f"\n  ── {title} ──")
    print(f"    {'':14s} {'진단=위험':>10s} {'진단=OK':>10s}")
    print(f"    {'실제 나쁜 답':14s} {c['TP']:10d} {c['FN']:10d}  ← FN이 '안다면서 틀리는' 실패")
    print(f"    {'실제 좋은 답':14s} {c['FP']:10d} {c['TN']:10d}")
    print(f"    n={c['n']}  재현율(나쁜 답 잡은 비율)={c['recall']}  "
          f"정밀도={c['precision']}  FN비율={c['fn_rate']}")
    if c["skipped_unestimable"]:
        print(f"    (추정불가라 제외한 셀 {c['skipped_unestimable']}개 — 이미 정직하게 실패한 경우)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))
    W = args.workers or n_workers()

    print("=" * 108)
    print("2.M §1-3 · 표본 적정성 진단 판별력 시험")
    print("=" * 108)
    print(f"  기준 출처: docs/유도_표본적정성_진단기준.md (구현 전 커밋 0d03c98)")
    print(f"  실용선 {PRACTICAL_LINE_DEG:.0f}° · 시드 {args.seeds} · 워커 {W}\n")

    keys_e = [("ellipse", (g, w, d, t), None) for g in ELL_GEOM for w in ELL_W
              for d in ELL_D for t in ELL_TAU]
    keys_t = [("tau", (tuple(ov.items()), t, j), None)
              for _n, ov in FRONTS for t in TAU_SWEEP for j in (0.0, JITTER)]
    # D-052 조건 재구성(같은 관계식·같은 dt 보정)
    from scripts.run_2k_e import tau_of, plan_time, p_dropout_for
    c0 = Config()
    keys_w = []
    for u in WINDS_MS:
        v = C_SPREAD * u
        tau = tau_of(u)
        tm, dt = plan_time(v, tau, c0)
        keys_w.append(("wind", (u, tau, v, tm, dt, p_dropout_for(c0.p_dropout, dt)), None))

    allkeys = keys_e + keys_t + keys_w
    jobs = [(k[0], k[1], sd) for k in allkeys for sd in seeds]
    print(f"  스윕 {len(jobs)} 런 (타원 {len(keys_e)} + τ {len(keys_t)} + 바람 {len(keys_w)} 조건)",
          flush=True)
    res = pmap(job, jobs, workers=W, label="2m-a")

    rows, idx = [], 0
    for kind, key, _ in allkeys:
        rs = res[idx:idx + len(seeds)]
        idx += len(seeds)
        if kind == "ellipse":
            g, w, d, t = key
            label = f"타원[{g}] W{w:.0f} d{d:.0f} τ{t:.0f}"
            meta = {"set": "ellipse", "geom": g, "wind_kmh": w, "ignition_d_m": d, "tau_s": t}
        elif kind == "tau":
            ov, t, j = key
            nm = next(n for n, o in FRONTS if tuple(o.items()) == ov)
            label = f"{nm} τ{t:.0f} {'지터' if j else '균일'}"
            meta = {"set": "tau", "front": nm, "tau_s": t, "jitter": j}
        else:
            u, tau, v, tm, dt, _p = key
            label = f"바람 u={u} τ{tau:.1f} v{v:.3f}"
            meta = {"set": "wind", "wind_u": u, "tau_s": round(tau, 2), "v_spread": round(v, 4)}
        de = [r["dir_err"] for r in rs if r["dir_err"] is not None]
        for i, r in enumerate(rs):
            rows.append({"label": label, **meta, "seed": seeds[i], **r})
    write_csv(os.path.join(args.outdir, "raw_2m_a_adequacy.csv"), rows)

    # ── 조건별 요약 ──
    agg = {}
    for r in rows:
        agg.setdefault(r["label"], []).append(r)
    summary = []
    for lab, rs in agg.items():
        de = [r["dir_err"] for r in rs if r["dir_err"] is not None]
        flagged = sum(1 for r in rs if r["grade"] in (DEGRADED, INSUFFICIENT))
        summary.append({"label": lab, "set": rs[0]["set"], "n_seeds": len(rs),
                        "dir_err_mean": round(float(np.mean(de)), 3) if de else None,
                        "estimable_pct": round(float(np.mean([r["estimable"] for r in rs])) * 100, 1),
                        "per_node_frac": round(float(np.mean([r["per_node_frac"] for r in rs
                                                              if r["per_node_frac"] is not None])), 1)
                        if any(r["per_node_frac"] is not None for r in rs) else None,
                        "flagged_pct": round(flagged / len(rs) * 100, 1),
                        "dphi_hat_mean": round(float(np.mean([r["dphi_hat"] for r in rs
                                                              if r["dphi_hat"] is not None])), 3)
                        if any(r["dphi_hat"] is not None for r in rs) else None,
                        "s2_med": round(float(np.mean([r["s2_med"] for r in rs
                                                       if r["s2_med"] is not None])), 4)
                        if any(r["s2_med"] is not None for r in rs) else None,
                        "count_flagged_pct": round(
                            sum(1 for r in rs if r["count_grade"] in (DEGRADED, INSUFFICIENT))
                            / len(rs) * 100, 1)})
    write_csv(os.path.join(args.outdir, "summary_2m_a_adequacy.csv"), summary)

    # ══════ ★ 통과 조건 (지시서 §1-3) ══════
    print("\n" + "=" * 108)
    print("★★ 통과 조건 — flank W10은 잡히고 head W10은 통과해야 한다 (둘 다여야 판별력)")
    print("=" * 108)
    print(f"  {'조건':30s} {'방향오차':>9s} {'per_node':>9s} {'δφ̂':>9s} {'s₂':>8s} "
          f"{'위험표시':>8s} {'판정':>8s}")
    ok_all = True
    for lab_pat, want_flag in ((("타원[flank] W10",), True), (("타원[head] W10",), False)):
        for s in summary:
            if not any(s["label"].startswith(p) for p in lab_pat):
                continue
            got = s["flagged_pct"] >= 50.0
            good = (got == want_flag)
            ok_all &= good
            print(f"  {s['label']:30s} {(s['dir_err_mean'] if s['dir_err_mean'] is not None else float('nan')):9.2f} "
                  f"{(s['per_node_frac'] or 0):8.0f}% "
                  f"{(s['dphi_hat_mean'] if s['dphi_hat_mean'] is not None else float('nan')):9.2f} "
                  f"{(s['s2_med'] if s['s2_med'] is not None else float('nan')):8.4f} "
                  f"{s['flagged_pct']:7.0f}% {('통과' if good else '★실패'):>8s}")
    print(f"\n  ⇒ 통과 조건 전체: {'충족' if ok_all else '★미충족'}")

    # ══════ 혼동행렬 ══════
    print("\n" + "=" * 108)
    print("★ 혼동행렬 — 진실(방향오차>5°) vs 진단(위험 표시)")
    print("=" * 108)
    for name, sel in (("전체", rows),
                      ("타원(2.L §4)", [r for r in rows if r["set"] == "ellipse"]),
                      ("τ 스윕(2.J/2.K)", [r for r in rows if r["set"] == "tau"]),
                      ("저풍속(D-052)", [r for r in rows if r["set"] == "wind"])):
        print_confusion(f"{name} · 조건수 지표(δφ̂)", confusion(sel, "grade"))
        print_confusion(f"{name} · 개수 지표(비교용)", confusion(sel, "count_grade"))

    # ══════ 예측 대조 ══════
    print("\n" + "=" * 108)
    print("★ 사전등록 예측 대조 (해석 없이 일치/불일치만)")
    print("=" * 108)
    ce, cc = confusion(rows, "grade"), confusion(rows, "count_grade")
    m1 = (ce["fn_rate"] or 1) < (cc["fn_rate"] or 1)
    print(f"  M1 공선성 지표가 개수 지표보다 오답을 잘 잡는다 → "
          f"{'일치' if m1 else '★불일치'}  (FN비율 δφ̂ {ce['fn_rate']} vs 개수 {cc['fn_rate']})")
    print(f"  M2 flank 잡고 head 통과 → {'일치' if ok_all else '★불일치'}")
    curv = [r for r in rows if r["set"] == "tau" and r["front"] == "curved_S2a20"
            and r["tau_s"] == 0.0 and r["jitter"] == 0.0]
    if curv:
        cm = confusion(curv, "grade")
        print(f"  M3 곡률이 만든 오차는 진단이 놓친다 (S2a20 τ=0 균일) → "
              f"TP={cm['TP']} FN={cm['FN']} → "
              f"{'일치(놓침)' if cm['FN'] > cm['TP'] else '★불일치(잡음)'}")


if __name__ == "__main__":
    main()
