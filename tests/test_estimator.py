"""test_estimator.py — 알려진 화재 벡터로 추정 정확도 검증 (지시서 #1 §6.5, §11 DoD).

무노이즈: 방향오차 < 5°, 속도오차 < 10%.
노이즈: 완화된 허용치 안에 드는지(강건성).
전 과정 시뮬레이션(Engine)에서도 DoD 충족을 확인.
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.config import Config
from sim.network import build_grid, Network
from sim.fire import Fire
from sim.estimator import Estimator
from sim.engine import Engine
from sim.metrics import angle_deg


def _synth_deaths(cfg, noise_std=0.0, seed=0):
    """격자 노드에 참 도착시각 T_true를 부여해 사망표본 합성."""
    nodes = build_grid(cfg)
    net = Network(nodes, cfg)
    fire = Fire(cfg, nodes)
    rng = np.random.default_rng(seed)
    deaths = []
    for nd in nodes:
        if nd.is_sink:
            continue
        t_true = fire.T_true(nd.pos)
        if t_true < 0:
            continue  # 전선 시작 이전(사실상 없음)
        t_obs = t_true + (rng.normal(0, noise_std) if noise_std > 0 else 0.0)
        deaths.append({"id": nd.id, "pos": nd.pos, "death_t_est": t_obs, "last_temp": 300})
    return net, deaths


def test_direction_speed_no_noise():
    cfg = Config(grid_rows=5, grid_cols=5, theta_deg=30.0, speed_true=1.5)
    net, deaths = _synth_deaths(cfg, noise_std=0.0)
    est = Estimator(cfg, neighbors=net.neighbors)
    out = est.update(deaths, t=100.0)

    assert out["dir"] is not None, "전역 방향 추정이 나와야 함"
    dir_err = angle_deg(out["dir"], cfg.direction())
    speed_err = abs(out["speed"] - cfg.speed_true) / cfg.speed_true * 100.0

    assert dir_err < 5.0, f"방향오차 {dir_err:.3f}° ≥ 5°"
    assert speed_err < 10.0, f"속도오차 {speed_err:.3f}% ≥ 10%"


@pytest.mark.parametrize("theta", [0.0, 30.0, 45.0, 75.0, 120.0])
def test_direction_various_angles_no_noise(theta):
    cfg = Config(grid_rows=6, grid_cols=6, theta_deg=theta, speed_true=2.0)
    net, deaths = _synth_deaths(cfg, noise_std=0.0)
    est = Estimator(cfg, neighbors=net.neighbors)
    out = est.update(deaths, t=100.0)
    assert out["dir"] is not None
    dir_err = angle_deg(out["dir"], cfg.direction())
    speed_err = abs(out["speed"] - cfg.speed_true) / cfg.speed_true * 100.0
    assert dir_err < 5.0, f"θ={theta}: 방향오차 {dir_err:.3f}°"
    assert speed_err < 10.0, f"θ={theta}: 속도오차 {speed_err:.3f}%"


def test_direction_speed_with_noise():
    # 측정 노이즈(σ=0.3s) 하에서도 완화 허용치 안에 들어야 함.
    cfg = Config(grid_rows=6, grid_cols=6, theta_deg=30.0, speed_true=1.5)
    net, deaths = _synth_deaths(cfg, noise_std=0.3, seed=7)
    est = Estimator(cfg, neighbors=net.neighbors)
    out = est.update(deaths, t=100.0)
    assert out["dir"] is not None
    dir_err = angle_deg(out["dir"], cfg.direction())
    speed_err = abs(out["speed"] - cfg.speed_true) / cfg.speed_true * 100.0
    assert dir_err < 12.0, f"노이즈 방향오차 {dir_err:.3f}°"
    assert speed_err < 25.0, f"노이즈 속도오차 {speed_err:.3f}%"


def test_eta_prediction_monotone():
    """도달예측: 전선 진행 방향 앞쪽 점일수록 ETA가 크다(단조)."""
    cfg = Config(grid_rows=6, grid_cols=6, theta_deg=0.0, speed_true=1.5)
    net, deaths = _synth_deaths(cfg, noise_std=0.0)
    est = Estimator(cfg, neighbors=net.neighbors)
    est.update(deaths, t=0.0)
    near = est.predict_arrival((10.0, 20.0))
    far = est.predict_arrival((40.0, 20.0))   # θ=0 → x 클수록 늦게 도달
    assert near is not None and far is not None
    assert far > near


def test_full_simulation_meets_dod():
    """전 과정 시뮬레이션(Engine)에서 방향<5°, 속도<10% 충족(무노이즈 화재)."""
    cfg = Config(mode="ours", wind_noise_deg=0.0)
    eng = Engine(cfg)
    last = None
    for snap in eng.stream():
        last = snap
    s = eng.summarize()
    assert s["final_dir_err_deg"] is not None
    assert s["final_dir_err_deg"] < 5.0, s
    assert s["final_speed_err_pct"] < 10.0, s
    assert s["false_positive_rate"] == 0.0, "무노이즈+낮은 dropout에서 오탐 0 기대"


def test_stock_mode_has_no_estimate():
    """stock 모드는 연결성만 — 추정(est) 없음."""
    cfg = Config(mode="stock")
    eng = Engine(cfg)
    last = None
    for snap in eng.stream():
        last = snap
    assert last is not None
    assert last["est"] is None
    s = eng.summarize()
    assert s["final_dir_err_deg"] is None
    assert s["final_delivery_rate"] is not None  # 전달률은 나옴
