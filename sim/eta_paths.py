"""eta_paths.py — ETA 두 경로 + **등급 게이트** 버전 분기 [2.N §3-A/B].

★ `sim/estimator.py`는 **불변**이다. `predict_arrival`이 그 안에 있으므로 게이트를 직접 넣을 수 없다.
  그래서 집계(`aggregate.py`) 때와 **같은 패턴**으로, estimator가 만든 `per_node`를 밖에서 읽어
  게이트를 적용한 예측을 따로 계산한다. **기본 동작(estimator)은 아무것도 바뀌지 않는다.**

── ETA 경로가 둘이라는 사실 [D-064] ──────────────────────────────────────────
  P1 `estimator.predict_arrival` : 앵커 = **유클리드 최근접** per_node 노드,
        T_pred = t_i + ∇T_i·(p − p_i)          ← 속도원 = **그 노드의 |∇T_i|**
        쓰는 곳: `metrics.arrival_err_s`, `_alerts`(대피경보) → **대시보드 HUD**
  P2 `run_2e3_stepE` 밴드 ETA    : 앵커 = 같은 최근접 노드의 t_i,
        ETA = (t_i − t_now) + (û·(p − p_i)) / med   ← 속도원 = **per-node 속도 중앙값**
        쓰는 곳: E3/E3x/E3x2 밴드 분석 → **보고서의 ETA 구간**
  **둘 다 `dir_global`을 쓰지 않는다.** 차이는 속도원뿐이다.

── 게이트(A) ──────────────────────────────────────────────────────────────
  현재 P1은 앵커 노드의 **등급을 보지 않는다.** flank W10 d60에서 `dir_global`은 None인데
  P1은 같은(퇴화한) 국소 적합의 ∇T로 **숫자를 낸다** — 모순이고 위험 쪽이다.
  ⇒ `INSUFFICIENT`(DOF<1 포함) 노드를 **앵커 후보에서 제외**한다.
     제외 후 후보가 없으면 **ETA도 INSUFFICIENT**(폴백 금지 — [D-063] §4-5와 같은 원칙).
"""
from __future__ import annotations

import numpy as np

from .adequacy import local_adequacy, INSUFFICIENT

OK_GRADE, INSUF = "OK", INSUFFICIENT


def node_grades(estimator, cfg):
    """per_node 각 노드의 국소 적합 등급 — estimator._fit_local과 같은 규칙으로 재구성."""
    out = {}
    deaths = estimator.deaths
    for i in estimator.per_node:
        xi, yi, ti = deaths[i]
        ids = [i]
        for j in estimator.neighbors.get(i, []):
            if j in deaths and abs(deaths[j][2] - ti) <= cfg.dt_window:
                ids.append(j)
        out[i] = local_adequacy([(deaths[k][0], deaths[k][1]) for k in ids],
                                [deaths[k][2] for k in ids], cfg.spacing_m)
    return out


def _nearest(per_node, p, allow=None):
    best, bd = None, float("inf")
    for i, v in per_node.items():
        if allow is not None and i not in allow:
            continue
        d = float(np.linalg.norm(np.asarray(p, float) - np.asarray(v["pos"], float)))
        if d < bd:
            bd, best = d, i
    return best


def predict_p1(estimator, p, allow=None):
    """P1 경로. allow=None이면 **현행과 비트 동일**, 집합을 주면 그 안에서만 앵커를 고른다."""
    i = _nearest(estimator.per_node, p, allow)
    if i is None:
        return None, None
    v = estimator.per_node[i]
    t = float(v["t"] + np.asarray(v["grad"], float) @
              (np.asarray(p, float) - np.asarray(v["pos"], float)))
    return t, i


def predict_p2(estimator, p, allow=None):
    """P2 경로(stepE 밴드와 같은 식). 속도원만 per-node **중앙값**으로 바뀐다."""
    i = _nearest(estimator.per_node, p, allow)
    if i is None:
        return None, None
    v = estimator.per_node[i]
    sp = [x["speed"] for x in estimator.per_node.values()]
    med = float(np.median(sp))
    if med <= 1e-12:
        return None, i
    u = np.asarray(v["dir"], float)
    s_axis = float(u @ (np.asarray(p, float) - np.asarray(v["pos"], float)))
    return float(v["t"] + s_axis / med), i


def gated_allow(grades):
    """게이트 통과 노드 집합 — INSUFFICIENT 제외(DOF<1은 local_adequacy가 이미 그렇게 분류)."""
    return {i for i, r in grades.items() if r["grade"] != INSUF}
