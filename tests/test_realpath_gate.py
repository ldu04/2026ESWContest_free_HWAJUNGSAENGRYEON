"""test_realpath_gate.py — 실물 경로의 화재/비화재 선별 [2.M P1·P2].

[D-053]이 드러낸 것: 펌웨어는 #2d 이전 OR 게이트고 `gateway.py`는 `Verifier`를 아예 안 써서
DC가 estimator로 **무선별 직행**했다 — 실물에 선별이 0이었다. 여기서 그걸 메운 결과를 고정한다.

★ 이 테스트가 지키는 것
  (a) 진짜 화재사망은 **통과**한다
  (b) 비화재 침묵(저온)은 **걸러진다**
  (c) LG 없는 침묵은 **무조건 기각되지 않는다** ← [P2] 비대칭 규칙의 핵심
  (d) LG는 **구제만** 하고 **기각하지 않는다**(대칭 규칙이면 미탐지가 생긴다)
  (e) `fake`가 여전히 최종 로그까지 살아남는다 (2.K §2 제약④ 회귀)
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gateway.fw_adapter import FirmwareAdapter        # noqa: E402
from gateway.mock_fw_serial import generate           # noqa: E402
from gateway.gateway import Gateway                   # noqa: E402

DEPLOY = os.path.join(ROOT, "gateway", "deploy_config.json")


def run(fw_lines):
    ad = FirmwareAdapter.from_file(DEPLOY)
    gw = Gateway()
    for ln in fw_lines:
        for out in ad.feed(ln):
            gw.feed(out)
    for out in ad.flush():
        gw.feed(out)
    return gw, ad


def by_id(gw):
    return {int(d["id"]): d for d in gw.death_log}


def hb(nid, temp, nt, st="ALIVE", fake=0):
    return json.dumps({"type": "HB", "id": nid, "temp": temp, "nt": nt, "st": st, "fake": fake})


def lg(nid, temp, nt, fake=0):
    return json.dumps({"type": "LG", "id": nid, "temp": temp, "nt": nt, "st": "DYING",
                       "fake": fake})


def dc(nid, nt, last_temp, fake=0):
    return json.dumps({"type": "DC", "id": nid, "death_t_est": nt, "last_temp": last_temp,
                       "nt": nt, "fake": fake})


# ────────────────── (a)(b) 통과와 차단 ──────────────────
def test_real_fire_death_passes_and_cold_nonfire_is_filtered():
    """합성 스트림에 (a)화재사망·(b)비화재 침묵을 섞어 흘린다."""
    gw, _ = run(list(generate(DEPLOY, fake=0, nonfire_ids=(12, 15))))
    d = by_id(gw)
    assert d, "사망 후보가 하나도 없으면 검증이 성립하지 않는다"
    # (b) 주입한 비화재 노드는 걸러져야 한다
    for nid in (12, 15):
        if nid in d:
            assert d[nid]["accepted"] == 0, f"비화재 노드 {nid}가 통과했다: {d[nid]['branch']}"
    # (a) 화재로 죽은 나머지는 통과해야 한다
    fire = [v for k, v in d.items() if k not in (12, 15)]
    assert fire and all(v["accepted"] == 1 for v in fire)


def test_estimator_only_receives_accepted_deaths():
    gw, _ = run(list(generate(DEPLOY, fake=0, nonfire_ids=(12, 15))))
    n_acc = sum(x["accepted"] for x in gw.death_log)
    assert len(gw.estimator.deaths) == n_acc
    assert gw.n_excluded == len(gw.death_log) - n_acc


def test_gate_actually_excludes_something():
    """선별이 '전부 통과'로 무력화돼 있지 않은지 — 게이트가 존재한다는 최소 증거."""
    gw, _ = run(list(generate(DEPLOY, fake=0, nonfire_ids=(12, 15))))
    assert gw.n_excluded > 0


# ────────────────── (c)(d) ★ P2 비대칭 규칙 ──────────────────
def test_missing_last_gasp_alone_never_rejects():
    """(c) LG를 못 받았다는 것만으로 기각되면 **진짜 화재를 버린다**(미탐지).

    노드 5의 LG 줄만 유실시킨다. 온도 이력(rep_peak)은 여전히 뜨거우므로 통과해야 한다.
    """
    gw, _ = run(list(generate(DEPLOY, fake=0, drop_lg_ids=(5,))))
    d = by_id(gw)
    assert 5 in d, "노드 5가 후보에 없으면 검증 불가"
    assert d[5]["had_last_gasp"] == 0
    assert d[5]["accepted"] == 1, "LG 없다고 기각했다 — 대칭 규칙이 돼버렸다"
    assert d[5]["branch"] == "branch1_self_hot"


def test_last_gasp_rescues_when_temperature_history_is_lost():
    """LG는 **구제**한다 — rep_peak이 유실돼 저온으로 보이는데 LG는 받은 경우.

    LG 없으면 branch2(양쪽 저온)로 기각될 상황인데, LG가 있으면 채택돼야 한다.
    """
    cold = [hb(5, 30.0, 100.0), hb(5, 31.0, 101.0)]
    warm_lg = cold + [lg(5, 32.0, 102.0)]          # 온도는 낮게 보고됐지만 LG는 왔다
    gw_no, _ = run(cold + [dc(5, 103.0, 31.0)])
    gw_lg, _ = run(warm_lg + [dc(5, 103.0, 31.0)])
    a, b = by_id(gw_no)[5], by_id(gw_lg)[5]
    assert a["accepted"] == 0 and a["branch"] == "branch2_both_cold"
    assert b["accepted"] == 1 and b["branch"] == "branch1_last_gasp"


def test_last_gasp_is_never_used_to_reject():
    """비대칭성의 반대편: LG 유무가 **같은 조건에서 기각을 만들어내지 않는다.**

    뜨거운 노드 두 개를 LG 유무만 다르게 두고, 둘 다 통과하는지 본다.
    """
    base = [hb(5, 95.0, 100.0), hb(6, 95.0, 100.0)]
    stream = base + [lg(5, 96.0, 101.0), dc(5, 101.0, 96.0), dc(6, 101.0, 96.0)]
    gw, _ = run(stream)
    d = by_id(gw)
    assert d[5]["had_last_gasp"] == 1 and d[5]["accepted"] == 1
    assert d[6]["had_last_gasp"] == 0 and d[6]["accepted"] == 1


def test_battery_death_is_not_rescued_by_last_gasp_rule():
    """배터리·크래시 사망은 애초에 LG를 못 보내므로 이 규칙으로 구제되지 않는다."""
    gw, _ = run(list(generate(DEPLOY, fake=0, nonfire_ids=(15,))))
    d = by_id(gw)
    if 15 in d:
        assert d[15]["had_last_gasp"] == 0
        assert d[15]["accepted"] == 0


# ────────────────── 규칙이 시뮬과 같은 것인지 ──────────────────
def test_gateway_uses_the_same_verifier_as_sim():
    """새 방어를 발명하지 않았다 — 시뮬과 **같은 클래스·같은 판정부**를 쓴다."""
    import inspect
    from sim.verification import Verifier
    import gateway.gateway as g
    assert "Verifier" in inspect.getsource(g)
    src = inspect.getsource(Verifier._classify)
    for token in ("branch1_self_hot", "branch2_both_cold", "branch3_residual",
                  "branch3_sample_poor"):
        assert token in src


def test_deployed_defaults_are_the_2d_rule():
    """배포판 기본 방어가 #2d 3분기 + #2e-2 Fix A인지 고정."""
    from sim.config import Config
    c = Config()
    assert c.nonfire_gate is True            # 3분기 선별
    assert c.nonfire_strict_gate is True     # Fix A [D-036]
    assert c.dtdt_gate is False              # Fix B는 비활성
    assert c.residual_gate_s == 2.0
    assert c.warn_temp == 60.0
    assert c.lastgasp_evidence is False      # 시뮬 기본은 꺼짐(실물에서만 켠다)


