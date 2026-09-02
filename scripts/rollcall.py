"""rollcall.py — 브리지에서 **누가 살아 보고하는지** 세어 리허설 전에 확인한다.

왜 필요한가 (2026-09-01)
------------------------
리허설 1회차에서 게이트웨이가 23분간 프레임 0건이었는데 아무도 몰랐다. 「16대가
붙어 있다」를 **런 시작 전에 증명**하지 않으면, 촬영 20분을 통째로 날린다.
게이트웨이는 런 중 조용하므로 점호는 **별도 도구**여야 한다.

온도까지 같이 본다: 25.00℃ 에 **고정**된 노드는 센서를 못 읽는 노드다
(`node.ino:79-80` 이 읽기 실패를 초기값 25.0f 로 덮어쓴다). n01 이 그랬다.

    python3 scripts/rollcall.py --port /dev/ttyUSB0 --seconds 90
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict

# ★ 표준출력/표준오류 고정 — cp949 콘솔에서 문자 하나로 죽지 않게, 튕겨도 줄이 남게.
#   근거: docs/n07_사망시험_판정_20260901.md §7
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

EXPECT = list(range(16))          # 노드 0..15 (n01..n16)
MIN_SAMPLES = 10                  # 이만큼 모여야 「25.00 고정」을 고장이라 부른다


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--reset", action="store_true",
                    help="여는 순간 보드를 리셋한다(기본은 리셋하지 않는다)")
    args = ap.parse_args()

    import serial
    # ★ 포트를 그냥 열면 DTR/RTS 가 걸려 **브리지가 재부팅된다.** 그러면 메시가 흩어져
    #   3분을 다시 기다려야 하고, 점호가 「지금 상태」가 아니라 「점호가 만든 상태」를 잰다.
    #   런 직전 점검 도구가 판을 흔들면 안 되므로 리셋 없이 연다.
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = args.port, args.baud, 1
    s.dtr = False
    s.rts = False
    if args.reset:
        s.dtr = True
    s.open()

    seen = defaultdict(list)      # id -> [temp, ...]
    kinds = defaultdict(int)
    bad = 0
    t0 = time.time()
    print("점호 %.0f초 — 포트 %s" % (args.seconds, args.port))
    sys.stdout.flush()
    buf = b""
    while time.time() - t0 < args.seconds:
        # readline() 은 타임아웃에 걸리면 줄 중간을 잘라 돌려준다 — 그러면 한 줄이
        # 두 조각으로 갈라져 둘 다 못 쓴다. 바이트를 모아 **개행에서만** 자른다.
        chunk = s.read(4096)
        if not chunk:
            continue
        buf += chunk
        if b"\n" not in buf:
            continue
        parts = buf.split(b"\n")
        buf = parts.pop()
        for raw in parts:
            ln = raw.decode("utf-8", "ignore").strip()
            if not (ln.startswith("{") and ln.endswith("}")):
                bad += 1
                continue
            try:
                d = json.loads(ln)
            except Exception:
                bad += 1
                continue
            k = d.get("type")
            kinds[k] += 1
            i = d.get("id")
            if isinstance(i, int) and "temp" in d:
                seen[i].append(float(d["temp"]))
            el = time.time() - t0
            if int(el) % 15 == 0 and int(el) > 0 and abs(el - int(el)) < 0.05:
                print("  %3.0fs  응답 노드 %d/16" % (el, len([x for x in seen if x != 99])))
                sys.stdout.flush()
    s.close()

    print("\n  메시지 종류: %s · 깨진 줄 %d" % (dict(kinds), bad))
    print("\n  ID  라벨   보고  온도범위        판정")
    missing, frozen = [], []
    for i in EXPECT:
        vs = seen.get(i, [])
        lab = "n%02d" % (i + 1)
        if not vs:
            print("  %2d  %-5s   %3d  %-14s  ★ 무응답" % (i, lab, 0, "-"))
            missing.append(lab)
            continue
        rng = "%.2f~%.2f" % (min(vs), max(vs))
        # 표본이 적으면 25.00 하나만으로 고장이라 부르지 않는다 —
        # 실온이 정말 25℃ 일 수 있다. 9비트라 0.5℃ 계단이므로 표본이 쌓여야 갈린다.
        if len(vs) >= MIN_SAMPLES and len(set(vs)) == 1 and abs(vs[0] - 25.0) < 0.01:
            v = "★ 25.00 고정 — 센서 의심"
            frozen.append(lab)
        elif len(vs) < MIN_SAMPLES:
            v = "표본 부족(%d) — 판정 보류" % len(vs)
        else:
            v = "정상"
        print("  %2d  %-5s   %3d  %-14s  %s" % (i, lab, len(vs), rng, v))
    if 99 in seen:
        print("  99  브리지  %3d" % len(seen[99]))

    # ★ 시리얼 품질도 관문이다. 예전에는 깨진 줄 16270개에도 「통과」라고 찍었다 —
    #   그 상태에서는 사망 신호(단발)가 유실되므로 통과시키면 안 된다.
    total_lines = sum(kinds.values()) + bad
    junk_ratio = bad / max(1, total_lines)
    serial_bad = bad > sum(kinds.values())
    print()
    print("  시리얼 품질: 정상 %d · 깨진 %d (%.0f%%)  %s"
          % (sum(kinds.values()), bad, 100 * junk_ratio,
             "★ 폭주 — 케이블/포트를 의심하라" if serial_bad else "정상"))
    print("  무응답 %d개: %s" % (len(missing), ", ".join(missing) or "없음"))
    print("  센서의심 %d개: %s" % (len(frozen), ", ".join(frozen) or "없음"))
    ok = not missing and not frozen and not serial_bad
    print("\n  ★ 점호 %s" % ("통과 — 런 시작 가능" if ok else "실패 — 위 항목을 먼저 해결"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
