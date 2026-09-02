"""test_fw_adapter_nt_wrap.py — `nt` 랩어라운드 보정 고정.

왜 이 테스트가 있나:
  `mesh.getNodeTime()`은 uint32 마이크로초라 **2^32 µs = 4294.967296 s ≈ 71.58분**마다 0으로
  되감긴다(node.ino L85-86에 한계로 적혀 있었고, 처리 코드는 없었다).
  되감기면 `v - t0`가 음수가 되어 **사망 시각 순서가 통째로 뒤집힌다.** 값이 비는 게 아니라
  그럴듯한 숫자로 바뀌므로 **조용히 틀린다** — 데모 촬영이 71분을 넘으면 방향 추정이 무의미해진다.
  랩은 실물에서 71분마다 한 번만 일어나 재현이 어렵다. 그래서 단위 테스트로 못박는다.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gateway"))

from fw_adapter import FirmwareAdapter, NT_WRAP_S, NT_WRAP_GUARD_S  # noqa: E402


def _deploy():
    """최소 배치: 노드 2개(0=싱크, 1)."""
    return {
        "sink_id": 0,
        "config": {"ambient": 25.0},
        "nodes": [
            {"id": 0, "x": 0.0, "y": 0.0, "is_sink": True},
            {"id": 1, "x": 0.15, "y": 0.0, "is_sink": False},
        ],
    }


def _hb(nid, nt, temp=25.0, st="ALIVE"):
    return json.dumps({"type": "HB", "id": nid, "temp": temp, "st": st,
                       "nt": nt, "fake": 0})


def _times(ad, lines):
    """각 라인을 먹이고 그때의 상대 각인 시각을 모은다."""
    got = []
    for ln in lines:
        m = json.loads(ln)
        ad.feed(ln)
        got.append(ad._node_time(m))   # 같은 값 재조회(추적 갱신은 멱등하게 동작)
    return got


def test_wrap_does_not_go_backwards():
    """랩 경계를 넘어도 각인 시각이 단조 증가해야 한다."""
    ad = FirmwareAdapter(_deploy())
    # 랩 직전 → 직후. 원시값은 4294.9 → 0.1 로 되감긴다.
    raws = [4290.0, 4292.0, 4294.9, 0.1, 2.0, 4.0]
    out = []
    for r in raws:
        ad.feed(_hb(1, r))
        out.append(ad.last_seen_t[1])

    assert ad.nt_wraps == 1, "랩이 정확히 1회 감지돼야 한다"
    for a, b in zip(out, out[1:]):
        assert b > a, f"시각이 뒤로 갔다: {out}"
    # 랩 직전(4294.9)에서 주기 끝(4294.967296)까지 0.067296s가 남아 있으므로
    # 직후 0.1s 까지의 실제 경과는 0.067296 + 0.1 = 0.167296s 다.
    assert out[3] - out[2] == pytest.approx(NT_WRAP_S - 4294.9 + 0.1, abs=1e-6)


def test_wrap_free_stream_is_unchanged():
    """랩이 없으면 보정이 **아무 일도 하지 않아야** 한다(기존 동작 불변)."""
    ad = FirmwareAdapter(_deploy())
    raws = [10.0, 11.0, 12.5, 30.0, 100.0]
    for r in raws:
        ad.feed(_hb(1, r))
    assert ad.nt_wraps == 0
    assert ad._nt_epoch == 0.0
    assert ad.last_seen_t[1] == pytest.approx(100.0 - 10.0)


def test_small_reordering_is_not_mistaken_for_wrap():
    """수십 초 규모의 순서 뒤바뀜을 랩으로 오인하면 안 된다(임계가 범위의 절반인 이유)."""
    ad = FirmwareAdapter(_deploy())
    for r in [1000.0, 1005.0, 998.0, 1010.0]:   # 7s 역행
        ad.feed(_hb(1, r))
    assert ad.nt_wraps == 0


def test_late_packet_from_before_wrap_is_placed_before_it():
    """랩 직후 도착한 '랩 이전' 패킷은 한 주기를 빼서 제자리로 돌린다."""
    ad = FirmwareAdapter(_deploy())
    for r in [4294.0, 1.0]:                     # 랩 발생
        ad.feed(_hb(1, r))
    assert ad.nt_wraps == 1
    late = ad._unwrap_nt(4293.5, track=False)   # 랩 이전 시각
    now = ad._unwrap_nt(2.0, track=False)
    assert late < now, "지연 패킷이 랩 이후로 잘못 밀렸다"


def test_dc_death_time_survives_wrap():
    """랩 이후 확정된 DC의 사망시각이 음수로 뒤집히지 않아야 한다.

    자기 각인(LG/HB)이 하나도 없는 최악의 경로 — 펌웨어 death_t_est 폴백 — 를 친다.
    """
    ad = FirmwareAdapter(_deploy())
    ad.feed(_hb(0, 4294.0))                     # 싱크만 말한다(노드 1의 각인 없음)
    ad.feed(_hb(0, 1.0))                        # 랩
    assert ad.nt_wraps == 1

    dc = json.dumps({"type": "DC", "id": 1, "death_t_est": 2.5,
                     "t_source": "last_gasp_node_stamp", "last_temp": 88.0,
                     "rep_peak": 88.0, "had_last_gasp": 1, "fake": 0})
    outs = [json.loads(o) for o in ad.feed(dc)]
    dcs = [o for o in outs if o["type"] == "DC"]
    assert len(dcs) == 1
    t_death = dcs[0]["death_t_est"]
    assert t_death > 0, f"랩으로 사망시각이 뒤집혔다: {t_death}"
    # t0 = 4294.0(첫 각인). 랩 후 2.5초는 절대 4294.967296+2.5 → 상대 = 3.467296
    assert t_death == pytest.approx(NT_WRAP_S + 2.5 - 4294.0, abs=1e-3)


def test_wrap_constants():
    """상수가 uint32 µs 정의와 일치하는지 못박는다."""
    assert NT_WRAP_S == pytest.approx(4294.967296)
    assert NT_WRAP_GUARD_S == pytest.approx(NT_WRAP_S / 2)
