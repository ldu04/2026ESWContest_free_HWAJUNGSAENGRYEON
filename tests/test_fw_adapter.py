"""test_fw_adapter.py — 펌웨어↔게이트웨이 어댑터 단위테스트 [2.K §2].

제약 4개를 **테스트로 고정**한다. 특히 ④(fake 통과)는 지시서가 "여기서 가장 잘 죽는다"고
지목한 지점이라 **여러 각도로** 잠근다.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# ★ ROOT/gateway 를 sys.path에 넣으면 `gateway/gateway.py` 가 **패키지 `gateway` 를 가린다**.
#   (import gateway → 디렉터리가 아니라 그 파일로 해석됨) 그래서 여기서는 넣지 않고
#   패키지 경로로만 임포트한다.

from gateway.fw_adapter import FirmwareAdapter          # noqa: E402
from gateway.mock_fw_serial import generate             # noqa: E402

DEPLOY = os.path.join(ROOT, "gateway", "deploy_config.json")


def _adapt(lines, **kw):
    ad = FirmwareAdapter.from_file(DEPLOY, **kw)
    out = []
    for ln in lines:
        out += ad.feed(ln)
    out += ad.flush()
    return [json.loads(o) for o in out], ad


def _gateway_run(fw_lines):
    """어댑터 → 게이트웨이 전 구간. 게이트웨이 인스턴스를 돌려준다."""
    from gateway.gateway import Gateway
    msgs, ad = _adapt(fw_lines)
    gw = Gateway()
    for m in msgs:
        gw.feed(json.dumps(m))
    return gw, ad, msgs


# ────────────────────────── 기본 변환 ──────────────────────────
def test_meta_is_emitted_before_any_frame():
    """게이트웨이는 META로 Config를 만든다 — 그게 없으면 cfg=None으로 터진다."""
    msgs, _ = _adapt(list(generate(DEPLOY, fake=0, t_max=10.0)))
    types = [m["type"] for m in msgs]
    assert types[0] == "META"
    assert "TICK" in types
    assert types.index("META") < types.index("TICK")


def test_frames_are_actually_produced():
    """[D-046]이 남긴 증상 = '실보드를 물리면 프레임 0개'. 그게 해소됐는지."""
    gw, _ad, _ = _gateway_run(list(generate(DEPLOY, fake=0)))
    assert len(gw.frames) > 0, "어댑터를 거쳤는데도 프레임이 0개면 접합이 안 된 것"


def test_estimator_produces_a_direction():
    gw, _ad, _ = _gateway_run(list(generate(DEPLOY, fake=0)))
    assert gw.frames[-1]["est"] is not None
    assert gw.frames[-1]["est"]["dir"] is not None, "사망이 쌓였는데 방향이 안 나오면 배관 불량"


def test_non_json_banner_lines_are_ignored():
    """부팅 배너(별표 줄)가 섞여도 죽지 않아야 한다."""
    lines = ["***** WARNING *****", "", "쓰레기", *generate(DEPLOY, fake=0, t_max=10.0)]
    msgs, ad = _adapt(lines)
    assert msgs and ad.n_lines > 0


# ────────────────────── 제약② 좌표는 deploy_config ──────────────────────
def test_coords_come_from_deploy_config_not_firmware():
    """펌웨어가 (0,0) 같은 쓰레기 좌표를 보내도 어댑터는 배치 파일 값을 쓴다."""
    fw = [
        json.dumps({"type": "HB", "id": 5, "x": 0.0, "y": 0.0, "temp": 30.0,
                    "nt": 100.0, "st": "ALIVE", "fake": 0}),
        json.dumps({"type": "LG", "id": 5, "x": 0.0, "y": 0.0, "temp": 85.0,
                    "nt": 101.0, "st": "DYING", "fake": 0}),
        json.dumps({"type": "DC", "id": 5, "x": 0.0, "y": 0.0,
                    "death_t_est": 999.0, "last_temp": 85.0, "nt": 105.0, "fake": 0}),
    ]
    msgs, _ = _adapt(fw)
    dc = next(m for m in msgs if m["type"] == "DC")
    with open(DEPLOY, encoding="utf-8") as f:
        want = next(n for n in json.load(f)["nodes"] if n["id"] == 5)
    assert (dc["x"], dc["y"]) == (want["x"], want["y"])
    assert (dc["x"], dc["y"]) != (0.0, 0.0)


def test_unknown_node_id_is_dropped_not_guessed():
    """배치 파일에 없는 ID는 좌표를 모른다 → 추측하지 말고 버려야 한다."""
    fw = [json.dumps({"type": "DC", "id": 999, "x": 1.0, "y": 2.0,
                      "death_t_est": 5.0, "nt": 5.0, "fake": 0})]
    msgs, ad = _adapt(fw)
    assert not [m for m in msgs if m["type"] == "DC"]
    assert 999 in ad.unknown_ids


# ────────────────────── 제약③ 시각은 노드 각인 ──────────────────────
def test_death_time_uses_node_stamp_not_root_confirm_time():
    """루트 확정 시각(통신·집계 지연 포함)이 아니라 LG의 자기 각인 시각을 써야 한다."""
    fw = [
        json.dumps({"type": "HB", "id": 5, "temp": 30.0, "nt": 100.0,
                    "st": "ALIVE", "fake": 0}),
        json.dumps({"type": "LG", "id": 5, "temp": 85.0, "nt": 101.5,
                    "st": "DYING", "fake": 0}),
        # 루트는 8.5초나 늦게 확정했다 — 이 값이 새어들면 안 된다
        json.dumps({"type": "DC", "id": 5, "death_t_est": 110.0, "nt": 110.0, "fake": 0}),
    ]
    msgs, _ = _adapt(fw)
    dc = next(m for m in msgs if m["type"] == "DC")
    assert dc["t_source"] == "last_gasp_node_stamp"
    # t0 = 첫 노드각인(100.0) → LG 101.5 는 상대 1.5 초
    assert dc["death_t_est"] == pytest.approx(1.5, abs=1e-6)
    assert dc["death_t_est"] != pytest.approx(10.0, abs=1e-6)   # 루트 확정 시각이 아님


def test_falls_back_to_heartbeat_stamp_when_last_gasp_lost():
    """LG를 못 받았으면 그 노드의 마지막 자기 각인(HB)으로 — 여전히 노드 각인이다."""
    fw = [
        json.dumps({"type": "HB", "id": 5, "temp": 30.0, "nt": 100.0, "fake": 0}),
        json.dumps({"type": "HB", "id": 5, "temp": 55.0, "nt": 103.0, "fake": 0}),
        json.dumps({"type": "DC", "id": 5, "death_t_est": 120.0, "nt": 120.0, "fake": 0}),
    ]
    msgs, _ = _adapt(fw)
    dc = next(m for m in msgs if m["type"] == "DC")
    assert dc["t_source"] == "last_heartbeat_node_stamp"
    assert dc["death_t_est"] == pytest.approx(3.0, abs=1e-6)


def test_local_millis_only_stream_is_flagged():
    """`nt`가 없고 `t`(로컬 millis)뿐이면 — 돌아가되 **경고를 남겨야** 한다."""
    fw = [
        json.dumps({"type": "HB", "id": 5, "temp": 30.0, "t": 10.0, "fake": 0}),
        json.dumps({"type": "LG", "id": 5, "temp": 85.0, "t": 12.0, "fake": 0}),
        json.dumps({"type": "DC", "id": 5, "death_t_est": 20.0, "t": 20.0, "fake": 0}),
    ]
    _msgs, ad = _adapt(fw)
    assert ad.report()["time_source"] == "local_millis"
    assert any("비교" in w for w in ad.report()["warnings"])


def test_tick_time_is_node_stamped_and_monotonic():
    msgs, _ = _adapt(list(generate(DEPLOY, fake=0)))
    ts = [m["t"] for m in msgs if m["type"] == "TICK"]
    assert ts == sorted(ts)
    assert ts[0] == pytest.approx(0.0)          # 첫 노드 각인 기준 상대시간


# ══════════════════ 제약④ fake 통과 — 안전장치의 생명선 ══════════════════
def test_fake_survives_adapter_into_dc():
    """★핵심: fake=1 입력이 어댑터를 통과해 DC에 남는가."""
    fw = [
        json.dumps({"type": "MODE", "fake": 1, "src": "FAKE_TEMP_RAMP"}),
        json.dumps({"type": "HB", "id": 5, "temp": 30.0, "nt": 100.0, "fake": 1}),
        json.dumps({"type": "LG", "id": 5, "temp": 85.0, "nt": 101.0, "fake": 1}),
        json.dumps({"type": "DC", "id": 5, "death_t_est": 105.0, "nt": 105.0, "fake": 1}),
    ]
    msgs, ad = _adapt(fw)
    dc = next(m for m in msgs if m["type"] == "DC")
    assert dc["fake"] == 1
    assert ad.session_fake == 1


def test_fake_survives_all_the_way_into_gateway_log():
    """★★ 지시서 제약④ 본문: fake=1 입력 → **최종 게이트웨이 로그**에 fake=1이 남는가.

    여기가 안전장치가 죽기 가장 쉬운 자리다 — estimator로 가는 dict에는 fake 자리가 없다.
    """
    gw, _ad, _ = _gateway_run(list(generate(DEPLOY, fake=1)))
    assert gw.death_log, "사망 대장이 비면 검증 자체가 성립하지 않는다"
    assert all(d["fake"] == 1 for d in gw.death_log)
    assert gw.session_fake == 1


def test_fake_appears_as_a_column_in_the_written_csv(tmp_path):
    """지시서: '게이트웨이 로그에도 **컬럼으로** 남아야 한다'."""
    import csv
    gw, _ad, _ = _gateway_run(list(generate(DEPLOY, fake=1)))
    p = gw.write_death_log(str(tmp_path / "deaths.csv"))
    with open(p, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows, "CSV가 비었다"
    assert "fake" in rows[0], "fake가 컬럼으로 없다 → 안전장치가 로그에서 죽었다"
    assert all(r["fake"] == "1" for r in rows)


def test_real_sensor_stream_stays_fake_zero():
    """반대 방향도 잠근다 — 실센서(fake=0)를 합성으로 오염시키면 안 된다."""
    gw, _ad, _ = _gateway_run(list(generate(DEPLOY, fake=0)))
    assert gw.session_fake == 0
    assert all(d["fake"] == 0 for d in gw.death_log)


def test_a_single_fake_line_contaminates_the_session():
    """안전측 규약: 한 줄이라도 합성이면 세션 전체를 합성으로 본다(표시는 내려가지 않는다)."""
    fw = list(generate(DEPLOY, fake=0))
    fw.insert(5, json.dumps({"type": "HB", "id": 7, "temp": 40.0, "nt": 1000.0, "fake": 1}))
    gw, ad, _ = _gateway_run(fw)
    assert ad.session_fake == 1
    assert gw.session_fake == 1


def test_fake_flag_never_downgrades_per_node():
    """합성으로 한 번 표시된 노드가 이후 fake=0 줄로 표시를 지울 수 없어야 한다."""
    fw = [
        json.dumps({"type": "HB", "id": 5, "temp": 30.0, "nt": 100.0, "fake": 1}),
        json.dumps({"type": "HB", "id": 5, "temp": 40.0, "nt": 101.0, "fake": 0}),
        json.dumps({"type": "LG", "id": 5, "temp": 85.0, "nt": 102.0, "fake": 0}),
        json.dumps({"type": "DC", "id": 5, "death_t_est": 105.0, "nt": 105.0, "fake": 0}),
    ]
    msgs, _ = _adapt(fw)
    dc = next(m for m in msgs if m["type"] == "DC")
    assert dc["fake"] == 1


# ────────────────────── 제약① estimator 불변 ──────────────────────
def test_estimator_source_is_untouched():
    """어댑터 작업이 estimator.py를 건드리지 않았음을 구조적으로 확인.

    (내용 해시가 아니라 '어댑터가 estimator를 import해 그대로 쓰는가'를 본다.)
    """
    import inspect
    from sim.estimator import Estimator
    src = inspect.getsource(Estimator)
    assert "fake" not in src, "estimator에 fake가 들어갔다면 제약① 위반"
    assert "deploy" not in src, "estimator에 배치 개념이 들어갔다면 제약① 위반"


def test_adapter_does_not_import_or_wrap_estimator():
    """변환은 어댑터 안에서만 — 어댑터가 estimator를 만지지 않는다."""
    import gateway.fw_adapter as fa
    src = open(fa.__file__, encoding="utf-8").read()
    assert "Estimator" not in src
