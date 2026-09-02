"""estimator.py — ★ Failure-Pattern(도착시각) 추정 (지시서 #1 §6). 이 프로젝트의 심장.

입력: verification이 확정한 사망 이벤트 D = {(x_i, y_i, t_i)}.
출력: ① 전선 진행 방향 단위벡터 ② 전선 속도(m/s) ③ 임의 지점 도달예측·ETA ④ 생존노드 잔여시간.

핵심 원리(부호 = 지시서 #1 §6.1 정본, [D-002]):
  도착시각장 T(x,y). 전선이 방향 n·속도 s면  ∇T = n/s.
  ⇒  방향 = ∇T/|∇T|,  속도 = 1/|∇T|.
"""
from __future__ import annotations

import numpy as np


class Estimator:
    def __init__(self, cfg, neighbors: dict[int, list[int]] | None = None):
        self.cfg = cfg
        self.neighbors = neighbors or {}
        # id -> (x, y, t_est)
        self.deaths: dict[int, tuple[float, float, float]] = {}
        # 마지막 전역 추정 캐시
        self.dir_global: tuple[float, float] | None = None
        self.speed_global: float | None = None
        self.per_node: dict[int, dict] = {}

    # --- 누적 & 갱신 ---
    def update(self, deaths: list[dict], t: float, survivors: list[tuple] | None = None) -> dict:
        """새 사망 이벤트를 누적하고 전역 추정을 갱신, est 스냅샷 반환.

        survivors: [(id, pos), ...] 생존 노드/대원 위치. 각자의 ETA·경보 산출용(§6.4).
        """
        for e in deaths:
            self.deaths[e["id"]] = (e["pos"][0], e["pos"][1], e["death_t_est"])

        self._fit_local()
        self._fit_global()

        alerts = self._alerts(survivors or [], t)

        return {
            "t": t,
            "n_deaths": len(self.deaths),
            "dir": self.dir_global,
            "speed": self.speed_global,
            "deaths": [(x, y, tt) for (x, y, tt) in self.deaths.values()],
            "per_node": {k: {"dir": v["dir"], "speed": v["speed"]}
                         for k, v in self.per_node.items()},
            "front_point": self._front_point(),
            "alerts": alerts,
        }

    # --- 6.2 국소 평면 최소제곱 ---
    def _fit_local(self) -> None:
        cfg = self.cfg
        self.per_node = {}
        for i, (xi, yi, ti) in self.deaths.items():
            # 지역집합 S_i = {i} ∪ {사망한 이웃 j : |t_j - t_i| ≤ dt_window}
            ids = [i]
            for j in self.neighbors.get(i, []):
                if j in self.deaths:
                    tj = self.deaths[j][2]
                    if abs(tj - ti) <= cfg.dt_window:
                        ids.append(j)
            if len(ids) < cfg.min_samples:
                continue  # 성긴 구간 → 추정 보류

            A = np.array([[self.deaths[k][0], self.deaths[k][1], 1.0] for k in ids])
            b = np.array([self.deaths[k][2] for k in ids])
            # 최소제곱 t ≈ a·x + b·y + c
            sol, *_ = np.linalg.lstsq(A, b, rcond=None)
            a, bb, _c = sol
            grad = np.array([a, bb])
            g = float(np.linalg.norm(grad))
            if g <= cfg.eps:
                continue
            self.per_node[i] = {
                "dir": (float(grad[0] / g), float(grad[1] / g)),
                "speed": float(1.0 / g),
                "grad": (float(a), float(bb)),
                "c": float(_c),
                "pos": (xi, yi),
                "t": ti,
            }

    # --- 6.3 전역 추정 ---
    def _fit_global(self) -> None:
        if not self.per_node:
            self.dir_global = None
            self.speed_global = None
            return
        # 방향: 속도 가중 평균 후 정규화
        acc = np.zeros(2)
        speeds = []
        for v in self.per_node.values():
            w = v["speed"]
            acc += w * np.array(v["dir"])
            speeds.append(v["speed"])
        norm = float(np.linalg.norm(acc))
        if norm > self.cfg.eps:
            self.dir_global = (float(acc[0] / norm), float(acc[1] / norm))
        else:
            self.dir_global = None
        # 속도: median(이상치에 강함)
        self.speed_global = float(np.median(speeds))

    # --- 6.4 도달예측 / ETA ---
    def predict_arrival(self, p) -> float | None:
        """점 p에 불이 도달할 예측 시각 T_pred(p). 가장 가까운 사망노드의 국소평면 외삽."""
        if not self.per_node:
            return None
        p = np.array(p, dtype=float)
        # per_node(국소 적합이 성공한 사망노드) 중 최근접
        best = None
        best_d = float("inf")
        for v in self.per_node.values():
            d = float(np.linalg.norm(p - np.array(v["pos"])))
            if d < best_d:
                best_d = d
                best = v
        if best is None:
            return None
        grad = np.array(best["grad"])
        return float(best["t"] + grad @ (p - np.array(best["pos"])))

    def eta(self, p, now: float) -> float | None:
        tp = self.predict_arrival(p)
        return None if tp is None else tp - now

    def _alerts(self, survivors: list[tuple], now: float) -> list[dict]:
        out = []
        for sid, pos in survivors:
            e = self.eta(pos, now)
            if e is not None and e <= self.cfg.alert_horizon:
                out.append({"id": sid, "pos": pos, "eta": round(e, 2)})
        return out

    def _front_point(self):
        if not self.deaths:
            return None
        pts = np.array([(x, y) for (x, y, _t) in self.deaths.values()])
        c = pts.mean(axis=0)
        return (float(c[0]), float(c[1]))
