"""mock_fw_serial.py — **node.ino 방언**(HB/LG/ST/DV/DC/MODE) 합성 스트림 생성 [2.K §2].

`mock_serial.py`와 다른 점: 저건 **게이트웨이 방언**(META/NODES/TICK…)을 만든다 — 즉 어댑터를
건너뛴다. 실보드가 실제로 뱉는 것은 **펌웨어 방언**이므로, 어댑터를 검증하려면 그쪽을 흉내내야 한다.

★ 이 파일이 재현하는 것은 **물리가 아니라 프로토콜**이다.
  목적은 "어댑터+게이트웨이 배관이 실보드 형식에서 도는가"를 보드 없이 확인하는 것뿐이다.
  온도 모델은 벤치 격자(0.15 m)에 맞춘 단순 선형 전선이며 **화재 물리의 근거로 쓰면 안 된다.**
  (그 역할은 sim/ 이 한다. 여기서 나온 방향오차를 성능 수치로 인용 금지.)

★ `fake` 는 인자로 받아 **모든 줄에** 박는다 — [D-046] 안전장치를 어댑터가 통과시키는지
  시험하려면 입력에 그 표시가 실제로 들어 있어야 하기 때문이다.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DEFAULT_DEPLOY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy_config.json")


def generate(deploy_path: str = DEFAULT_DEPLOY, fake: int = 1, theta_deg: float = 30.0,
             speed: float = 0.02, hb_period: float = 1.0, t_max: float = 90.0,
             ambient: float = 25.0, peak: float = 300.0, warm_scale: float = 0.09,
             threshold: float = 80.0, warn: float = 60.0, k_confirm: int = 3,
             t0: float = 1000.0, silence_timeout: float = 3.0,
             nonfire_ids=(), nonfire_t: float = 6.0, drop_lg_ids=(),
             origin=None, p0_offset: float = -0.10):
    """펌웨어 방언 JSONL 문자열을 순차 yield.

    [2.M 테스트] 세 부류를 섞을 수 있다:
      (a) 진짜 화재사망      — 기본. 임계를 밟고 LG를 보낸 뒤 침묵.
      (b) 비화재 침묵(저온)  — `nonfire_ids`: 불이 닿기 전 `nonfire_t`에 **말없이** 송신 중단.
                               LG 없음, 온도 낮음 → 배터리 소진·크래시의 대리.
      (c) LG 없는 침묵       — `drop_lg_ids`: 불에 타 죽지만 **LG 줄만 유실**시킨다.
                               [P2] 비대칭 규칙이 이걸 무조건 기각하면 **진짜 화재를 버린다**.
    """
    with open(deploy_path, encoding="utf-8") as f:
        dep = json.load(f)
    nodes = {int(n["id"]): (float(n["x"]), float(n["y"]), bool(n.get("is_sink", False)))
             for n in dep["nodes"]}
    sink = int(dep.get("sink_id", 0))
    # ── 전선 모양 ──
    #   origin=None  → 평면(직선) 전선. theta_deg 방향으로 진행. (기존 동작, 기본값)
    #   origin=(x,y) → **방사형** 전선. 그 점에서 원형으로 퍼진다.
    #     대본 B 가 이쪽이다 — 점화점 (0.02, -0.11) m, 1.100 mm/s.
    #     방사형에서는 '진행방향 투영' 대신 **점화점까지의 거리**가 곧 전선 도달 순서다.
    if origin is None:
        th = math.radians(theta_deg)
        nvec = (math.cos(th), math.sin(th))
        proj = {i: nodes[i][0] * nvec[0] + nodes[i][1] * nvec[1] for i in nodes}
    else:
        ox, oy = origin
        proj = {i: math.hypot(nodes[i][0] - ox, nodes[i][1] - oy) for i in nodes}
    # 전선 시작 위치. 기본은 가장 앞선 노드보다 조금 뒤(=아직 아무도 안 죽은 상태에서 시작).
    #   p0_offset=0.0 이면 가장 앞선 노드가 t=0 에 임계를 밟는다(대본 B 규약).
    p0 = min(proj.values()) + p0_offset

    def temp_at(nid, t):
        d = proj[nid] - (p0 + speed * t)          # + = 전선 앞(미연소)
        if d <= 0:
            return peak
        return ambient + (peak - ambient) * math.exp(-d / warm_scale)

    # 부팅 배너 (루트) — 사람용 + 기계용
    if fake:
        yield "****************************************************"
        yield "*** WARNING: FAKE_TEMP_RAMP=1                    ***"
        yield "*** SYNTHETIC TEMPERATURE - NOT REAL SENSOR DATA ***"
        yield "****************************************************"
    yield json.dumps({"type": "MODE", "fake": fake,
                      "src": "FAKE_TEMP_RAMP" if fake else "DS18B20"})
    yield json.dumps({"type": "ROOT_READY"})

    state = {i: "ALIVE" for i in nodes}
    dying_t = {}
    voted = set()
    confirmed = set()
    votes: dict[int, set] = {}
    last_heard = {i: 0.0 for i in nodes}

    t = 0.0
    while t <= t_max:
        nt = t0 + t                                # 메시 동기 시각(초)

        # (b) 비화재 침묵: 예약 시각에 말없이 송신 중단(LG 없음, 저온)
        for nid in nonfire_ids:
            if state.get(nid) not in ("DEAD",) and t >= nonfire_t:
                state[nid] = "DEAD"

        # 1) 각 노드: 센싱 → 임계 → LG / HB
        for nid in sorted(nodes):
            if state[nid] == "DEAD":
                continue
            temp = temp_at(nid, t)
            is_sink = nodes[nid][2]
            if state[nid] == "ALIVE" and temp >= threshold and not is_sink:
                state[nid] = "DYING"
                dying_t[nid] = t
                yield json.dumps({"type": "ST", "id": nid, "st": "DYING",
                                  "temp": round(temp, 2), "ms": int(t * 1000),
                                  "fake": fake, "nt": nt})
                if nid not in drop_lg_ids:          # (c) LG 줄 유실 시나리오
                    yield json.dumps({"type": "LG", "id": nid,
                                      "x": nodes[nid][0], "y": nodes[nid][1],
                                      "temp": round(temp, 2), "t": t, "ms": int(t * 1000),
                                      "st": "DYING", "fake": fake, "nt": nt})
                last_heard[nid] = t
            elif state[nid] == "ALIVE":
                yield json.dumps({"type": "HB", "id": nid,
                                  "x": nodes[nid][0], "y": nodes[nid][1],
                                  "temp": round(temp, 2), "t": t, "ms": int(t * 1000),
                                  "st": "ALIVE", "fake": fake, "nt": nt})
                last_heard[nid] = t

        # 2) DYING → DEAD (last_gasp_delay 후 송신 중단)
        for nid, td in list(dying_t.items()):
            if state[nid] == "DYING" and t - td >= 0.3:
                state[nid] = "DEAD"
                yield json.dumps({"type": "ST", "id": nid, "st": "DEAD",
                                  "temp": round(temp_at(nid, t), 2), "ms": int(t * 1000),
                                  "fake": fake, "nt": nt})

        # 3) 교차검증: 침묵 + 고온 정황 → DV (관측자는 살아있는 이웃들)
        for nid in sorted(nodes):
            if nid in confirmed or state[nid] != "DEAD":
                continue
            if t - last_heard[nid] <= silence_timeout:
                continue
            observers = [o for o in sorted(nodes)
                         if o != nid and state[o] != "DEAD"
                         and (temp_at(o, t) >= warn or temp_at(nid, last_heard[nid]) >= warn)]
            for o in observers:
                if (nid, o) in voted:
                    continue
                voted.add((nid, o))
                yield json.dumps({"type": "DV", "suspect": nid, "observer": o,
                                  "last_temp": round(temp_at(nid, last_heard[nid]), 2),
                                  "t": t, "fake": fake, "nt": nt})
                votes.setdefault(nid, set()).add(o)
                # 4) 루트 집계 → K표 도달 시 DC
                if len(votes[nid]) >= k_confirm and nid not in confirmed:
                    confirmed.add(nid)
                    yield json.dumps({
                        "type": "DC", "id": nid,
                        "x": nodes[nid][0], "y": nodes[nid][1],
                        # 펌웨어와 동일하게 **suspect 자신의 LG 각인 시각**을 싣는다
                        "death_t_est": t0 + dying_t.get(nid, t),
                        "t_source": "last_gasp_node_stamp",
                        "last_temp": round(temp_at(nid, last_heard[nid]), 2),
                        "fake": fake, "nt": nt})
        t = round(t + hb_period, 6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", default=DEFAULT_DEPLOY)
    ap.add_argument("--fake", type=int, default=1, help="1=합성 표시, 0=실센서 표시")
    ap.add_argument("--out", default=os.path.join("results", "dashboard", "mock_fw_stream.jsonl"))
    ap.add_argument("--t-max", type=float, default=90.0)
    ap.add_argument("--nonfire", default="", help="비화재 침묵 노드 id (쉼표구분)")
    ap.add_argument("--drop-lg", default="", help="LG를 유실시킬 노드 id (쉼표구분)")
    ap.add_argument("--origin", default="", help="방사형 전선 점화점 'x,y' (m). 비우면 직선 전선")
    ap.add_argument("--speed", type=float, default=None, help="전선 속도 m/s")
    ap.add_argument("--p0-offset", type=float, default=-0.10, help="전선 시작 오프셋(m). 0=가장 앞선 노드가 t=0에 임계")
    ap.add_argument("--warm-scale", type=float, default=None, help="온도 상승 스케일(m)")
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    n = 0
    with open(args.out, "w", encoding="utf-8") as f:
        pi = lambda v: tuple(int(x) for x in v.split(",") if x.strip())
        kw = {}
        if args.origin.strip():
            kw["origin"] = tuple(float(x) for x in args.origin.split(","))
        if args.speed is not None: kw["speed"] = args.speed
        if args.warm_scale is not None: kw["warm_scale"] = args.warm_scale
        kw["p0_offset"] = args.p0_offset
        for line in generate(args.deploy, fake=args.fake, t_max=args.t_max,
                             nonfire_ids=pi(args.nonfire), drop_lg_ids=pi(args.drop_lg), **kw):
            f.write(line + "\n")
            n += 1
    print(f"[mock_fw] {n} 줄 → {args.out}  (fake={args.fake})")


if __name__ == "__main__":
    main()
