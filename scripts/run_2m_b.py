"""run_2m_b.py — 2.M §1-4 · 분기③의 **초기 표본 문제** 측정.

코드를 읽어 확인한 사실(추정 아님):
  `Verifier._residual`은 `accepted`(이미 화재사망으로 **확정된**) 이웃만 모아 평면을 적합한다.
  `len(acc) < cfg.min_samples`(=3)면 `None`을 돌려주고 → `_sample_poor` → Fix A → **제외**.
  ⇒ 화재 **초기**에는 accepted가 비어 있으므로 분기③에 들어온 후보가 체계적으로 제외된다.
  ⇒ 그리고 `min_samples=3`은 평면 3파라미터라 **DOF=0** — §1-1(a)가 지적한 바로 그 구간이고,
     **기하(공선) 검사는 아예 없다** — 3점이 한 줄이면 쓰레기 평면에서 residual이 나온다.

여기서는 그 대가를 잰다: 초기 제외 건수 / 첫 방향 추정 시각 / 분기③ 적합의 표본수·공선성 분포.
결론 문장 없음.
"""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import numpy as np
from sim.config import Config
from sim.engine import Engine
from sim.adequacy import local_adequacy

SCEN = [("S1", {}), ("S2a_10", {"wind_noise_deg": 10.0}),
        ("S11_nonfire4", {"n_nonfire_deaths": 4}),
        ("S11_nonfire8", {"n_nonfire_deaths": 8})]


def run(name, ov, seed, strict=True):
    cfg = Config(mode="ours", seed=seed, nonfire_strict_gate=strict, **ov)
    eng = Engine(cfg)
    first_dir_t = None
    n_conf_at = []
    for snap in eng.stream():
        if first_dir_t is None and snap["est"] and snap["est"].get("dir") is not None:
            first_dir_t = snap["t"]
        n_conf_at.append((snap["t"], len(eng.estimator.deaths)))
    v = eng.verifier
    strict_rej = [r for r in v.sample_poor_log if r["by"] == "strict"]
    # 분기③ residual 적합의 표본수·공선성 (사후 재구성: accepted 장부 기준)
    acc = v.accepted
    geo = []
    for uid in list(v.confirmed) + list(v.excluded_nonfire):
        nb = [acc[j] for j in v.neighbors.get(uid, []) if j in acc]
        if len(nb) >= cfg.min_samples:
            rec = local_adequacy([(x, y) for x, y, _t in nb], [t for _x, _y, t in nb],
                                 cfg.spacing_m)
            geo.append((len(nb), rec["s2"], rec["grade"]))
    return {"first_dir_t": first_dir_t, "n_confirmed": len(eng.estimator.deaths),
            "n_excluded": len(v.excluded_nonfire), "n_strict_rej": len(strict_rej),
            "geo": geo, "first_death_t": min((t for t in
                        (nd.death_t for nd in eng.nodes if nd.death_t is not None)), default=None)}


if __name__ == "__main__":
    seeds = list(range(1, 31))
    print("=" * 100)
    print("2.M §1-4 · 분기③ 초기 표본 문제")
    print("=" * 100)
    print(f"  min_samples={Config().min_samples} (평면 3파라미터 → 이 값에서 DOF=0)")
    print("  Fix A: residual 표본 부족 → 제외. 초기에는 accepted가 비어 있다.\n")
    rows = []
    print(f"  {'시나리오':16s} {'게이트':8s} {'첫사망':>8s} {'첫방향':>8s} {'지연':>7s} "
          f"{'확정':>6s} {'제외':>6s} {'strict제외':>10s}")
    for name, ov in SCEN:
        for strict in (True, False):
            rs = [run(name, ov, sd, strict) for sd in seeds]
            fd = [r["first_death_t"] for r in rs if r["first_death_t"] is not None]
            fv = [r["first_dir_t"] for r in rs if r["first_dir_t"] is not None]
            lag = [r["first_dir_t"] - r["first_death_t"] for r in rs
                   if r["first_dir_t"] is not None and r["first_death_t"] is not None]
            rows.append({"scenario": name, "strict_gate": int(strict),
                         "first_death_t": round(float(np.mean(fd)), 2) if fd else None,
                         "first_dir_t": round(float(np.mean(fv)), 2) if fv else None,
                         "lag_s": round(float(np.mean(lag)), 2) if lag else None,
                         "n_confirmed": round(float(np.mean([r["n_confirmed"] for r in rs])), 2),
                         "n_excluded": round(float(np.mean([r["n_excluded"] for r in rs])), 2),
                         "n_strict_rej": round(float(np.mean([r["n_strict_rej"] for r in rs])), 2),
                         "n_dir_valid": len(fv)})
            r = rows[-1]
            print(f"  {name:16s} {('FixA' if strict else '레거시'):8s} "
                  f"{(r['first_death_t'] or 0):8.2f} {(r['first_dir_t'] or 0):8.2f} "
                  f"{(r['lag_s'] or 0):7.2f} {r['n_confirmed']:6.2f} {r['n_excluded']:6.2f} "
                  f"{r['n_strict_rej']:10.2f}")
    p = os.path.join("results", "stress", "summary_2m_b_branch3.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"\n  [csv] {p}")

    # 분기③ 적합의 표본수·공선성 분포
    print("\n" + "=" * 100)
    print("★ 분기③ residual 평면적합의 표본수·기하 (같은 adequacy 도구를 적용해본 것)")
    print("=" * 100)
    allgeo = []
    for name, ov in SCEN:
        for sd in seeds[:10]:
            allgeo += run(name, ov, sd, True)["geo"]
    if allgeo:
        ns = [g[0] for g in allgeo]
        s2 = [g[1] for g in allgeo if g[1] is not None]
        from collections import Counter
        print(f"  적합 건수 {len(allgeo)}")
        print(f"  표본수 분포: {dict(sorted(Counter(ns).items()))}   ← 3이면 DOF=0")
        print(f"  n=3 비율: {sum(1 for n in ns if n == 3)/len(ns)*100:.1f} %")
        if s2:
            print(f"  s₂ 중앙값 {np.median(s2):.4f} · 최소 {min(s2):.4f} · "
                  f"s₂<0.1(거의 공선) 비율 {sum(1 for x in s2 if x < 0.1)/len(s2)*100:.1f} %")
        print(f"  등급 분포: {dict(Counter(g[2] for g in allgeo))}")
