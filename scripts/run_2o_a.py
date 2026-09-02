"""run_2o_a.py — 2O §1 · ETA 등급 게이트 **분해검정** (U / S / D).

★ 문제의식(지시서): 게이트 전 MAE는 58,527건, 후 MAE는 47,154건에 대한 값이라
  **서로 다른 모집단**이다. 그 비교는 처치효과가 아니라 **선택효과**를 잰다.

분해:
  U 무변화 — 게이트 전후 앵커 동일   → 전후 MAE가 **정확히 같아야** 정상(다르면 구현 버그)
  S 치환   — 앵커가 바뀜             → **같은 질의에 대한 쌍대 비교** ← 진짜 처치효과
  D 삭제   — 유효 앵커 없음          → **게이트 전 이 집합의 MAE** ← 선택효과 진단

★ 판정 규칙은 측정 전에 고정(지시서 §1-3). 결과를 보고 바꾸지 않는다.
★ 사전등록 가설(§1-4): flank의 MAE 상승은 인공물이다
   (a) D의 게이트 전 MAE < flank 전체 MAE(105.21)  ← 쉬운 문제가 지워졌다
   (b) S의 평균 앵커거리가 게이트 후 증가          ← 외삽 연장
   (c) S의 쌍대 악화폭 ≪ 23.46(=128.67−105.21) 또는 개선으로 뒤집힘
   반증: (a)가 반대면 인공물 가설 기각 → 게이트가 실제로 해롭다는 증거.

★ 함께: 앵커거리 분포(전/후)와 corr(|ETA오차|, 앵커거리).
결론 문장 없음.
"""
import csv
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
from sim.eta_paths import node_grades, gated_allow, predict_p1
from scripts.run_2e3_diagnose import TrueFront, ETA_DISTS
from scripts.run_2l_b import ellipse_cfg, plan_tmax
from scripts._par import pmap, n_workers

TAUS = (0.0, 11.0, 78.5)
CONDS = ([("ellipse", ("flank", 10.0, d)) for d in (30.0, 60.0, 120.0)]
         + [("ellipse", ("head", w, d)) for w in (10.0, 20.0, 30.0, 50.0)
            for d in (30.0, 60.0, 120.0)]
         + [("line", ("straight_S1", {})),
            ("line", ("curved_S2a10", {"wind_noise_deg": 10.0})),
            ("line", ("curved_S2a20", {"wind_noise_deg": 20.0}))])


def group_of(lab):
    if "flank" in lab:
        return "flank"
    return "head" if "head" in lab else "line"


