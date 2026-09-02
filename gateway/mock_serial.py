"""mock_serial.py — 루트 ESP32가 파이로 보낼 '모의 시리얼(JSON 라인)' 스트림 생성 (지시서 #4 §3-A).

실물 HW 없이 게이트웨이를 end-to-end 검증하기 위해, 시뮬 engine을 '물리 세계 + 노드 + 루트'
스탠드인으로 돌려 루트가 내보낼 JSON 라인 스트림을 만든다. 게이트웨이는 이 스트림만 보고
(=시뮬 내부를 모른 채) estimator를 재사용해 재구성한다.

라인 타입:
  META  : {config, nodes(정적 좌표·sink), sink_id}
  NODES : 이번 틱 노드 상태/온도
  DC    : 이번 틱 새로 '확정된' 사망(교차검증 통과) — 루트가 K표 집계해 발행
  ROUTE : 현재 메시 라우팅 트리(자가치유)
  GT    : ground-truth 전선(모의 전용; 실물엔 없음)
  STATS : 전달률·사망 수(루트 카운터)
  TICK  : 틱 경계(게이트웨이가 여기서 스냅샷 1장 flush)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sim.config import Config
from sim.engine import Engine


def generate(cfg):
    """JSON 라인 문자열들을 순차 yield."""
    eng = Engine(cfg)

    # META (정적 정보)
    nodes0 = eng.nodes
    yield json.dumps({
        "type": "META",
        "config": {
            "radio_range_m": cfg.radio_range_m, "dt": cfg.dt,
            "alert_horizon": cfg.alert_horizon, "dt_window": cfg.dt_window,
            "speed_true": cfg.speed_true, "spacing_m": cfg.spacing_m,
        },
        "sink_id": 0,
        "nodes": [{"id": n.id, "x": n.pos[0], "y": n.pos[1], "is_sink": n.is_sink}
                  for n in nodes0],
    }, ensure_ascii=False)

    seen_conf = 0
    for snap in eng.stream():
        t = snap["t"]
        # NODES
        yield json.dumps({
            "type": "NODES", "t": t,
            "nodes": [{"id": nd["id"], "state": nd["state"], "temp": nd["temp"]}
                      for nd in snap["nodes"]],
        }, ensure_ascii=False)

        # DC — verifier.confirm_log 의 새 항목 = 이번 틱 확정 사망
        log = eng.verifier.confirm_log
        for e in log[seen_conf:]:
            nd = eng.by_id[e["id"]]
            yield json.dumps({
                "type": "DC", "t": t, "id": e["id"],
                "x": nd.pos[0], "y": nd.pos[1],
                "death_t_est": e["death_t_est"], "last_temp": e["death_t_est"] and nd.last_temp,
            }, ensure_ascii=False)
        seen_conf = len(log)

        # ROUTE (자가치유 트리)
        yield json.dumps({"type": "ROUTE", "t": t,
                          "edges": snap["topology"]["route_edges"]}, ensure_ascii=False)
        # GT (모의 전용)
        yield json.dumps({"type": "GT", "t": t,
                          "front": list(snap["fire_front"]), "dir": list(snap["fire_dir"])},
                         ensure_ascii=False)
        # STATS
        yield json.dumps({"type": "STATS", "t": t,
                          "delivery_rate": snap["hud"]["delivery_rate"],
                          "n_dead": snap["hud"]["n_dead"]}, ensure_ascii=False)
        # TICK 경계
        yield json.dumps({"type": "TICK", "t": t}, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=os.path.join("results", "dashboard", "mock_stream.jsonl"),
                    help="스트림 저장 경로('-' 면 stdout)")
    args = ap.parse_args()
    cfg = Config(mode="ours", seed=args.seed)

    if args.out == "-":
        for line in generate(cfg):
            print(line)
    else:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        n = 0
        with open(args.out, "w", encoding="utf-8") as f:
            for line in generate(cfg):
                f.write(line + "\n"); n += 1
        print(f"[mock] {n} lines → {args.out}")


if __name__ == "__main__":
    main()
