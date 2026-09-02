"""night_robustness.py — 추정기 강건성 합성 실험 (2026-08-31 야간).

★ 이 스크립트가 만드는 모든 산출물은 **합성(SYNTHETIC)** 이다. 행마다 fake=1 을 찍는다.
★ sim/estimator.py 는 건드리지 않는다. **동결된 추정기를 그대로 인스턴스화해서 돌린다.**

--- 참값(ground truth) 모델 ---
mock_fw_serial.generate() 의 방사형 전선과 **같은 물리**를 쓴다:
    T(t) = ambient + (peak-ambient)*exp(-d/warm_scale),  d = r_i - (p0 + v*t)
    T >= 80 이 되는 순간이 사망 → d* = warm_scale*ln((peak-ambient)/(thr-ambient))
    p0 = min(r) + p0_offset,  p0_offset = -d*  (대본 B 규약: 가장 앞선 노드가 t=0 에 사망)
    ⇒ t_death(i) = (r_i - min(r)) / v          ... 오프셋이 정확히 상쇄된다
r_i 는 점화점에서 노드까지의 거리다. 즉 **속도는 시각의 배율일 뿐이고 기하는 건드리지 않는다.**

--- 참값 방향 세 가지 ---
추정기 출력의 정의와 "참값" 의 정의가 서로 다르다. 그래서 잡음이 0이어도 오차는 0이 아니다.
이 하한을 먼저 재고(=기하학적 하한), 그 위에 잡음 영향을 얹는다.
    ① 점화점 -> 판 중심   (문서·덱이 쓰는 헤드라인 참값)
    ② 국소 법선 벡터평균  (추정기의 국소 적합이 재는 것)
    ③ 전역 단일 평면적합  (추정기의 전역 적합이 재는 것)
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.config import Config          # noqa: E402
from sim.estimator import Estimator    # noqa: E402

# ── 고정 상수 (헌장 §1 동결값 — 바꾸지 않는다) ───────────────────────────
ROWS = COLS = 4
ORIGIN    = (0.02, -0.11) # m, 대본 B 점화점

# ★★ [2026-09-01 TRUTH AUDIT] 여기 있던 `V_FRONT = 0.00061 (D-069)` 는 **두 세대 전 값**이었다
#   (D-074 0.000523 → D-075 0.000579). 파생 주석도 590.2/327.9 로 굳어 있었다.
#   런에는 안 들어가지만, 보고서용 강건성 분석을 다시 돌리면 **현재 대본과 다른 규모의 숫자**가
#   나와 제출물 안에서 숫자가 어긋난다. 그래서 하드코딩을 지우고 **정본에서 읽는다.**
def _load_deploy():
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "gateway", "deploy_config.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)["config"]


_C = _load_deploy()
SPACING = float(_C["spacing_m"])          # 정본: gateway/deploy_config.json
RADIO   = float(_C["radio_range_m"])
V_FRONT = float(_C["v_front_expected"])


def _center(P):
    xs = [p[0] for p in P.values()]; ys = [p[1] for p in P.values()]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


DT_WINDOW     = RADIO   / V_FRONT       # 유도값 — 손으로 적지 않는다
ALERT_HORIZON = SPACING / V_FRONT

OUTDIR = os.path.join("results", "night")


# ── 배치 · 이웃 ──────────────────────────────────────────────────────────
def positions(measured=True):
    """노드 좌표. 기본은 **실측**(`gateway/deploy_config.json`).

    ★ [2026-08-31] 예전에는 명목 격자를 만들어 썼다. 실측 좌표가 반영된 뒤로는
      그것이 곧 참값 정의(점화점→판 중심)를 바꾸므로, 분석도 같은 좌표를 써야 한다.
      명목으로 돌리려면 measured=False.
    """
    if not measured:
        return {r * COLS + c: (c * SPACING, r * SPACING) for r in range(ROWS) for c in range(COLS)}
    import json as _json
    _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "gateway", "deploy_config.json")
    with open(_p, encoding="utf-8") as f:
        _d = _json.load(f)
    return {n["id"]: (n["x"], n["y"]) for n in _d["nodes"]}


def neighbors(pos, radio=RADIO):
    out = {}
    for i, pi in pos.items():
        out[i] = [j for j, pj in pos.items()
                  if j != i and math.hypot(pi[0] - pj[0], pi[1] - pj[1]) <= radio + 1e-12]
    return out


def make_cfg():
    return Config(mode="ours", spacing_m=SPACING, radio_range_m=RADIO, dt=1.0,
                  dt_window=DT_WINDOW, alert_horizon=ALERT_HORIZON, speed_true=V_FRONT)


# ── 참값 ────────────────────────────────────────────────────────────────
def true_death_times(pos, origin=ORIGIN, v=V_FRONT):
    r = {i: math.hypot(p[0] - origin[0], p[1] - origin[1]) for i, p in pos.items()}
    rmin = min(r.values())
    return {i: (r[i] - rmin) / v for i in r}


def truth_center_deg(origin=ORIGIN, center=None):
    """① 점화점 -> 판 중심. center 를 안 주면 현재 좌표의 외곽 중점을 쓴다."""
    if center is None:
        center = _center(positions())
    return math.degrees(math.atan2(center[1] - origin[1], center[0] - origin[0])) % 360.0


def ang_deg(vec):
    return math.degrees(math.atan2(vec[1], vec[0])) % 360.0


def ang_err(a, b):
    """두 방향(도)의 최소 차이. 부호 없는 각도차."""
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


# ── 추정 1회 ─────────────────────────────────────────────────────────────
def estimate(deaths_dict, pos, cfg, nb):
    """deaths_dict: {id: t}. 반환: (전역방향deg|None, 국소법선평균deg|None, est, n_local)."""
    est_obj = Estimator(cfg, nb)
    tmax = max(deaths_dict.values())
    ev = [{"id": i, "pos": pos[i], "death_t_est": t} for i, t in sorted(deaths_dict.items(),
                                                                       key=lambda kv: kv[1])]
    survivors = [(i, pos[i]) for i in pos if i not in deaths_dict]
    est = est_obj.update(ev, tmax, survivors)
    g = ang_deg(est["dir"]) if est["dir"] else None
    locs = [v["dir"] for v in est["per_node"].values() if v.get("dir")]
    if locs:
        mx = float(np.mean([d[0] for d in locs])); my = float(np.mean([d[1] for d in locs]))
        loc = ang_deg((mx, my)) if math.hypot(mx, my) > 1e-12 else None
    else:
        loc = None
    return g, loc, est, len(locs)


# ── 리드타임 · ETA (구간 해석해) ─────────────────────────────────────────
def lead_times(deaths_dict, pos, cfg, nb, horizon=ALERT_HORIZON):
    """각 노드가 죽기 전에 실제로 받은 경고 시간(초)과 ETA 오차를 구간 해석으로 구한다.

    사망 사이 구간에서는 적합이 고정이므로 eta(p,t) = predict_arrival(p) - t 는 t 에 선형이다.
    따라서 경보 조건 eta <= H 는 t >= predict_arrival(p) - H 로 정확히 풀린다.
    """
    order = sorted(deaths_dict.items(), key=lambda kv: kv[1])
    est_obj = Estimator(cfg, nb)
    first_alert = {}          # id -> 최초 경보 시각
    eta_err = {}              # id -> (마지막 예측 도달시각 - 실제 사망시각)
    for k, (nid, tk) in enumerate(order):
        est_obj.update([{"id": nid, "pos": pos[nid], "death_t_est": tk}], tk, None)
        seg_end = order[k + 1][1] if k + 1 < len(order) else max(deaths_dict.values())
        for j, pj in pos.items():
            if j in first_alert or deaths_dict.get(j, math.inf) <= tk:
                continue
            pa = est_obj.predict_arrival(pj)
            if pa is None:
                continue
            t_on = max(tk, pa - horizon)
            if t_on <= min(seg_end, deaths_dict.get(j, math.inf)):
                first_alert[j] = t_on
        for j, pj in pos.items():
            if j in deaths_dict and deaths_dict[j] > tk:
                pa = est_obj.predict_arrival(pj)
                if pa is not None:
                    eta_err[j] = pa - deaths_dict[j]      # +면 늦게 온다고 예측
    lead = {j: deaths_dict[j] - first_alert[j] for j in first_alert if j in deaths_dict}
    return lead, eta_err


# ── CSV ─────────────────────────────────────────────────────────────────
def write_csv(name, rows, fields):
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            r = dict(r); r["fake"] = 1
            w.writerow(r)
    return path


def pct(a, q):
    return float(np.percentile(a, q)) if len(a) else float("nan")


def summarize(a):
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return dict(n=0, median=float("nan"), p90=float("nan"), mean=float("nan"),
                    p99=float("nan"), max=float("nan"))
    return dict(n=int(a.size), median=float(np.median(a)), p90=pct(a, 90),
                mean=float(a.mean()), p99=pct(a, 99), max=float(a.max()))
