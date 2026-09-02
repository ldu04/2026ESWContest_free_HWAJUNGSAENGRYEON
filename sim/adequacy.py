"""adequacy.py — 표본 적정성 자기진단 [2.M §1].

**추정기가 자기 답을 믿어도 되는지 스스로 판정**하게 하는 계층.
새 방어를 발명하는 게 아니라, **평면 적합이 성립하기 위한 전제조건을 실행 시점에 검사**한다.

★ 기준의 유도는 `docs/유도_표본적정성_진단기준.md`에 **구현 전에** 적고 커밋했다(p-해킹 방지).
  이 파일은 그 문서를 코드로 옮긴 것이며, 임계를 결과 보고 조정하지 않는다.

★ `sim/estimator.py`는 **건드리지 않는다.** 진단은 estimator가 이미 만든 국소 적합 정보를
  **밖에서 다시 읽어** 계산한다(같은 좌표·같은 창 규칙을 재현하되, estimator의 수학에는 손대지 않는다).

★ 이 진단이 **못 잡는 것**(문서 §5와 동일, 출력에도 싣는다):
  ① 계통 편향 — 모든 국소 적합이 **일관되게** 틀리면 통과한다(곡률 오차가 여기 해당할 수 있다)
  ② 모델 오차 — "평면 모델 하에서 표본이 충분한가"만 본다
  ③ 사망시각 공통 시프트 — 잔차에 안 잡힌다
  ⇒ **`OK`는 "정확하다"가 아니라 "표본 부족으로 틀린 건 아니다"라는 뜻이다.**
"""
from __future__ import annotations

import math

import numpy as np

# ── 유도 문서에서 온 상수. **조정 대상 아님** ──
PRACTICAL_LINE_DEG = 5.0      # 방향 실용선 — 지시서 #1 DoD 이래 계속 쓰던 값(새로 만들지 않았다)
DOF_MIN = 1                   # DOF ≥ 1 이라야 σ̂_t 추정 가능 → n ≥ 4
DOF_TRUST = 2                 # DOF ≥ 2 라야 σ̂ 자체가 미덥다 → n ≥ 5
EPS_GEOM_REL = 1e-9           # σ₂ ≤ EPS_GEOM_REL·σ₁ 이면 공선(부동소수 잡음 수준)

OK, DEGRADED, INSUFFICIENT = "OK", "DEGRADED", "INSUFFICIENT"
_RANK = {OK: 0, DEGRADED: 1, INSUFFICIENT: 2}


def worst(*grades):
    return max(grades, key=lambda g: _RANK[g])


def local_adequacy(pts, times, spacing_m):
    """한 국소 평면 적합의 표본 적정성.

    pts   : [(x, y), ...] 적합에 실제로 들어간 관측 좌표
    times : [t, ...]      같은 순서의 사망시각
    반환  : dict(grade, dphi_hat_deg, s2, n_obs, dof, sigma_t, cond, reason)
    """
    P = np.asarray(pts, dtype=float)
    b = np.asarray(times, dtype=float)
    n = int(P.shape[0])
    dof = n - 3
    out = {"n_obs": n, "dof": dof, "s2": None, "cond": None,
           "sigma_t": None, "dphi_hat_deg": None, "grade": INSUFFICIENT, "reason": ""}

    if n < 3:
        out["reason"] = "n<3: 평면 적합 자체가 불가"
        return out

    # 중심화 — 상수항은 잉여모수이므로 기울기를 구속하는 건 중심화 좌표뿐이다
    Mt = P - P.mean(axis=0)
    sv = np.linalg.svd(Mt, compute_uv=False)
    s1 = float(sv[0]) if sv.size > 0 else 0.0
    s2 = float(sv[1]) if sv.size > 1 else 0.0
    out["s2"] = round(s2 / (spacing_m * math.sqrt(n)), 6) if spacing_m > 0 else None
    out["cond"] = (float(s1 / s2) if s2 > 0 else float("inf"))

    # ── (b) 기하: 공선이면 방향의 한 성분이 원리적으로 구속되지 않는다 ──
    if s2 <= EPS_GEOM_REL * max(s1, 1e-30):
        out["reason"] = "공선(σ₂≈0): 그 선에 수직한 기울기 성분이 구속되지 않음"
        return out

    # ── (a) 개수: DOF < 1 이면 자기 오차를 추정할 수단이 없다 ──
    if dof < DOF_MIN:
        out["reason"] = f"DOF={dof}<{DOF_MIN}: 잔차가 항등 0, 자기 오차 추정 불가"
        return out

    # ── 예측 각불확실성 δφ̂ (전부 런타임 관측량) ──
    A = np.hstack([P, np.ones((n, 1))])
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    g = sol[:2]
    gn = float(np.linalg.norm(g))
    resid = b - A @ sol
    sigma_t = float(math.sqrt(float(resid @ resid) / dof))
    out["sigma_t"] = round(sigma_t, 6)

    if gn <= 1e-12:
        out["reason"] = "|∇T|≈0: 방향이 정의되지 않음"
        return out

    # ĝ 에 수직한 방향의 분산 (문서 §3)
    u_perp = np.array([-g[1], g[0]]) / gn
    try:
        cov_geom = np.linalg.inv(Mt.T @ Mt)
    except np.linalg.LinAlgError:
        out["reason"] = "정규행렬 특이: 기하가 방향을 구속하지 못함"
        return out
    var_perp = float(u_perp @ cov_geom @ u_perp) * sigma_t ** 2
    dphi = math.degrees(math.sqrt(max(var_perp, 0.0)) / gn)
    out["dphi_hat_deg"] = round(dphi, 4)

    # ── (c) 등급 ──
    if dphi > PRACTICAL_LINE_DEG:
        out["grade"] = DEGRADED
        out["reason"] = f"δφ̂={dphi:.2f}° > 실용선 {PRACTICAL_LINE_DEG:.0f}°"
    elif dof < DOF_TRUST:
        # δφ̂ 는 통과했지만 σ̂ 자체가 못 미더운 구간(n=4) — 문서 §1에서 이미 DEGRADED로 유도됨
        out["grade"] = DEGRADED
        out["reason"] = f"DOF={dof}<{DOF_TRUST}: σ̂ 추정 자체가 불안정"
    else:
        out["grade"] = OK
        out["reason"] = f"δφ̂={dphi:.2f}° ≤ {PRACTICAL_LINE_DEG:.0f}°, DOF={dof}"
    return out