def job(a):
    kind, key, tau, seed = a
    if kind == "ellipse":
        g, w, d = key
        cfg = ellipse_cfg(w, d, geom=g, tau=tau, seed=seed, t_max=plan_tmax(w, d, g))
    else:
        _n, ov = key
        cfg = Config(mode="ours", seed=seed, sensor_tau_s=tau, t_max=400.0, **dict(ov))
    eng = Engine(cfg)
    tf = None
    U, Spre, Spost, Dpre, Sdpre, Sdpost, alle, alld = [], [], [], [], [], [], [], []
    for snap in eng.stream():
        t = snap["t"]
        if tf is None and kind != "ellipse":
            tf = TrueFront(eng.fire)
        if not eng.estimator.per_node or abs(t - round(t)) > 1e-9:
            continue
        allow = gated_allow(node_grades(eng.estimator, cfg))
        front = np.array(eng.fire.front_pos(t), float)
        nv = np.array(eng.fire._dir_at(t) if kind != "ellipse" else cfg.direction(), float)
        pn = eng.estimator.per_node
        for dd in ETA_DISTS:
            p = front + nv * dd
            ta = (eng.fire.T_true(p) if kind == "ellipse" else (tf.arrival(p) if tf else None))
            if ta is None or not np.isfinite(ta):
                continue
            v0, i0 = predict_p1(eng.estimator, p)
            v1, i1 = predict_p1(eng.estimator, p, allow)
            if v0 is None:
                continue
            d0 = float(np.linalg.norm(np.asarray(p) - np.asarray(pn[i0]["pos"])))
            alle.append(abs(v0 - ta))
            alld.append(d0)
            if v1 is None:
                Dpre.append(abs(v0 - ta))
            elif i1 == i0:
                U.append(abs(abs(v0 - ta) - abs(v1 - ta)))
            else:
                d1 = float(np.linalg.norm(np.asarray(p) - np.asarray(pn[i1]["pos"])))
                Spre.append(abs(v0 - ta))
                Spost.append(abs(v1 - ta))
                Sdpre.append(d0)
                Sdpost.append(d1)
    m = lambda a: (float(np.mean(a)) if a else None)
    out = {"n_U": len(U), "n_S": len(Spre), "n_D": len(Dpre), "n_all": len(alle),
           "U_maxdiff": (max(U) if U else 0.0),
           "S_e_pre": m(Spre), "S_e_post": m(Spost), "D_e_pre": m(Dpre),
           "S_d_pre": m(Sdpre), "S_d_post": m(Sdpost),
           "all_e": m(alle), "all_d": m(alld)}
    out["corr_err_dist"] = (float(np.corrcoef(alle, alld)[0, 1]) if len(alle) > 2 else None)
    return out


