"""run_gate.py — 런 시작 전 **관문**. 한 번 돌려서 GO / NO-GO 를 낸다.

왜 (2026-09-01)
---------------
오늘 하루 같은 실수를 두 번 했다: **증거를 계층으로 나누지 않고 "깨졌다"로 뭉뚱그렸다.**
그 대가로 케이블·드라이버·포트·보드를 몇 시간 뒤졌고, 결과는 **아무 고장도 아니었다**
(포트를 열자 밀린 버퍼가 쏟아진 것이었다).

그래서 런 직전 판단을 **사람의 인상이 아니라 고정된 항목**으로 만든다.
각 항목은 「무엇을 보고 그렇게 판정했는지」를 같이 찍는다.

    python tools/run_gate.py --port COM3            # 노트북
    python tools/run_gate.py --port /dev/ttyUSB0 --seconds 90 --expect-nodes 16

★ 이 도구는 **아무것도 고치지 않는다.** 읽고 판정만 한다.
★ 판정이 GO 면 **케이블·드라이버·포트·root·펌웨어를 더 건드리지 않고** 런으로 간다.
  그게 오늘 배운 것이다 — 멀쩡한 것을 계속 만지면 변인통제가 깨진다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from check_serial_integrity import backlog_split, classify   # noqa: E402

# 이 파일들이 같으면 「같은 판을 돌리고 있다」고 본다.
IDENTITY_FILES = ["gateway/gateway.py", "gateway/fw_adapter.py", "gateway/serial_source.py",
                  "gateway/deploy_config.json", "scripts/rollcall.py", "scripts/run_cue.py",
                  "firmware/node/config.h"]

G = {}          # 항목 -> (판정, 근거)


def put(k, verdict, why=""):
    G[k] = (verdict, why)


# ── 1. 소프트웨어 신원 ─────────────────────────────────────────────────
def software_identity():
    try:
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True, timeout=20).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True, timeout=20).stdout.strip()
        n_dirty = len([x for x in dirty.splitlines() if x.strip()])
    except Exception:
        h, n_dirty = "?", -1

    digests = {}
    for rel in IDENTITY_FILES:
        p = os.path.join(ROOT, rel)
        if os.path.isfile(p):
            digests[rel] = hashlib.md5(open(p, "rb").read()).hexdigest()[:8]
    combined = hashlib.md5(
        "".join("%s:%s" % (k, v) for k, v in sorted(digests.items())).encode()
    ).hexdigest()[:12]

    ok = len(digests) == len(IDENTITY_FILES)
    put("Software identity", "PASS" if ok else "FAIL",
        "commit %s · 미커밋 %s개 · 핵심파일 지문 %s · python %s"
        % (h, n_dirty if n_dirty >= 0 else "?", combined,
           ".".join(map(str, sys.version_info[:3]))))
    print("  [신원] 핵심 파일 지문 — 파이에서도 같은 값이 나와야 한다")
    for k, v in sorted(digests.items()):
        print("     %-34s %s" % (k, v))
    print("     %-34s %s" % ("→ 합산 지문", combined))
    print()
    return combined


# ── 2~6. 시리얼 한 번 잡아서 여러 항목을 동시에 본다 ───────────────────
def serial_gate(port, seconds, baud, expect_nodes, raw_out):
    import serial
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, baud, 1
    # ★ 리셋하지 않고 연다. 리셋하면 「지금 판의 상태」가 아니라 「내가 만든 상태」를 재게 된다.
    #   대신 backlog 를 데이터 성질로 분리한다(시간으로 자르지 않는다).
    s.dtr = False
    s.rts = False
    s.open()
    lines, t0 = [], time.time()
    while time.time() - t0 < seconds:
        b = s.readline()
        if b:
            lines.append(b)
    s.close()

    if raw_out:
        os.makedirs(os.path.dirname(os.path.abspath(raw_out)), exist_ok=True)
        with open(raw_out, "wb") as f:
            f.writelines(lines)

    n_back, live = backlog_split(lines)
    kinds, parsed, _samples, (_f, _n, _replay) = classify(live)
    total = sum(kinds.values())
    good = kinds.get("good_json", 0)
    # ★ [2026-09-01] 부팅 출력을 「비정상」으로 세면 안 된다.
    #   포트를 열면 이 보드는 리셋되므로 `rst:0x`·`load:`·`entry`·`[REAL SENSOR MODE]` 같은
    #   **정상 부팅 로그가 반드시 따라온다.** 그걸 고장으로 세어 5.2% 가 나왔고
    #   멀쩡한 판이 NO-GO 로 막혔다(실제로 그랬다). 판정은 **JSON 이어야 할 줄** 기준으로만 한다.
    boot = kinds.get("boot_noise", 0)
    judged = max(1, total - boot)
    bad_pct = 100.0 * (total - boot - good) / judged

    # --- 브리지 기동 ---
    saw_meshid = any(d.get("type") == "MESHID" for d in parsed)
    saw_bridge_hb = any(d.get("type") in ("HB", "ST") and d.get("id") == 99 for d in parsed)
    put("Bridge startup", "PASS" if (saw_bridge_hb or saw_meshid) else "FAIL",
        "MESHID %s · 브리지 보고 %s" % ("있음" if saw_meshid else "없음",
                                        "있음" if saw_bridge_hb else "없음"))

    # --- backlog ---
    if n_back == 0:
        put("Serial backlog", "NONE", "배출 구간 없음")
    elif total > 0 and bad_pct < 5:
        put("Serial backlog", "PRESENT-BUT-DRAINED",
            "앞 %d줄 배출 후 실시간 %d줄 정상" % (n_back, total))
    else:
        put("Serial backlog", "CONTINUOUS", "배출 뒤에도 깨짐이 이어진다")

    # --- LIVE ---
    put("LIVE serial", "PASS" if (total >= 3 and bad_pct < 5) else "FAIL",
        "실시간 %d줄(부팅로그 %d 제외) · 비정상 %.1f%%" % (total, boot, bad_pct))

    # --- 점호 ---
    ids = {d.get("id") for d in parsed if isinstance(d.get("id"), int)}
    nodes = sorted(i for i in ids if i != 99)
    missing = [i for i in range(expect_nodes) if i not in nodes]
    put("%d-node rollcall" % expect_nodes,
        "PASS" if (not missing and 99 in ids) else "FAIL",
        "응답 %d/%d · 브리지 %s%s"
        % (len(nodes), expect_nodes, "있음" if 99 in ids else "없음",
           " · 무응답 " + ",".join("n%02d" % (i + 1) for i in missing) if missing else ""))

    # --- 패킷 연속성 (ms 를 의사 시퀀스로) ---
    per = {}
    for d in parsed:
        i, ms = d.get("id"), d.get("ms")
        if isinstance(i, int) and isinstance(ms, (int, float)):
            per.setdefault(i, []).append(float(ms))
    back_n = sum(sum(1 for a, b in zip(v, v[1:]) if b < a) for v in per.values())
    dup_n = sum(len(v) - len(set(v)) for v in per.values())
    put("Packet continuity", "PASS" if (back_n == 0 and dup_n == 0) else "FAIL",
        "시각역행 %d · 중복 %d (노드 %d개 관측)" % (back_n, dup_n, len(per)))

    # --- topology ---
    peers = [d.get("n_peers") for d in parsed if d.get("type") == "TOPO"]
    peers = [p for p in peers if isinstance(p, int)]
    if not peers:
        put("Topology", "UNKNOWN", "TOPO 줄 없음")
    elif len(set(peers)) == 1:
        put("Topology", "STABLE", "n_peers=%d 로 %d회 일정" % (peers[0], len(peers)))
    else:
        put("Topology", "RECONFIGURING", "n_peers 변동 %s" % sorted(set(peers)))
    print("  ※ 부모/자식 관계는 **관측 불가**다 — TOPO_FULL_SUBTREE=0 (힙 크래시 방지).")
    print("     따라서 Topology 는 n_peers 개수만 본 판정이다. 「군집」 여부는 알 수 없다.")

    # --- clock ---
    nts = [(d.get("id"), d.get("nt")) for d in parsed if isinstance(d.get("nt"), (int, float))]
    if not nts:
        put("Clock", "UNKNOWN", "nt 필드 없음")
    else:
        per_nt = {}
        for i, v in nts:
            per_nt.setdefault(i, []).append(float(v))
        jumps = sum(1 for v in per_nt.values() for a, b in zip(v, v[1:]) if b < a)
        put("Clock", "STABLE" if jumps == 0 else "ANOMALOUS",
            "nt 역행 %d건 (노드 %d개)" % (jumps, len(per_nt)))
    print("  ※ mesh 시각 **조정 이벤트**는 관측 불가다 — onNodeTimeAdjusted 미등록.")
    print("     그래서 Clock 은 nt 단조성만 본 판정이고, 「조정됐는지」는 알 수 없다.")
    print()

    # --- 물리 연결 ---
    if n_back == 0 and bad_pct < 1:
        put("Hardware connection", "NORMAL", "배출 없음 · 실시간 깨끗")
    elif bad_pct < 5:
        put("Hardware connection", "UNKNOWN",
            "배출이 있었다 — 간헐 접촉 가능성을 배제하지 못한다")
    else:
        put("Hardware connection", "SUSPICIOUS", "실시간 구간에서 깨짐 지속")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--expect-nodes", type=int, default=16)
    ap.add_argument("--raw-out", default=None)
    args = ap.parse_args()

    raw_out = args.raw_out or os.path.join(
        ROOT, "results", "raw", "gate_%s.log" % time.strftime("%H%M%S"))

    print("=" * 74)
    print("  런 관문 — %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 74)
    software_identity()
    print("  [시리얼] %s 에서 %.0f초 관측 (RAW → %s)"
          % (args.port, args.seconds, os.path.relpath(raw_out, ROOT)))
    serial_gate(args.port, args.seconds, args.baud, args.expect_nodes, raw_out)

    fails = [k for k, (v, _) in G.items() if v in ("FAIL", "CONTINUOUS", "SUSPICIOUS")]
    print("[TONIGHT RUN GATE]")
    print()
    for k in ("Software identity", "Bridge startup", "%d-node rollcall" % args.expect_nodes,
              "Serial backlog", "LIVE serial", "Packet continuity", "Topology", "Clock",
              "Hardware connection"):
        v, why = G.get(k, ("UNKNOWN", "검사 안 함"))
        print("%-22s %-22s %s" % (k + ":", v, why))
    print()
    print("%-22s %s" % ("Immediate blocker:", "YES" if fails else "NO"))
    print("%-22s %s" % ("REHEARSAL:", "NO-GO" if fails else "GO"))
    if fails:
        print()
        print("  막는 항목: %s" % ", ".join(fails))
        print("  ★ 조사 순서: RAW 에 실제 이상이 있나 → BACKLOG 인가 LIVE 인가 →")
        print("     어디서 끊기나 → 브리지 TX / 파이 RAW / 파서 / 게이트웨이 순.")
        print("     **첫 mismatch 계층보다 앞을 원인으로 추측하지 말 것.**")
    else:
        print()
        print("  ★ GO — 여기서 케이블·드라이버·포트·root·펌웨어를 더 건드리지 않는다.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
