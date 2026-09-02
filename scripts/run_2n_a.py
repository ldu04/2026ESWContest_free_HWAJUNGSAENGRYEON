"""run_2n_a.py — 2.N §1 · **채점 기준(ground truth) 확인**.

★ 착수 시 코드를 읽어 확인한 사실 — **지시서의 전제를 정정해야 한다.**
  지시서는 "정답을 전체 확산 방향(장축)으로 놓고 채점하고 있을 것"이라고 가정했으나,
  `run_2l_b.py` / `run_2m_a.py` / `run_2m_c.py` 의 타원 채점부는 **이미 국소 법선 기준**이다:

      err = angle_deg(est_dir,  mean_over_dead_nodes( ∇T/|∇T| ))

  즉 flank W10 d30의 **81.81°는 전역 축 대비가 아니라 국소 법선 대비 값**이다.
  ⇒ [추가-A]가 요구한 "기본 창 8 s + 국소 법선 기준" 조건은 **이미 측정돼 있었고 82°였다.**

★ 그러나 그 국소 법선 기준에는 **집계 불일치**가 있다(이번에 새로 발견):
      추정치 `dir_global` = **per_node(국소 적합 성공) 노드들만**의 속도가중 평균
      정답      (기존)    = **전 사망 노드**의 참 법선 단순 평균
  flank d30은 per_node가 **60 %**뿐이라, 추정에 기여하지 않은 40 %가 정답에는 들어간다.
  **서로 다른 노드 집합을 비교**하고 있었던 것이다. 이건 가설과 별개의 실제 채점 결함이다.

★ 그래서 기준 4개를 나란히 낸다 (결론 문장 없음, 표만)
  R1 전역 축            : cfg.direction()                      — 장축(지시서가 가정한 기준)
  R2 전 사망노드 평균   : 기존 기준(2.L §4·2.M 전부 이 값)
  R3 ★기여 노드 정합   : per_node 노드만, **같은 속도가중**으로 참 법선 평균 — 집계를 맞춘 것
  R4 per-node 개별      : 각 국소 적합 방향 vs **그 노드의** 참 법선. 중앙값·분포
                          → "추정기가 국소 법선을 제대로 재고 있는가"에 대한 가장 직접적인 답
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
from scripts.run_2l_b import ellipse_cfg, plan_tmax
from scripts.run_2e3_diagnose import TrueFront
from scripts._par import pmap, n_workers

OUTDIR = os.path.join("results", "stress")

# [추가-A] 결정적 셀 + 최소 대조군. 전 조건 재채점은 이 결과를 보고 정한다.
CELLS = [
    ("ellipse", ("flank", 10.0, 30.0), "★결정적: 타원 flank W10 d30"),
    ("ellipse", ("flank", 10.0, 60.0), "타원 flank W10 d60"),
    ("ellipse", ("head", 10.0, 30.0), "대조: 타원 head W10 d30"),
    ("ellipse", ("head", 50.0, 30.0), "대조: 타원 head W50 d30"),
    ("line", ("straight_S1", {}), "대조: 직선 S1 (R1=R2=R3이어야 함)"),
    ("line", ("curved_S2a20", {"wind_noise_deg": 20.0}), "대조: 곡선 S2a20"),
]


def true_normal(eng, pos, kind, tf=None):
    """그 노드 위치의 **참 전선 법선**(단위벡터).

    ★ 초판은 직선/요동 전선에서 `cfg.direction()`(명목 θ)을 돌려줬는데, 이는 **참 법선이 아니다**.
      요동 전선의 법선은 시간에 따라 도는 `fire._dir_at(t)`이고, 한 노드가 겪는 법선은
      **그 노드에 전선이 도착한 시각의** 법선이다. 명목 θ와는 다르다.
      → 이 오류 때문에 S2a10/S2a20의 R2·R3가 R1과 항상 같게 나왔다(정정).
    """
    if kind == "ellipse":
        g = eng.fire._ellipse_gradT(pos)
        n = float(np.linalg.norm(g))
        return (g / n) if n > 1e-12 else None
    ta = tf.arrival(pos) if tf is not None else None
    return np.array(eng.fire._dir_at(ta if ta is not None else 0.0), dtype=float)


def job(a):
    kind, key, seed = a
    if kind == "ellipse":
        geom, w, d = key
        cfg = ellipse_cfg(w, d, geom=geom, tau=0.0, seed=seed, t_max=plan_tmax(w, d, geom))
    else:
        _n, ov = key
        cfg = Config(mode="ours", seed=seed, sensor_tau_s=0.0, **dict(ov))
    eng = Engine(cfg)
    eng.cfg = cfg
    for _ in eng.stream():
        pass

    tf = None if kind == "ellipse" else TrueFront(eng.fire)
    est = eng.estimator
    est_dir = est.dir_global
    out = {"estimable": int(est_dir is not None), "n_pernode": len(est.per_node),
           "n_deaths": len(est.deaths),
           "R1": None, "R2": None, "R3": None, "R4_med": None, "R4_max": None,
           "R5_simple": None, "max_weight_pct": None, "n_R4": 0}
    if est_dir is None:
        return out

    # R1 — 전역 축
    out["R1"] = angle_deg(est_dir, cfg.direction())

    # R2 — 전 사망 노드의 참 법선 **단순** 평균 (기존 기준)
    dv = []
    for nd in eng.nodes:
        if nd.is_sink or nd.death_t is None:
            continue
        u = true_normal(eng, nd.pos, kind, tf)
        if u is not None:
            dv.append(u)
    if dv:
        m = np.mean(dv, axis=0)
        if float(np.linalg.norm(m)) > 1e-9:
            out["R2"] = angle_deg(est_dir, tuple(m / np.linalg.norm(m)))

    # R3 — ★기여 노드만, dir_global과 **같은 속도가중**으로 참 법선 평균
    #   estimator._fit_global: acc += speed_i · dir_i  → 정답도 같은 가중으로 모아야 정합이다.
    acc = np.zeros(2)
    for i, v in est.per_node.items():
        u = true_normal(eng, v["pos"], kind, tf)
        if u is not None:
            acc += float(v["speed"]) * np.asarray(u, dtype=float)
    if float(np.linalg.norm(acc)) > 1e-9:
        out["R3"] = angle_deg(est_dir, tuple(acc / np.linalg.norm(acc)))

    # R5 — ★속도가중 없이 **단순평균**했을 때. `_fit_global`은 speed=1/|∇T| 로 가중하는데,
    #   퇴화 적합은 |∇T|→0 이라 speed→∞ 가 되어 **가장 나쁜 적합이 합산을 지배**할 수 있다.
    sm = np.zeros(2)
    for i, v in est.per_node.items():
        sm += np.asarray(v["dir"], dtype=float)
    if float(np.linalg.norm(sm)) > 1e-9 and float(np.linalg.norm(acc)) > 1e-9:
        out["R5_simple"] = angle_deg(tuple(sm / np.linalg.norm(sm)), tuple(acc / np.linalg.norm(acc)))
    sps = [v["speed"] for v in est.per_node.values()]
    out["max_weight_pct"] = round(max(sps) / sum(sps) * 100, 1) if sps else None

    # R4 — per-node 개별: 국소 적합 방향 vs 그 노드의 참 법선
    errs = []
    for i, v in est.per_node.items():
        u = true_normal(eng, v["pos"], kind, tf)
        if u is not None:
            errs.append(angle_deg(v["dir"], tuple(u)))
    if errs:
        out["R4_med"] = float(np.median(errs))
        out["R4_max"] = float(np.max(errs))
        out["n_R4"] = len(errs)
    return out


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=15)
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))
    W = args.workers or n_workers()

    print("=" * 112)
    print("2.N §1 · 채점 기준 확인 — 배포 기본 창 8 s, τ=0")
    print("=" * 112)
    print("  ★ 지시서 전제 정정: 타원 채점은 **이미 국소 법선 기준**이었다(전역 축 아님).")
    print("     flank W10 d30의 81.81°는 국소 법선 대비 값이다.")
    print("  ★ 새로 발견한 결함: 추정치는 per_node 노드만의 가중평균인데")
    print("     정답(R2)은 전 사망 노드 평균 — **서로 다른 노드 집합을 비교**하고 있었다.\n")
    print(f"  기준 R1 전역 축 / R2 전 사망노드 평균(기존) / R3 기여노드 정합 / R4 per-node 개별")
    print(f"  시드 {args.seeds} · 워커 {W}\n")

    jobs = [(k, key, sd) for k, key, _lab in CELLS for sd in seeds]
    res = pmap(job, jobs, workers=W, label="2n-a")

    rows, idx = [], 0
    for kind, key, lab in CELLS:
        rs = res[idx:idx + len(seeds)]
        idx += len(seeds)
        rec = {"label": lab, "kind": kind, "n_seeds": len(seeds)}
        for k in ("R1", "R2", "R3", "R4_med", "R4_max", "R5_simple", "max_weight_pct"):
            v = [r[k] for r in rs if r[k] is not None]
            rec[k] = round(float(np.mean(v)), 3) if v else None
            rec[k + "_std"] = round(float(np.std(v)), 3) if v else None
        rec["estimable_pct"] = round(float(np.mean([r["estimable"] for r in rs])) * 100, 1)
        rec["n_pernode"] = round(float(np.mean([r["n_pernode"] for r in rs])), 2)
        rec["n_deaths"] = round(float(np.mean([r["n_deaths"] for r in rs])), 2)
        rec["pernode_frac"] = (round(rec["n_pernode"] / rec["n_deaths"] * 100, 1)
                               if rec["n_deaths"] else None)
        rows.append(rec)
        for i, r in enumerate(rs):
            pass
    write_csv(os.path.join(args.outdir, "summary_2n_a_groundtruth.csv"), rows)
    write_csv(os.path.join(args.outdir, "raw_2n_a_groundtruth.csv"),
              [{"label": lab, "seed": seeds[i], **r}
               for (kind, key, lab), off in zip(CELLS, range(0, len(res), len(seeds)))
               for i, r in enumerate(res[off:off + len(seeds)])])

    print("\n" + "=" * 112)
    print("★ 네 기준으로 각각 채점 (방향오차 °, 평균±std)")
    print("=" * 112)
    print(f"  {'조건':32s} {'R1 전역축':>12s} {'R2 전사망(기존)':>14s} "
          f"{'R3 기여정합':>13s} {'R4중앙':>8s} {'R4최대':>8s} {'R5 단순평균':>11s} "
          f"{'최대가중':>8s} {'per_node':>9s}")
    f = lambda r, k: (f"{r[k]:8.2f}±{r[k+'_std']:<5.2f}" if r[k] is not None else f"{'-':>14s}")
    for r in rows:
        g = lambda k, w=8: (f"{r[k]:{w}.2f}" if r[k] is not None else f"{'-':>{w}s}")
        print(f"  {r['label']:32s} {g('R1',12)} {g('R2',14)} {g('R3',13)} "
              f"{g('R4_med')} {g('R4_max')} {g('R5_simple',11)} "
              f"{(f'{r[chr(109)+chr(97)+chr(120)+chr(95)+chr(119)+chr(101)+chr(105)+chr(103)+chr(104)+chr(116)+chr(95)+chr(112)+chr(99)+chr(116)]:7.1f}%' if r['max_weight_pct'] is not None else '       -')} "
              f"{(r['pernode_frac'] or 0):8.0f}%")

    # ── 결합 명세 대조 ──
    print("\n" + "=" * 112)
    print("★ 결합 명세 대조 (지시서 §1-1) — 기준을 바꿨을 때 무엇이 얼마나 움직이나")
    print("=" * 112)
    print(f"  {'조건':32s} {'R2→R3 변화':>13s} {'R1→R2 변화':>13s}  판정")
    for r in rows:
        d23 = (r["R3"] - r["R2"]) if (r["R3"] is not None and r["R2"] is not None) else None
        d12 = (r["R2"] - r["R1"]) if (r["R2"] is not None and r["R1"] is not None) else None
        note = ""
        if r["label"].startswith("대조: 직선"):
            note = ("R1=R2=R3 확인" if (d23 is not None and abs(d23) < 1e-6
                                        and d12 is not None and abs(d12) < 1e-6)
                    else "★직선인데 기준이 갈린다 = 구현 오류 의심")
        print(f"  {r['label']:32s} {(f'{d23:+.2f}' if d23 is not None else '-'):>13s} "
              f"{(f'{d12:+.2f}' if d12 is not None else '-'):>13s}  {note}")

    print("\n" + "=" * 112)
    print("★ 가설 판정 재료 (해석 없이 수치만)")
    print("=" * 112)
    dec = next((r for r in rows if r["label"].startswith("★결정적")), None)
    if dec:
        print(f"  결정적 셀 [기본 창 8 s + 국소 법선 기준]:")
        print(f"    R2(기존 국소 기준)   = {dec['R2']}°")
        print(f"    R3(기여 노드 정합)   = {dec['R3']}°")
        print(f"    R4(per-node 중앙값)  = {dec['R4_med']}°   최대 {dec['R4_max']}°")
        print(f"    R1(전역 축)          = {dec['R1']}°")
        print(f"    per_node 비율        = {dec['pernode_frac']}%")
        print()
        print("  [추가-A]의 판정 기준:")
        print("    · 여전히 82° 근처면 → 채점 아님, 굶주림 확정(가설 반증)")
        print("    · 작게 나오면 → 두 원인 공존, 기여도 분해 필요")


if __name__ == "__main__":
    main()