def main():
    seeds = list(range(1, 11))
    jobs = [(k, key, t, sd) for k, key in CONDS for t in TAUS for sd in seeds]
    print(f"2O §1 · 게이트 분해검정 U/S/D ({len(jobs)} 런)\n", flush=True)
    res = pmap(job, jobs, workers=n_workers(), label="2o-a")

    rows, idx = [], 0
    for kind, key in CONDS:
        lab = (f"타원[{key[0]}] W{key[1]:.0f} d{key[2]:.0f}" if kind == "ellipse" else key[0])
        for t in TAUS:
            rs = res[idx:idx + len(seeds)]
            idx += len(seeds)
            g = lambda k: [r[k] for r in rs if r.get(k) is not None]
            rec = {"label": lab, "group": group_of(lab), "tau_s": t}
            for k in ("n_U", "n_S", "n_D", "n_all"):
                rec[k] = sum(r[k] for r in rs)
            for k in ("S_e_pre", "S_e_post", "D_e_pre", "S_d_pre", "S_d_post",
                      "all_e", "all_d", "corr_err_dist"):
                rec[k] = round(float(np.mean(g(k))), 4) if g(k) else None
            rec["U_maxdiff"] = max(r["U_maxdiff"] for r in rs)
            rows.append(rec)

    p = os.path.join("results", "stress", "summary_2o_a_gate_decomp.csv")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  [csv] {p}\n")

    print("=" * 112)
    print("★ 무결성 확인 — U(무변화) 집합은 전후 MAE가 정확히 같아야 한다")
    print("=" * 112)
    mx = max(r["U_maxdiff"] for r in rows)
    print(f"  U 집합 전후 최대 차이 = {mx:.3e}  →  "
          f"{'정상' if mx < 1e-9 else '★구현 버그 의심'}")

    def wavg(sel, k):
        v = [(r[k], r["n_all"]) for r in sel if r[k] is not None]
        return float(np.average([a for a, _ in v], weights=[b for _, b in v])) if v else None

    print("\n" + "=" * 112)
    print("★★ 분해 — 조건군별 (건수는 10시드 합)")
    print("=" * 112)
    print(f"  {'군':6s} {'τ':>5s} {'U':>7s} {'S':>7s} {'D':>7s} "
          f"{'S 전MAE':>9s} {'S 후MAE':>9s} {'S 쌍대Δ':>10s} "
          f"{'D 전MAE':>9s} {'전체MAE':>9s} {'D−전체':>10s}")
    for grp in ("flank", "head", "line"):
        for t in TAUS:
            sel = [r for r in rows if r["group"] == grp and r["tau_s"] == t]
            if not sel:
                continue
            sp, so = wavg(sel, "S_e_pre"), wavg(sel, "S_e_post")
            dp, ae = wavg(sel, "D_e_pre"), wavg(sel, "all_e")
            f = lambda v, w=9: (f"{v:{w}.2f}" if v is not None else "-".rjust(w))
            ds = (f"{so - sp:+10.2f}" if (sp is not None and so is not None) else "-".rjust(10))
            dd = (f"{dp - ae:+10.2f}" if (dp is not None and ae is not None) else "-".rjust(10))
            print(f"  {grp:6s} {t:5.0f} {sum(r['n_U'] for r in sel):7d} "
                  f"{sum(r['n_S'] for r in sel):7d} {sum(r['n_D'] for r in sel):7d} "
                  f"{f(sp)} {f(so)} {ds} {f(dp)} {f(ae)} {dd}")

    print("\n" + "=" * 112)
    print("★ 앵커거리 — S에서 게이트가 외삽을 얼마나 늘리나 + 오차와의 상관")
    print("=" * 112)
    print(f"  {'군':6s} {'τ':>5s} {'S거리 전':>10s} {'S거리 후':>10s} {'Δ':>8s} "
          f"{'전체 거리':>10s} {'corr(|오차|,거리)':>18s}")
    for grp in ("flank", "head", "line"):
        for t in TAUS:
            sel = [r for r in rows if r["group"] == grp and r["tau_s"] == t]
            if not sel:
                continue
            mm = lambda k: (float(np.mean([r[k] for r in sel if r[k] is not None]))
                            if any(r[k] is not None for r in sel) else None)
            a, b = mm("S_d_pre"), mm("S_d_post")
            f = lambda v, w=10: (f"{v:{w}.2f}" if v is not None else "-".rjust(w))
            dl = (f"{b - a:+8.2f}" if (a is not None and b is not None) else "-".rjust(8))
            print(f"  {grp:6s} {t:5.0f} {f(a)} {f(b)} {dl} {f(mm('all_d'))} "
                  f"{f(mm('corr_err_dist'), 18)}")

    print("\n" + "=" * 112)
    print("★ 사전등록 가설 대조 (§1-4, 사후 수정 없음)")
    print("=" * 112)
    fl = [r for r in rows if r["group"] == "flank"]
    dp, ae = wavg(fl, "D_e_pre"), wavg(fl, "all_e")
    sp, so = wavg(fl, "S_e_pre"), wavg(fl, "S_e_post")
    sdp = float(np.mean([r["S_d_pre"] for r in fl if r["S_d_pre"] is not None]))
    sdo = float(np.mean([r["S_d_post"] for r in fl if r["S_d_post"] is not None]))
    print(f"  (a) D의 게이트 전 MAE({dp:.2f}) < flank 전체 MAE({ae:.2f}) ?  → "
          + ("일치 — 쉬운 문제가 지워졌다" if dp < ae
             else "★불일치 — 어려운 문제가 지워졌다 = 인공물 가설 기각"))
    print(f"  (b) S의 앵커거리가 게이트 후 증가 ?  {sdp:.2f} → {sdo:.2f}  → "
          + ("일치" if sdo > sdp else "★불일치"))
    print(f"  (c) S 쌍대 Δ({so - sp:+.2f}) 가 23.46보다 훨씬 작거나 개선 ?  → "
          + ("일치" if (so - sp) < 23.46 else "★불일치"))
    print(f"\n  ★정지 조건(§4): S 쌍대 비교가 악화면 멈추고 보고 → "
          f"S 쌍대 Δ = {so - sp:+.2f} → "
          + ("★악화 = 정지" if so > sp else "개선/중립 = 진행 가능"))


if __name__ == "__main__":
    main()
