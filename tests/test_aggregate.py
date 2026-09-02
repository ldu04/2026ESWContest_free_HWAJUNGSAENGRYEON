"""test_aggregate.py — 전역 집계 버전 분기 [2.N 추가-G].

★ 핵심 고정: `legacy` 모드가 `estimator.dir_global`과 **비트 동일**해야 한다.
  그래야 "estimator.py 불변 + 버전 분기"라는 원칙이 실제로 지켜진 것이다.
"""
import os, sys
import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sim.config import Config
from sim.engine import Engine
from sim.aggregate import aggregate_direction, all_modes, MODES


def _run(**kw):
    cfg = Config(mode="ours", **kw)
    eng = Engine(cfg)
    for _ in eng.stream():
        pass
    return eng, cfg


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_legacy_is_bit_identical_to_estimator(seed):
    eng, cfg = _run(seed=seed)
    lg = aggregate_direction(eng.estimator, cfg, "legacy")["dir"]
    assert lg is not None and eng.estimator.dir_global is not None
    assert np.max(np.abs(np.array(lg) - np.array(eng.estimator.dir_global))) == 0.0


def test_all_modes_return_unit_vectors():
    eng, cfg = _run(seed=42)
    for m, r in all_modes(eng.estimator, cfg).items():
        if r["dir"] is not None:
            assert abs(float(np.linalg.norm(r["dir"])) - 1.0) < 1e-9, m


def test_n_eff_is_bounded_by_sample_count():
    """유효표본수는 1 이상 n 이하여야 한다(Kish)."""
    eng, cfg = _run(seed=42)
    n = len(eng.estimator.per_node)
    for m in ("legacy", "uniform", "invvar"):
        r = aggregate_direction(eng.estimator, cfg, m)
        if r["n_eff"] is not None:
            assert 1.0 - 1e-9 <= r["n_eff"] <= n + 1e-9, (m, r["n_eff"], n)


def test_uniform_weighting_gives_n_eff_equal_n():
    eng, cfg = _run(seed=42)
    r = aggregate_direction(eng.estimator, cfg, "uniform")
    assert r["n_eff"] == pytest.approx(len(eng.estimator.per_node), rel=1e-9)


def test_default_mode_is_invvar():
    """★[D-063] 기본 집계를 invvar로 전환했음을 고정."""
    from sim.aggregate import DEFAULT_MODE
    eng, cfg = _run(seed=42)
    assert DEFAULT_MODE == "invvar"
    assert aggregate_direction(eng.estimator, cfg)["mode"] == "invvar"


def test_no_silent_fallback_to_legacy():
    """★폴백 없음 — invvar가 값을 못 내면 grade=INSUFFICIENT 여야 한다.

    legacy로 조용히 되돌아가면 '가중 폭주' 실패가 다시 숨는다.
    """
    from sim.aggregate import aggregate_direction as agg
    import sim.aggregate as A

    class _Fake:                      # 전 적합이 DOF<1 인 상황을 강제
        per_node = {1: {"dir": (1.0, 0.0), "speed": 1.0, "pos": (0.0, 0.0), "t": 0.0}}
        deaths = {1: (0.0, 0.0, 0.0)}
        neighbors = {1: []}
    eng, cfg = _run(seed=42)
    r = agg(_Fake(), cfg)             # 기본 = invvar
    assert r["mode"] == "invvar"
    assert r["dir"] is None
    assert r["grade"] == A.INSUFFICIENT
    assert "DOF" in r["reason"] or "가중" in r["reason"]


def test_n_eff_is_always_paired_with_raw_n():
    """★n_eff 단독 표기 금지 — 원표본수 n_local이 항상 함께 나와야 한다."""
    eng, cfg = _run(seed=42)
    for m in MODES:
        r = aggregate_direction(eng.estimator, cfg, m)
        assert "n_local" in r and r["n_local"] == len(eng.estimator.per_node)
        if r["n_eff"] is not None:
            assert r["n_eff_frac"] is not None


def test_speed_median_aggregation_untouched():
    """★속도의 median 집계는 통제군 — estimator 안에 그대로 있어야 한다."""
    import inspect, numpy as np
    from sim.estimator import Estimator
    assert "np.median(speeds)" in inspect.getsource(Estimator._fit_global)
    eng, cfg = _run(seed=42)
    sp = [v["speed"] for v in eng.estimator.per_node.values()]
    assert eng.estimator.speed_global == pytest.approx(float(np.median(sp)))


def test_fake_temp_ramp_defaults_to_zero():
    """★[D-063] 제출물 경로에 합성 데이터가 들어갈 여지를 기본값으로 막는다."""
    import re
    h = open(os.path.join(ROOT, "firmware", "node", "config.h"), encoding="utf-8").read()
    m = re.search(r"#define\s+FAKE_TEMP_RAMP\s+(\d+)", h)
    assert m and m.group(1) == "0"


def test_estimator_source_untouched_by_aggregate():
    """집계 모듈이 estimator를 수정하지 않는다."""
    import inspect
    from sim.estimator import Estimator
    src = inspect.getsource(Estimator)
    for token in ("aggregate", "invvar", "n_eff", "adequacy"):
        assert token not in src


def test_residual_min_samples_default_is_four():
    """[추가-I] 채택 고정 — DOF≥1 이라야 잔차가 판별력을 갖는다."""
    assert Config().residual_min_samples == 4


def test_regression_still_identical():
    eng, _cfg = _run(seed=42)
    s = eng.summarize()
    assert s["final_dir_err_deg"] == 2.115
    assert s["final_speed_err_pct"] == 0.096
    assert s["false_positives"] == 0
    assert s["confirmed_deaths"] == 13