def test_sim_path_is_unchanged_by_the_refactor():
    """리팩터 후에도 시뮬 회귀가 IDENTICAL인지 — 판정부를 옮긴 게 시뮬을 바꾸지 않았다."""
    from sim.config import Config
    from sim.engine import Engine
    eng = Engine(Config(mode="ours", seed=42))
    for _ in eng.stream():
        pass
    s = eng.summarize()
    assert s["final_dir_err_deg"] == 2.115
    assert s["final_speed_err_pct"] == 0.096
    assert s["false_positives"] == 0
    assert s["confirmed_deaths"] == 13


# ────────────────── 제약④ 회귀 ──────────────────
def test_fake_still_survives_to_the_final_log(tmp_path):
    """선별 계층이 생겨도 합성 표시는 로그 끝까지 남아야 한다 (2.K §2 제약④)."""
    import csv
    gw, _ = run(list(generate(DEPLOY, fake=1, nonfire_ids=(12,), drop_lg_ids=(5,))))
    assert gw.session_fake == 1
    assert gw.death_log and all(d["fake"] == 1 for d in gw.death_log)
    p = gw.write_death_log(str(tmp_path / "deaths.csv"))
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    assert "fake" in rows[0] and all(r["fake"] == "1" for r in rows)
    # 제외된 죽음도 대장에는 남아야 한다(감사 가능성)
    assert any(r["accepted"] == "0" for r in rows)


def test_decision_reason_is_logged_for_every_death():
    """왜 채택/제외됐는지가 모든 건에 남는가(사후 감사용)."""
    gw, _ = run(list(generate(DEPLOY, fake=0, nonfire_ids=(12, 15))))
    for d in gw.death_log:
        assert d["branch"] in ("branch1_self_hot", "branch1_last_gasp", "branch2_both_cold",
                               "branch3_residual", "branch3_sample_poor", "orgate")
        assert d["accepted"] in (0, 1)
