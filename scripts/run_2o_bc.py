"""run_2o_bc.py — 2O §2(P1−P2 런타임 신호) + §3(예측 재정식화).

§2 — `eta_disagreement = |P1 − P2|` 는 **정답 없이 런타임에 계산**되는 유일한 신뢰도 신호다.
  임계(측정 전 고정, 지시서 §2-3):
      < 30 s      AGREE
      30 ~ 300 s  DIVERGENT
      > 300 s     BROKEN
  근거: 정상 구간 최대 4.19 s와 파탄 구간 최소 522 s 사이에 **두 자릿수 공백**이 있어
        그 사이 어느 값을 잡아도 같은 분류가 나온다. 30 s는 자릿수의 중간이며
        **결과가 이 값의 정확한 위치에 민감하지 않다는 것**이 정당성이다(성능이 아니라).
  검증: 등급 × 실제오차 교차표. ★AGREE인데 오차가 큰 칸이 있으면 이 신호는 위험 쪽으로
        눈이 먼 것이므로 신뢰도 지표로 쓸 수 없다.
  또: 게이트 D집합(삭제)과 BROKEN 구간의 **겹침** — 겹치면 두 장치가 같은 걸 잡는 것.

§3 — 재정식화된 사전등록 검정 (지시서 §3-4, [식 유도])
      Δd_i     = d_i(지터) − d_i(균일)      ← 같은 시드, 노드별 지연의 지터 유발 변화
      σ_Δd     = std(Δd_i)                  ← 분모. 지터 조건에서 구조적으로 0이 아니다
      ΔETA_rms = rms( ETA_지터 − ETA_균일 ) ← 같은 질의점
      R        = ΔETA_rms / σ_Δd
  예측 R ≈ 1      (앵커가 관측 1개라 평균화 없음)
  반증 R ≈ 1/√n_j (앵커도 평균화를 받음)
  ★같은 단위(초)라 비가 아니라 **무차원 비율 1**과 비교한다 — §3-3의 분모 폭발 문제가 재발하지 않는다.

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
from sim.eta_paths import node_grades, gated_allow, predict_p1, predict_p2
from scripts.run_2e3_diagnose import TrueFront, ETA_DISTS
from scripts.run_2l_b import ellipse_cfg, plan_tmax
from scripts._par import pmap, n_workers

AGREE_S, BROKEN_S = 30.0, 300.0          # ★측정 전 고정
TAUS = (0.0, 11.0, 78.5)
CONDS = ([("ellipse", ("flank", 10.0, d)) for d in (30.0, 60.0, 120.0)]
         + [("ellipse", ("head", w, d)) for w in (10.0, 20.0, 30.0, 50.0)
            for d in (30.0, 60.0, 120.0)]
         + [("line", ("straight_S1", {})),
            ("line", ("curved_S2a10", {"wind_noise_deg": 10.0})),
            ("line", ("curved_S2a20", {"wind_noise_deg": 20.0}))])
JIT_TAUS = (11.0, 30.0, 78.5)
FRONTS = [("straight_S1", {}), ("curved_S2a10", {"wind_noise_deg": 10.0}),
          ("curved_S2a20", {"wind_noise_deg": 20.0})]


def grade_of(dis):
    if dis < AGREE_S:
        return "AGREE"
    return "DIVERGENT" if dis <= BROKEN_S else "BROKEN"


# ───────────────────────── §2 ─────────────────────────
def job_b(a):
    kind, key, tau, seed = a
    if kind == "ellipse":
        g, w, d = key
        cfg = ellipse_cfg(w, d, geom=g, tau=tau, seed=seed, t_max=plan_tmax(w, d, g))
    else:
        _n, ov = key
        cfg = Config(mode="ours", seed=seed, sensor_tau_s=tau, t_max=400.0, **dict(ov))
    eng = Engine(cfg)
    tf = None
    cells = {}          # (grade, deleted) -> [errs]
    for snap in eng.stream():
        t = snap["t"]
        if tf is None and kind != "ellipse":
            tf = TrueFront(eng.fire)
        if not eng.estimator.per_node or abs(t - round(t)) > 1e-9:
            continue
        allow = gated_allow(node_grades(eng.estimator, cfg))
        front = np.array(eng.fire.front_pos(t), float)
        nv = np.array(eng.fire._dir_at(t) if kind != "ellipse" else cfg.direction(), float)
        for dd in ETA_DISTS:
            p = front + nv * dd
            ta = (eng.fire.T_true(p) if kind == "ellipse" else (tf.arrival(p) if tf else None))
            if ta is None or not np.isfinite(ta):
                continue
            v1, _i = predict_p1(eng.estimator, p)
            v2, _j = predict_p2(eng.estimator, p)
            if v1 is None or v2 is None:
                continue
            gv, _ = predict_p1(eng.estimator, p, allow)
            key2 = (grade_of(abs(v1 - v2)), gv is None)
            cells.setdefault(key2, []).append(abs(v1 - ta))
    return {f"{g}|{int(d)}": (len(v), float(np.mean(v)), float(np.percentile(v, 95)))
            for (g, d), v in cells.items()}


# ───────────────────────── §3 ─────────────────────────
def job_c(a):
    ov, tau, seed = a

    def run(jit):
        cfg = Config(mode="ours", seed=seed, sensor_tau_s=tau, sensor_tau_var_pct=jit,
                     sensor_tau_var_dist=("gauss" if jit > 0 else "uniform"),
                     t_max=400.0, **dict(ov))
        eng = Engine(cfg)
        tf = None
        eta = {}
        for snap in eng.stream():
            t = snap["t"]
            if tf is None:
                tf = TrueFront(eng.fire)
            if not eng.estimator.per_node or abs(t - round(t)) > 1e-9:
                continue
            front = np.array(eng.fire.front_pos(t), float)
            nv = np.array(eng.fire._dir_at(t), float)
            for dd in ETA_DISTS:
                p = front + nv * dd
                v, _i = predict_p1(eng.estimator, p)
                if v is not None:
                    eta[(round(t, 3), dd)] = v
        # 노드별 지연 d_i = 사망시각 − 참 도착시각
        d = {}
        for nd in eng.nodes:
            if nd.is_sink or nd.death_t is None:
                continue
            ta = tf.arrival(nd.pos)
            if ta is not None and np.isfinite(ta):
                d[nd.id] = nd.death_t - ta
        npn = float(np.mean([len(eng.estimator.per_node)])) if eng.estimator.per_node else None
        return eta, d, npn

    e_u, d_u, n_u = run(0.0)
    e_j, d_j, _n = run(0.3)
    common_d = set(d_u) & set(d_j)
    dd = [d_j[i] - d_u[i] for i in common_d]
    common_e = set(e_u) & set(e_j)
    de = [e_j[k] - e_u[k] for k in common_e]
    return {"sigma_dd": (float(np.std(dd)) if len(dd) > 1 else None),
            "deta_rms": (float(np.sqrt(np.mean(np.square(de)))) if de else None),
            "n_d": len(dd), "n_e": len(de), "n_pernode": n_u}


def main():
    seeds = list(range(1, 11))

    # ═══════════ §2 ═══════════
    jobs = [(k, key, t, sd) for k, key in CONDS for t in TAUS for sd in seeds]
    print(f"2O §2 · P1−P2 신뢰도 신호 ({len(jobs)} 런) — 임계 {AGREE_S:.0f}/{BROKEN_S:.0f} s 고정\n",
          flush=True)
    res = pmap(job_b, jobs, workers=n_workers(), label="2o-b")
    agg = {}
    for r in res:
        for k, (n, mae, p95) in r.items():
            a = agg.setdefault(k, [0, 0.0, []])
            a[0] += n
            a[1] += mae * n
            a[2].append(p95)
    print("=" * 96)
    print("★ 교차표 — |P1−P2| 등급 × 실제 ETA 오차 (게이트 삭제 여부 함께)")
    print("=" * 96)
    print(f"  {'등급':11s} {'게이트':8s} {'건수':>9s} {'MAE(s)':>11s} {'P95(s)':>11s}")
    for g in ("AGREE", "DIVERGENT", "BROKEN"):
        for dele in (0, 1):
            k = f"{g}|{dele}"
            if k not in agg:
                continue
            n, s, p95 = agg[k]
            print(f"  {g:11s} {('삭제됨' if dele else '유지'):8s} {n:9d} "
                  f"{s / n:11.2f} {float(np.mean(p95)):11.2f}")
    tot = sum(v[0] for v in agg.values())
    print(f"\n  전체 {tot}건")
    ag = sum(v[0] for k, v in agg.items() if k.startswith("AGREE"))
    ag_mae = sum(v[1] for k, v in agg.items() if k.startswith("AGREE")) / max(ag, 1)
    br = sum(v[0] for k, v in agg.items() if k.startswith("BROKEN"))
    br_mae = (sum(v[1] for k, v in agg.items() if k.startswith("BROKEN")) / br) if br else None
    print(f"  ★AGREE({ag}건) MAE = {ag_mae:.2f} s   ← 크면 이 신호는 위험 쪽으로 눈이 멀었다는 뜻")
    if br:
        print(f"   BROKEN({br}건) MAE = {br_mae:.2f} s")
    # 게이트 D집합과 BROKEN의 겹침
    d_tot = sum(v[0] for k, v in agg.items() if k.endswith("|1"))
    d_broken = agg.get("BROKEN|1", [0])[0]
    if d_tot:
        print(f"\n  ★게이트 삭제({d_tot}건) 중 BROKEN 등급: {d_broken}건 "
              f"({d_broken / d_tot * 100:.1f} %)")
        print(f"   BROKEN({br}건) 중 게이트 삭제: "
              f"{(d_broken / br * 100 if br else 0):.1f} %  "
              f"← 높으면 두 장치가 같은 것을 잡는다")

    # ═══════════ §3 ═══════════
    jobs = [(ov, t, sd) for _n, ov in FRONTS for t in JIT_TAUS for sd in seeds]
    print(f"\n2O §3 · 예측 재정식화 R = ΔETA_rms / σ_Δd  ({len(jobs)} 런)\n", flush=True)
    res = pmap(job_c, jobs, workers=n_workers(), label="2o-c")
    rows, idx = [], 0
    print("=" * 96)
    print("★ 재정식화 검정 — 예측 R ≈ 1 (앵커 평균화 없음) / 반증 R ≈ 1/√n_j")
    print("=" * 96)
    print(f"  {'전선':16s} {'τ':>6s} {'σ_Δd(s)':>10s} {'ΔETA_rms(s)':>13s} {'★R':>8s} "
          f"{'n_j':>6s} {'1/√n_j':>8s}")
    for _n, ov in FRONTS:
        nm = next(n for n, o in FRONTS if o == ov)
        for t in JIT_TAUS:
            rs = res[idx:idx + len(seeds)]
            idx += len(seeds)
            g = lambda k: [r[k] for r in rs if r.get(k) is not None]
            sd = float(np.mean(g("sigma_dd"))) if g("sigma_dd") else None
            de = float(np.mean(g("deta_rms"))) if g("deta_rms") else None
            nj = float(np.mean(g("n_pernode"))) if g("n_pernode") else None
            R = (de / sd) if (sd and sd > 1e-12 and de is not None) else None
            rows.append({"front": nm, "tau_s": t, "sigma_dd": sd, "deta_rms": de,
                         "R": R, "n_pernode": nj})
            f = lambda v, w=10: (f"{v:{w}.4f}" if v is not None else "-".rjust(w))
            print(f"  {nm:16s} {t:6.1f} {f(sd)} {f(de, 13)} {f(R, 8)} "
                  f"{(f'{nj:6.1f}' if nj else '     -')} "
                  f"{(f'{1 / np.sqrt(nj):8.3f}' if nj else '       -')}")
    p = os.path.join("results", "stress", "summary_2o_c_prediction.csv")
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n  [csv] {p}")
    Rs = [r["R"] for r in rows if r["R"] is not None]
    njm = float(np.mean([r["n_pernode"] for r in rows if r["n_pernode"]]))
    if Rs:
        print(f"\n  전체 R 평균 {np.mean(Rs):.3f} (범위 {min(Rs):.3f}~{max(Rs):.3f}) · "
              f"1/√n_j = {1 / np.sqrt(njm):.3f}")
        near1 = sum(1 for x in Rs if 0.5 <= x <= 2.0)
        nearr = sum(1 for x in Rs if x <= 0.5)
        print(f"  R∈[0.5,2] (예측 ≈1 쪽) {near1}/{len(Rs)} · "
              f"R≤0.5 (반증 ≈1/√n_j 쪽) {nearr}/{len(Rs)}")


if __name__ == "__main__":
    main()
