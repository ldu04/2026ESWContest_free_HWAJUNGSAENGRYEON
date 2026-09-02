"""estimator_regress.py — #2e-3 Step 2.A · 역수를 제거한 속도 추정 (**원 estimator는 그대로 보존**).

원 `Estimator`(estimator.py)는 도착시각 평면 `t ≈ a·x + b·y + c` 를 적합해
    방향 = ∇T/|∇T|,   속도 = 1/|∇T|
를 낸다. Step 1([D-037])이 밝힌 문제는 **속도 쪽의 역수**다:
|∇T|에 평균 0인 잡음이 실려도 Jensen 부등식으로 `E[1/X] > 1/E[X]` 이므로 속도가 **위로 치우친다**.
실제로 모든 스트레스에서 부호가 +였다(S2a20 +29.8 %, S6 9노드 +34.6 %, S7 +25.0 %).

이 파일은 **그 한 단계만** 바꾼다:
    방향 û_i : 원 평면적합 결과 **그대로 재사용**(손대지 않음 — 방향이 우리 헤드라인 2.1°)
    속도 v_i : 국소 집합 S_i 에서  s_j = p_j·û_i  를  t_j 에 **회귀한 기울기** (나눗셈 없음)
               회귀는 Theil–Sen(쌍기울기 중앙값) — 하이퍼파라미터 없음 = 스윕할 것도 없음.

[D-038] 1c 경고 준수: 표본을 전역으로 풀링하면 노이즈가 지배할 때 오히려 악화한다(S1 0.10→8.64 %).
따라서 **"국소 적합 + per-node 중앙값" 구조는 그대로 두고 역수 단계만 교체**한다.

방향 비열화를 **구조적으로** 막는 장치:
  `_fit_global`의 방향 가중치는 **원래의 평면 속도(`speed_plane`)**를 그대로 쓴다.
  → 방향 산출 경로에 새 속도가 전혀 들어가지 않으므로 **방향은 비트 단위로 동일**하다.
  (그럼에도 S1~S11 전 시나리오에서 실측으로 재확인한다.)

도달예측(predict_arrival)은 국소 평면의 기울기를 쓰는데, 그 기울기의 **크기**가 곧 1/속도다.
따라서 새 속도를 반영하려면 `grad = û_i / v_i` 로 재구성한다. 방향 û_i 는 불변이므로
**ETA는 속도 개선분만큼만 움직인다**(Step 1 ⑤: 원거리 ETA 오차의 주범이 속도 편향이었다).
"""
from __future__ import annotations

import numpy as np

from .estimator import Estimator


def theil_sen_slope(t: np.ndarray, s: np.ndarray, eps: float = 1e-9) -> float | None:
    """s = α + v·t 의 기울기 v 를 쌍기울기 중앙값으로. 표본 <2 또는 t가 모두 같으면 None.

    로버스트 회귀 중 **하이퍼파라미터가 없는** 것을 골랐다 — 튜닝할 여지 자체가 없어야
    '테스트 점수로 스윕하지 않았다'가 구조적으로 보장된다([D-030]·[D-034] 규율의 연장).
    """
    n = len(t)
    if n < 2:
        return None
    slopes = []
    for a in range(n - 1):
        dt = t[a + 1:] - t[a]
        ok = np.abs(dt) > eps
        if np.any(ok):
            slopes.append((s[a + 1:][ok] - s[a]) / dt[ok])
    if not slopes:
        return None
    allsl = np.concatenate(slopes)
    return float(np.median(allsl)) if allsl.size else None


class RegressionEstimator(Estimator):
    """원 Estimator와 동일하되, 속도만 `s`-vs-`t` 회귀 기울기로 낸다.

    per_node[i] 에 두 값이 함께 남는다:
      "speed_plane" = 1/|∇T|          (원 방식, 방향 가중치·비교용)
      "speed"       = 회귀 기울기      (새 방식, 전역 속도 집계에 사용)
    """

    def _fit_local(self) -> None:
        cfg = self.cfg
        self.per_node = {}
        for i, (xi, yi, ti) in self.deaths.items():
            ids = [i]
            for j in self.neighbors.get(i, []):
                if j in self.deaths:
                    tj = self.deaths[j][2]
                    if abs(tj - ti) <= cfg.dt_window:
                        ids.append(j)
            if len(ids) < cfg.min_samples:
                continue

            A = np.array([[self.deaths[k][0], self.deaths[k][1], 1.0] for k in ids])
            b = np.array([self.deaths[k][2] for k in ids])
            sol, *_ = np.linalg.lstsq(A, b, rcond=None)
            a, bb, _c = sol
            grad = np.array([a, bb])
            g = float(np.linalg.norm(grad))
            if g <= cfg.eps:
                continue
            u = grad / g                                   # 방향: 원 방식 그대로
            speed_plane = float(1.0 / g)                   # 원 속도(역수)

            # --- 역수 제거: 국소 집합을 û 축에 투영해 s-vs-t 회귀 ---
            P = np.array([[self.deaths[k][0], self.deaths[k][1]] for k in ids], dtype=float)
            s_axis = P @ u
            v_reg = theil_sen_slope(b, s_axis, cfg.eps)
            if v_reg is None or v_reg <= cfg.eps:
                v_reg = speed_plane                        # 축상 표본이 못 쓰면 원 값으로 폴백

            self.per_node[i] = {
                "dir": (float(u[0]), float(u[1])),
                "speed": float(v_reg),
                "speed_plane": speed_plane,
                # 도달예측용 기울기: 방향 불변 + 새 속도 반영
                "grad": (float(u[0] / v_reg), float(u[1] / v_reg)),
                "c": float(_c),
                "pos": (xi, yi),
                "t": ti,
            }

    def _fit_global(self) -> None:
        """방향은 **원래의 평면 속도**로 가중 — 새 속도가 방향 경로에 전혀 개입하지 않는다."""
        if not self.per_node:
            self.dir_global = None
            self.speed_global = None
            return
        acc = np.zeros(2)
        speeds = []
        for v in self.per_node.values():
            acc += v["speed_plane"] * np.array(v["dir"])   # ← 방향 가중치는 원 방식 고정
            speeds.append(v["speed"])                      # ← 속도 집계는 새 방식
        norm = float(np.linalg.norm(acc))
        self.dir_global = (float(acc[0] / norm), float(acc[1] / norm)) if norm > self.cfg.eps else None
        self.speed_global = float(np.median(speeds))
