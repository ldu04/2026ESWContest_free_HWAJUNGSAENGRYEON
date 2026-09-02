"""metrics.py — 정량 지표 수집·요약 (지시서 #1 §7).

매 틱 스냅샷을 받아 보고서/발표용 수치를 모은다:
  전달률, 재라우팅 지연, 방향오차(deg), 속도오차(%), 도달예측 오차(s),
  오탐률/미탐지연. 요약은 CSV로 저장.
"""
from __future__ import annotations

import csv
import math
import os

import numpy as np

from .node import NodeState


def angle_deg(u, v) -> float:
    """두 2D 벡터 사이 각(도), 0~180."""
    u = np.array(u, dtype=float)
    v = np.array(v, dtype=float)
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    if nu == 0 or nv == 0:
        return float("nan")
    c = float(np.clip(u @ v / (nu * nv), -1.0, 1.0))
    return math.degrees(math.acos(c))


class Metrics:
    def __init__(self, cfg, fire=None):
        self.cfg = cfg
        self.fire = fire
        self.rows: list[dict] = []          # 시계열
        self.gen_total = 0
        self.del_total = 0

    def record(self, t, nodes, packets, deaths, est, fire, net=None, verifier=None) -> None:
        self.gen_total += packets["generated"]
        self.del_total += packets["delivered"]
        delivery_rate = (self.del_total / self.gen_total) if self.gen_total else 1.0

        n_dead = sum(1 for nd in nodes if nd.state == NodeState.DEAD)

        dir_err = float("nan")
        speed_err = float("nan")
        arrival_err = float("nan")

        if est and est.get("dir") is not None:
            dir_err = angle_deg(est["dir"], self.cfg.direction())
            if est.get("speed"):
                speed_err = abs(est["speed"] - self.cfg.speed_true) / self.cfg.speed_true * 100.0

        # 도달예측 오차: 아직 살아있는 비-sink 노드에 대해 T_pred vs T_true 평균절대오차
        if est and est.get("dir") is not None and self.fire is not None:
            from .estimator import Estimator  # 타입 힌트용(런타임 무해)
            errs = []
            predictor = est.get("_predictor")
            for nd in nodes:
                if nd.is_sink or nd.state == NodeState.DEAD:
                    continue
                if predictor is not None:
                    tp = predictor.predict_arrival(nd.pos)
                    if tp is not None:
                        errs.append(abs(tp - self.fire.T_true(nd.pos)))
            if errs:
                arrival_err = float(np.mean(errs))

        self.rows.append({
            "t": round(t, 3),
            "n_dead": n_dead,
            "delivery_rate": round(delivery_rate, 4),
            "dir_err_deg": None if math.isnan(dir_err) else round(dir_err, 3),
            "speed_err_pct": None if math.isnan(speed_err) else round(speed_err, 3),
            "arrival_err_s": None if math.isnan(arrival_err) else round(arrival_err, 3),
            "n_alerts": len(est["alerts"]) if est else 0,
        })

    # --- 요약 ---
    def summary(self, net=None, verifier=None) -> dict:
        def last_valid(key):
            for r in reversed(self.rows):
                if r[key] is not None:
                    return r[key]
            return None

        reroute = net.reroute_delays_ms if net else []
        n_conf = len(verifier.confirm_log) if verifier else 0
        fp = verifier.false_positives if verifier else 0

        # 미탐지연: 확정시각 - 실제 사망시각 (평균)
        detect_lag = []
        if verifier:
            for log in verifier.confirm_log:
                if log["true_death_t"] is not None:
                    detect_lag.append(log["t_confirm"] - log["true_death_t"])

        return {
            "mode": self.cfg.mode,
            "n_nodes": self.cfg.n_nodes(),
            "final_delivery_rate": self.rows[-1]["delivery_rate"] if self.rows else None,
            "final_dir_err_deg": last_valid("dir_err_deg"),
            "final_speed_err_pct": last_valid("speed_err_pct"),
            "final_arrival_err_s": last_valid("arrival_err_s"),
            "reroute_delay_ms_mean": round(float(np.mean(reroute)), 2) if reroute else None,
            "reroute_delay_ms_max": round(float(np.max(reroute)), 2) if reroute else None,
            "confirmed_deaths": n_conf,
            "false_positives": fp,
            "false_positive_rate": round(fp / n_conf, 4) if n_conf else 0.0,
            "detect_lag_s_mean": round(float(np.mean(detect_lag)), 3) if detect_lag else None,
        }

    def write_timeseries_csv(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fields = ["t", "n_dead", "delivery_rate", "dir_err_deg",
                  "speed_err_pct", "arrival_err_s", "n_alerts"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(self.rows)

    def summarize(self, path: str | None = None, net=None, verifier=None) -> dict:
        s = self.summary(net, verifier)
        if path:
            self.write_timeseries_csv(path)
        return s
