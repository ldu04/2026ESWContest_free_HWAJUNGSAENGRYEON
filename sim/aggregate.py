"""aggregate.py — 전역 방향 집계의 **버전 분기** [2.N 추가-G].

유도는 `docs/유도_표본적정성_진단기준.md` **부록 B**에 측정 전 커밋(817dbfe).

★ `sim/estimator.py`는 **불변**이다. 그래서 여기서는 estimator가 이미 만든 `per_node`를
  **밖에서 다시 집계**한다. `legacy`는 `_fit_global`의 계산을 그대로 재현하므로
  **`estimator.dir_global`과 비트 동일**해야 한다(테스트로 고정).

★ **기본값은 `invvar`** [D-063]. 레거시는 `mode="legacy"`로 계속 보존되고 비트 동일이다.
  ★폴백 없음 — invvar가 값을 못 내면 **명시적으로 `grade=INSUFFICIENT`**를 돌려준다.
    legacy로 조용히 되돌아가면 "가중 폭주"라는 실패가 다시 숨기 때문이다.
  ★속도의 `median` 집계는 `estimator._fit_global` 안에 있고 **건드리지 않는다** — §4-2의 통제군.

후보 (부록 B-5)
  legacy       w_i = speed_i = 1/|∇T_i|          ← 현행. 퇴화 적합일수록 가중이 커진다
  uniform      w_i = 1                            ← 가중 제거 대조군
  median       원형 중앙값(각도 순위 기반)         ← 이상치에 강함
  invvar       w_i = 1/δφ̂_i²                      ← 부록 B-2의 이론적 정답 후보
  invvar_trim  invvar + INSUFFICIENT 등급 배제     ← + 퇴화 적합 제외
"""
from __future__ import annotations

import math

import numpy as np

from .adequacy import local_adequacy, OK, INSUFFICIENT   # 등급 문자열은 adequacy가 정본

MODES = ("legacy", "uniform", "median", "invvar", "invvar_trim")

# ★ [D-063] 기본 집계를 **invvar**로 전환. 근거는 부록 B-2(역분산) + [D-062] 측정(예측 4/4 일치).
#   ★폴백 없음: invvar가 값을 못 내면 **명시적으로 INSUFFICIENT**를 돌려준다.
#     legacy로 조용히 되돌아가면 "가중 폭주"라는 실패가 다시 숨는다.
#   ★레거시 경로는 버전 분기로 **계속 보존**한다(mode="legacy", 비트 동일 회귀 유지).
#   ★속도의 median 집계는 estimator 안에 있고 **건드리지 않는다** — §4-2의 통제군이다.
DEFAULT_MODE = "invvar"


def _unit(v):
    n = float(np.linalg.norm(v))
    return (v / n) if n > 1e-12 else None


def _circular_median(dirs):
    """각도 순위 기반 중앙값 — 각 후보를 축으로 놓고 **각거리 합**이 최소인 것을 고른다."""
    A = np.asarray(dirs, dtype=float)
    best, best_cost = None, float("inf")
    for cand in A:
        c = 0.0
        for other in A:
            d = float(np.clip(cand @ other, -1.0, 1.0))
            c += math.acos(d)
        if c < best_cost:
            best_cost, best = c, cand
    return _unit(np.asarray(best, dtype=float)) if best is not None else None


def _weights(estimator, cfg, mode):
    """(ids, dirs, weights, 진단 rec) — mode에 따른 가중치."""
    ids, dirs, recs = [], [], []
    for i, v in estimator.per_node.items():
        ids.append(i)
        dirs.append(np.asarray(v["dir"], dtype=float))
        recs.append(None)
    if not ids:
        return [], [], [], []

    if mode == "legacy":
        w = [float(estimator.per_node[i]["speed"]) for i in ids]
    elif mode == "uniform":
        w = [1.0] * len(ids)
    elif mode == "median":
        w = [1.0] * len(ids)                       # 실제 결합은 _circular_median 이 한다
    else:                                          # invvar / invvar_trim
        deaths = estimator.deaths
        w = []
        for k, i in enumerate(ids):
            xi, yi, ti = deaths[i]
            sub = [i]
            for j in estimator.neighbors.get(i, []):
                if j in deaths and abs(deaths[j][2] - ti) <= cfg.dt_window:
                    sub.append(j)
            rec = local_adequacy([(deaths[m][0], deaths[m][1]) for m in sub],
                                 [deaths[m][2] for m in sub], cfg.spacing_m)
            recs[k] = rec
            d = rec.get("dphi_hat_deg")
            # δφ̂ 를 못 구하면(DOF<1 등) 가중 0에 가깝게 — 정보가 없다는 뜻이다
            w.append(1.0 / (d * d) if (d is not None and d > 1e-9) else 0.0)
    return ids, dirs, w, recs