def _circular_std_deg(dirs):
    """단위벡터 목록의 원형 표준편차(도). 방향이 서로 얼마나 어긋나는가."""
    V = np.asarray(dirs, dtype=float)
    if V.shape[0] < 2:
        return 0.0
    R = float(np.linalg.norm(V.mean(axis=0)))
    R = min(max(R, 1e-12), 1.0)
    return math.degrees(math.sqrt(max(-2.0 * math.log(R), 0.0)))


def global_adequacy(local_records, dirs):
    """전역 방향(속도가중 평균)의 적정성. 문서 §4의 정의를 그대로 따른다.

    local_records : local_adequacy() 결과 리스트 (per-node)
    dirs          : 같은 순서의 per-node 방향 단위벡터
    """
    usable = [(r, d) for r, d in zip(local_records, dirs)
              if r["grade"] != INSUFFICIENT and r["dphi_hat_deg"] is not None]
    out = {"n_local": len(local_records), "n_usable": len(usable),
           "n_ok": sum(1 for r in local_records if r["grade"] == OK),
           "dphi_stat_deg": None, "dphi_disp_deg": None,
           "dphi_hat_deg": None, "grade": INSUFFICIENT, "reason": ""}
    if not usable:
        out["reason"] = "쓸 수 있는 국소 적합이 없음"
        return out

    n = len(usable)
    stat = math.sqrt(float(np.mean([r["dphi_hat_deg"] ** 2 for r, _ in usable]))) / math.sqrt(n)
    disp = _circular_std_deg([d for _, d in usable]) / math.sqrt(n)
    out["dphi_stat_deg"] = round(stat, 4)
    out["dphi_disp_deg"] = round(disp, 4)
    dphi = max(stat, disp)
    out["dphi_hat_deg"] = round(dphi, 4)
    if dphi > PRACTICAL_LINE_DEG:
        out["grade"] = DEGRADED
        out["reason"] = (f"δφ̂_global={dphi:.2f}° > {PRACTICAL_LINE_DEG:.0f}° "
                         f"(stat {stat:.2f} / disp {disp:.2f})")
    else:
        out["grade"] = OK
        out["reason"] = f"δφ̂_global={dphi:.2f}° ≤ {PRACTICAL_LINE_DEG:.0f}°"
    return out


def diagnose(estimator, cfg):
    """estimator의 현재 국소 적합들을 **밖에서 읽어** 진단한다. estimator는 불변.

    반환: {"local": {id: rec}, "global": rec, "count_grade": ..., "caveat": ...}
    """
    deaths = estimator.deaths
    locals_, dirs, per_id = [], [], {}
    for i, v in estimator.per_node.items():
        # estimator._fit_local 과 **같은 규칙**으로 지역집합을 재구성한다(수학은 손대지 않는다)
        xi, yi, ti = deaths[i]
        ids = [i]
        for j in estimator.neighbors.get(i, []):
            if j in deaths and abs(deaths[j][2] - ti) <= cfg.dt_window:
                ids.append(j)
        pts = [(deaths[k][0], deaths[k][1]) for k in ids]
        ts = [deaths[k][2] for k in ids]
        rec = local_adequacy(pts, ts, cfg.spacing_m)
        rec["id"] = i
        per_id[i] = rec
        locals_.append(rec)
        dirs.append(v["dir"])

    # 비교용: **개수만** 보는 등급 (지시서 요구 — 어느 지표가 오답을 잘 잡는지 비교)
    cnt = [(OK if r["n_obs"] >= 5 else (DEGRADED if r["n_obs"] == 4 else INSUFFICIENT))
           for r in locals_]
    n_ok_cnt = sum(1 for c in cnt if c == OK)
    count_grade = (INSUFFICIENT if not cnt or all(c == INSUFFICIENT for c in cnt)
                   else (OK if n_ok_cnt >= max(1, len(cnt) // 2) else DEGRADED))

    return {"local": per_id,
            "global": global_adequacy(locals_, dirs),
            "count_grade": count_grade,
            "caveat": "OK는 '정확하다'가 아니라 '표본 부족으로 틀린 건 아니다'라는 뜻이다. "
                      "계통 편향(곡률 등)·모델 오차·사망시각 공통 시프트는 이 진단이 못 잡는다."}
