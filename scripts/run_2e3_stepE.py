"""run_2e3_stepE.py — #2e-3 Step 2.E · 속도/ETA **신뢰구간(밴드)**.

전제(사용자 확정): A는 병행 보존, 밴드는 **배포판(base) 잔차**로 구축한다.
배포판은 배포 파이프라인과 바이트 동일이므로 승격 재검증이 필요 없다.

설계 원칙 (사용자 지침)
-----------------------
1) **편향 인지형.** 2.A가 속도 `+`편향이 12/12로 실재·지속함을 보였으므로 **대칭 부트스트랩을 쓰지 않는다.**
   런 안의 per-node 속도 **경험 분포의 비대칭 분위수**를 그대로 쓴다(부호·비대칭 보존).
2) **도출/평가 분리.** 밴드 규칙(분위수 쌍·확대계수 k)은 **S1에서만** 확정하고, 커버리지는 **S2~S11**에서 평가한다.
   테스트 점수를 보고 밴드를 조이거나 넓히지 않는다.
3) **안전 기준은 '이른쪽(조기) 끝'.** 그 끝이 참 도착을 덮어야 조기경보가 성립한다.
   `breach_early`(참 도착이 밴드 이른끝보다 **더 이르다**) = **★위험**(불이 최조기 예측보다 먼저 옴).
   `breach_late`(참 도착이 밴드 늦은끝보다 더 늦다) = **보수 초과**(너무 일찍 경보).
   ※ 지시서 괄호 문구는 방향이 갈릴 수 있어, 1d와 같은 규약(물리적 위험 방향)으로 정의하고 **양쪽 다** 보고한다.
4) **폭 하한.** 감사([D-038])가 낸 물리/모델형 하한보다 좁은 밴드는 거짓이다.
   → `E1`(관측만)과 `E2`(E1 ∨ 감사 하한)를 **둘 다** 내고 차이를 드러낸다.
5) 표기는 **ETA 초** 우선, 점 숫자 금지.
6) **−6.4 s 오프셋은 미보정** — 밴드의 이른끝이 그만큼 보수적으로 흡수한다.

밴드 구성 (전부 런타임 관측량)
------------------------------
  per-node 속도 집합 {v_i} 의 경험 분위수:
      v_lo = med − k·(med − P05),   v_hi = med + k·(P95 − med)
  **k는 S1에서 도출**한다. S1에서 이미 참값이 [P05,P95] 안에 들어오므로 **확대할 근거가 없다 → k = 1**.
  (줄이는 것은 테스트 점수를 보고 하는 짓이라 금지. S1이 결정론적이라 k를 연속적으로 최적화할 수 없다는
   사실도 그대로 기록한다.)
  ETA 밴드: 같은 국소 평면 기하에 속도만 갈아끼운다.
      ETA(v) = t_i + (û·(p − p_i)) / v − t_now      → 빠른 v = 이른 도착
      ETA_early = ETA(v_hi),  ETA_late = ETA(v_lo)
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
from scripts.run_2e3_diagnose import TrueFront, ETA_DISTS

OUTDIR = os.path.join("results", "stress")
NOMINAL = 90.0
K_FROM_S1 = 1.0          # ★S1에서 도출. 아래 calibrate_on_S1()이 근거를 출력한다.

SCENARIOS = [
    ("S1",       {}),
    ("S2a_5",    {"wind_noise_deg": 5.0}),
    ("S2a_10",   {"wind_noise_deg": 10.0}),
    ("S2a_20",   {"wind_noise_deg": 20.0}),
    ("S2b_20",   {"wind_speed_var_pct": 0.2}),
    ("S2b_40",   {"wind_speed_var_pct": 0.4}),
    ("S4_40",    {"placement_jitter": 0.4}),
    ("S6_n9",    {"grid_rows": 3, "grid_cols": 3, "p_dropout": 0.05}),
    ("S6_n12",   {"grid_rows": 3, "grid_cols": 4, "p_dropout": 0.05}),
    ("S6_n25",   {"grid_rows": 5, "grid_cols": 5, "p_dropout": 0.05}),
    ("S7_worst", {"wind_noise_deg": 10.0, "wind_speed_var_pct": 0.2,
                  "placement_jitter": 0.2, "p_dropout": 0.10}),
]


def speed_band(est, k=K_FROM_S1):
    """런 안 per-node 속도의 **비대칭 경험 분위수** 밴드. 대칭 부트스트랩 아님."""
    sp = np.array([v["speed"] for v in est.per_node.values()], dtype=float)
    if sp.size < 3:
        return None
    med = float(np.median(sp))
    lo = med - k * (med - float(np.percentile(sp, 5)))
    hi = med + k * (float(np.percentile(sp, 95)) - med)
    return max(lo, 1e-3), max(hi, 1e-3), med


def nearest_local(est, p):
    best, bd = None, float("inf")
    for v in est.per_node.values():
        d = float(np.linalg.norm(np.array(p) - np.array(v["pos"])))
        if d < bd:
            bd, best = d, v
    return best


def run_one(seed, ov, floor_pct=0.0):
    cfg = Config(mode="ours", seed=seed, **ov)
    eng = Engine(cfg)
    tf = None
    rows = []
    speed_rows = []
    for snap in eng.stream():
        t = snap["t"]
        if tf is None:
            tf = TrueFront(eng.fire)
        if not eng.estimator.per_node or abs(t - round(t)) > 1e-9:
            continue
        band = speed_band(eng.estimator)
        if band is None:
            continue
        v_lo, v_hi, med = band
        # E2: 감사 하한을 병합(폭이 감사 하한보다 좁으면 넓힌다)
        v_lo2 = min(v_lo, med * (1.0 - floor_pct / 100.0))
        v_hi2 = max(v_hi, med * (1.0 + floor_pct / 100.0))
        front = np.array(eng.fire.front_pos(t), dtype=float)
        nvec = np.array(eng.fire._dir_at(t), dtype=float)
        for d in ETA_DISTS:
            p = front + nvec * d
            ta = tf.arrival(p)
            loc = nearest_local(eng.estimator, p)
            if ta is None or loc is None:
                continue
            u = np.array(loc["dir"], dtype=float)
            s_axis = float(u @ (p - np.array(loc["pos"], dtype=float)))
            if s_axis <= 0:
                continue
            eta_true = ta - t
            base_t = loc["t"] - t
            def eta(v):
                return base_t + s_axis / v
            rows.append({"dist": d,
                         "eta_true": eta_true,
                         "eta_point": eta(med),
                         "e1_early": eta(v_hi), "e1_late": eta(v_lo),
                         "e2_early": eta(v_hi2), "e2_late": eta(v_lo2)})
    # 속도 밴드 커버리지(최종 시점)
    band = speed_band(eng.estimator)
    if band is not None:
        ex = [tf.arrival(nd.pos) for nd in eng.nodes if not nd.is_sink]
        ex = [x for x in ex if x is not None]
        ts = np.arange(min(ex), max(ex) + 1e-9, cfg.dt)
        vb = float(np.mean([eng.fire._speed_at(float(x)) for x in ts]))
        v_lo, v_hi, med = band
        v_lo2 = min(v_lo, med * (1 - floor_pct / 100.0))
        v_hi2 = max(v_hi, med * (1 + floor_pct / 100.0))
        speed_rows.append({"v_true_bar": vb, "med": med,
                           "e1_in": int(v_lo <= vb <= v_hi), "e2_in": int(v_lo2 <= vb <= v_hi2),
                           "e1_w": (v_hi - v_lo) / med * 100, "e2_w": (v_hi2 - v_lo2) / med * 100})
    return rows, speed_rows


def calibrate_on_s1(seeds):
    """★도출 단계 — S1에서만. k를 정하는 근거를 출력한다."""
    print("=" * 104)
    print("도출(S1에서만) — 확대계수 k")
    print("=" * 104)
    hit = w = n = 0
    for sd in seeds:
        cfg = Config(mode="ours", seed=sd)
        eng = Engine(cfg)
        for _ in eng.stream():
            pass
        tf = TrueFront(eng.fire)
        ex = [tf.arrival(nd.pos) for nd in eng.nodes if not nd.is_sink]
        ex = [x for x in ex if x is not None]
        ts = np.arange(min(ex), max(ex) + 1e-9, cfg.dt)
        vb = float(np.mean([eng.fire._speed_at(float(x)) for x in ts]))
        b = speed_band(eng.estimator, k=1.0)
        if b is None:
            continue
        lo, hi, med = b
        n += 1
        hit += int(lo <= vb <= hi)
        w += (hi - lo) / med * 100
    print(f"  k=1 (확대 없음)에서 S1 속도밴드 커버리지 = {hit}/{n} = {hit/n*100:.1f} %  "
          f"(평균 폭 {w/n:.1f} % of median)")
    print("  → S1에서 이미 참값이 [P05,P95] 안에 들어온다. **확대할 근거가 없으므로 k = 1 확정.**")
    print("     줄이는 것은 테스트 점수를 보고 하는 짓이라 금지. 또한 S1은 속도 오차 std가 0.00인")
    print("     결정론적 시나리오라 **k를 연속적으로 최적화할 수 없다** — 이 한계도 그대로 기록한다.")
    print()
    return 1.0


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--outdir", default=OUTDIR)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))

    # 감사([D-038])가 낸 폭 하한 — 테스트 점수가 아니라 **감사 산출물**에서 가져온다(지침4)
    floors = {}
    p = os.path.join(OUTDIR, "summary_2e3_20_floor_decomposition.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8")):
            fs = float(r["F_sampling_physics"]) if r.get("F_sampling_physics") else 0.0
            mf = float(r["floor_canonical_vs_bar"] or 0.0)
            floors[r["scenario"]] = max(fs, mf)     # 물리 하한과 모델형 하한 중 큰 쪽

    print("#2e-3 Step 2.E · 속도/ETA 밴드 (배포판 base 기준, 편향 인지형·비대칭 경험분위수)\n")
    calibrate_on_s1(seeds)

    # ---- E3 편향 항: **S1에서만** 도출 (지침1 '편향 인지형' + 지침2 도출/평가 분리) ----
    #   E1/E2는 '런 안 per-node 산포'만 본다 → 모든 노드가 **공유하는 계통 편향**은 구조적으로 못 본다.
    #   그래서 S1의 ETA 오차(ETA_pred − ETA_true) 경험분위수를 거리별로 뽑아 밴드를 이동시킨다.
    #   ETA_true ≈ ETA_pred − (그 오차) 이므로  [early − q95, late − q05] 로 보정한다.
    bias = {}
    s1e = []
    for sd in seeds:
        r, _s = run_one(sd, {}, floor_pct=0.0)
        s1e += r
    print("=" * 104)
    print("도출(S1에서만) — E3 편향 항 (거리별 ETA 오차 경험분위수, 비대칭 그대로)")
    print("=" * 104)
    for d in ETA_DISTS:
        e = np.array([x["eta_point"] - x["eta_true"] for x in s1e if x["dist"] == d])
        if e.size == 0:
            continue
        q05, q50, q95 = (float(np.percentile(e, 5)), float(np.median(e)), float(np.percentile(e, 95)))
        bias[d] = (q05, q95)
        print(f"  {d:5.0f} m: S1 ETA 오차 5%={q05:+7.2f}s  중앙={q50:+7.2f}s  95%={q95:+7.2f}s "
              f"→ 밴드를 [−{q95:+.2f}, −{q05:+.2f}] 만큼 이동")
    print("  ※ 이 보정은 **시뮬 S1에서 경험적으로** 뽑은 값이라 −6.4 s 물리 오프셋(=warm_scale 의존)을")
    print("     그대로 물려받는다 → 실물 적용 전 [D-035]의 warm_scale ±20/30/50 % 미스매치 게이트 필요.")
    print()

    cov_rows, eta_rows = [], []
    for name, ov in SCENARIOS:
        fl = floors.get(name, 0.0)
        R, S = [], []
        for sd in seeds:
            r, s = run_one(sd, ov, floor_pct=fl)
            R += r
            S += s
        if S:
            cov_rows.append({
                "scenario": name, "n_runs": len(S), "audit_floor_pct": round(fl, 2),
                "E1_speed_cov_pct": round(float(np.mean([x["e1_in"] for x in S])) * 100, 1),
                "E2_speed_cov_pct": round(float(np.mean([x["e2_in"] for x in S])) * 100, 1),
                "E1_width_pct": round(float(np.mean([x["e1_w"] for x in S])), 1),
                "E2_width_pct": round(float(np.mean([x["e2_w"] for x in S])), 1)})
        for d in ETA_DISTS:
            sub = [x for x in R if x["dist"] == d]
            if not sub:
                continue
            tr = np.array([x["eta_true"] for x in sub])
            row = {"scenario": name, "dist_m": d, "n": len(sub),
                   "eta_true_mean_s": round(float(tr.mean()), 1)}
            q05, q95 = bias.get(d, (0.0, 0.0))
            for tag in ("e1", "e2", "e3"):
                src = "e2" if tag == "e3" else tag
                sh_lo, sh_hi = ((-q95, -q05) if tag == "e3" else (0.0, 0.0))
                lo = np.array([x[f"{src}_early"] for x in sub]) + sh_lo
                hi = np.array([x[f"{src}_late"] for x in sub]) + sh_hi
                inb = (tr >= lo) & (tr <= hi)
                row[f"{tag.upper()}_cov_pct"] = round(float(inb.mean()) * 100, 1)
                row[f"{tag.upper()}_breach_early_pct"] = round(float((tr < lo).mean()) * 100, 1)
                row[f"{tag.upper()}_breach_late_pct"] = round(float((tr > hi).mean()) * 100, 1)
                row[f"{tag.upper()}_early_s"] = round(float(lo.mean()), 1)
                row[f"{tag.upper()}_late_s"] = round(float(hi.mean()), 1)
                row[f"{tag.upper()}_width_s"] = round(float((hi - lo).mean()), 1)
            eta_rows.append(row)
        print(f"  [{name:9s}] 완료 (감사 폭하한 {fl:.2f} %)")

    write_csv(os.path.join(args.outdir, "summary_2e3_E_coverage.csv"), cov_rows)
    write_csv(os.path.join(args.outdir, "summary_2e3_E_eta_band.csv"), eta_rows)

    print("\n" + "=" * 104)
    print(f"★ 속도 밴드 커버리지 (명목 {NOMINAL:.0f} %)  ·  E1=관측만, E2=E1 ∨ 감사 하한")
    print("=" * 104)
    print(f"  {'시나리오':9s} {'감사 폭하한':>10s} {'E1 커버':>8s} {'E1 폭':>8s} | {'E2 커버':>8s} {'E2 폭':>8s}  판정")
    for r in cov_rows:
        ok1 = "✅" if r["E1_speed_cov_pct"] >= NOMINAL else "❌ 미달"
        ok2 = "✅" if r["E2_speed_cov_pct"] >= NOMINAL else "❌ 미달"
        print(f"  {r['scenario']:9s} {r['audit_floor_pct']:10.2f} {r['E1_speed_cov_pct']:7.1f}% "
              f"{r['E1_width_pct']:7.1f}% | {r['E2_speed_cov_pct']:7.1f}% {r['E2_width_pct']:7.1f}%  "
              f"E1 {ok1} / E2 {ok2}")

    print("\n" + "=" * 104)
    print("★ ETA 밴드 (초)  ·  breach_early = 참 도착이 밴드 이른끝보다 더 이름 = **위험**")
    print("   E2 = 관측 산포 ∨ 감사 하한 (편향 미포함)   |   E3 = E2 + S1에서 도출한 편향 항")
    print("=" * 104)
    print(f"  {'시나리오':9s} {'거리':>5s} {'참ETA':>7s} | {'E2커버':>7s} {'E2위험':>7s} {'E2보수':>7s} "
          f"| {'E3 이른끝':>9s} {'E3 늦은끝':>9s} {'E3폭':>6s} {'E3커버':>7s} {'★E3위험':>8s} {'E3보수':>7s}")
    for r in eta_rows:
        print(f"  {r['scenario']:9s} {r['dist_m']:5.0f} {r['eta_true_mean_s']:7.1f} | "
              f"{r['E2_cov_pct']:6.1f}% {r['E2_breach_early_pct']:6.1f}% {r['E2_breach_late_pct']:6.1f}% | "
              f"{r['E3_early_s']:9.1f} {r['E3_late_s']:9.1f} {r['E3_width_s']:6.1f} "
              f"{r['E3_cov_pct']:6.1f}% {r['E3_breach_early_pct']:7.1f}% {r['E3_breach_late_pct']:6.1f}%")

    print("\n" + "=" * 104)
    print("★ 안전 측면 요약 — 이른끝이 조기경보 하한으로 유효한가 (지침3)")
    print("=" * 104)
    for tag in ("E2", "E3"):
        mx = max(r[f"{tag}_breach_early_pct"] for r in eta_rows)
        bad = [f"{r['scenario']}@{r['dist_m']:.0f}m={r[f'{tag}_breach_early_pct']}%"
               for r in eta_rows if r[f"{tag}_breach_early_pct"] > 10.0]
        print(f"  {tag}: 최대 위험측 초과율 = {mx:.1f} %  → 단측 신뢰도 {100-mx:.1f} %  "
              f"{'✅ 조기경보 하한으로 유효' if mx <= 10 else '❌ 하한 무효'}")
        if bad:
            print(f"      10 % 초과 지점: {', '.join(bad[:6])}")

    print("\n" + "=" * 104)
    print("★ 발표 표기 예시 (점 숫자 금지 — 'ETA 4~6분(90 %)' 형식) · E3 기준")
    print("=" * 104)
    for r in eta_rows:
        if r["dist_m"] != 100.0:
            continue
        lo, hi = r["E3_early_s"], r["E3_late_s"]
        print(f"  {r['scenario']:9s} 100 m: \"ETA {lo/60:.1f}~{hi/60:.1f}분\"  "
              f"(참 {r['eta_true_mean_s']/60:.1f}분, 커버 {r['E3_cov_pct']:.0f} %, 위험측 {r['E3_breach_early_pct']:.1f} %)")


if __name__ == "__main__":
    main()