def aggregate_direction(estimator, cfg, mode=None):
    """전역 방향을 mode 규칙으로 집계.

    mode 기본값은 `DEFAULT_MODE`(=invvar). **폴백 없음** — 값을 못 내면 grade=INSUFFICIENT.
    반환 dict(mode, dir, grade, n_local, n_used, n_eff, n_eff_frac, max_w_frac, disp_w_deg, reason)
      · `n_local` = **원표본수**(per_node 전체). `n_eff`는 **반드시 이 값과 짝지어** 읽어야 한다 —
        n_eff 단독 표기는 오진을 유도한다(n_eff=1.0이 "표본이 1개"인지 "10개인데 하나가 지배"인지
        구분되지 않는다). [D-063]
    """
    mode = DEFAULT_MODE if mode is None else mode
    n_local = len(estimator.per_node)
    ids, dirs, w, recs = _weights(estimator, cfg, mode)
    out = {"mode": mode, "dir": None, "grade": INSUFFICIENT, "n_local": n_local,
           "n_used": 0, "n_eff": None, "n_eff_frac": None,
           "max_w_frac": None, "disp_w_deg": None, "reason": ""}
    if not ids:
        out["reason"] = "국소 적합이 없음"
        return out

    if mode == "invvar_trim":
        keep = [k for k, r in enumerate(recs)
                if r is not None and r["grade"] != INSUFFICIENT and w[k] > 0]
        ids = [ids[k] for k in keep]
        dirs = [dirs[k] for k in keep]
        w = [w[k] for k in keep]
        if not ids:
            out["reason"] = "INSUFFICIENT 배제 후 남은 적합이 없음"
            return out

    out["n_used"] = len(ids)

    if mode == "median":
        out["dir"] = _circular_median(dirs)
        out["n_eff"] = float(len(dirs))
        out["n_eff_frac"] = 1.0
        out["max_w_frac"] = round(1.0 / len(dirs), 4)
    else:
        W = np.asarray(w, dtype=float)
        sw = float(W.sum())
        if sw <= 0:
            # ★폴백 없음 — invvar에서 전 적합이 DOF<1이면 여기 걸린다. legacy로 되돌아가지 않는다.
            out["reason"] = (f"{mode}: 유효 가중이 전부 0 "
                             f"(국소 적합 {n_local}개가 전부 δφ̂ 산출 불가 = DOF<1)")
            return out
        acc = np.zeros(2)
        for wi, d in zip(W, dirs):
            acc += wi * d
        out["dir"] = _unit(acc)
        # ★ 유효표본수(Kish) — 하나가 지배하면 1로 간다(부록 B-6)
        out["n_eff"] = round(float(sw * sw / float((W * W).sum())), 3)
        out["n_eff_frac"] = round(out["n_eff"] / len(ids), 4) if ids else None
        out["max_w_frac"] = round(float(W.max() / sw), 4)
        # ★ 가중 반영 원형표준편차 — 기존 disp는 비가중이라 가중 후 붕괴를 못 봤다
        R = float(np.linalg.norm(acc)) / sw
        R = min(max(R, 1e-12), 1.0)
        out["disp_w_deg"] = round(math.degrees(math.sqrt(max(-2.0 * math.log(R), 0.0))), 4)
    if out["dir"] is not None:
        out["dir"] = (float(out["dir"][0]), float(out["dir"][1]))
        out["grade"] = OK
        out["reason"] = f"{mode}: n_local={n_local}, n_used={out['n_used']}, n_eff={out['n_eff']}"
    else:
        out["reason"] = out["reason"] or f"{mode}: 방향 벡터합이 0에 가까움"
    return out


def all_modes(estimator, cfg):
    return {m: aggregate_direction(estimator, cfg, m) for m in MODES}
