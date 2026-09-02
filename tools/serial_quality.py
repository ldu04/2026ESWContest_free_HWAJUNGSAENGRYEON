"""serial_quality.py — 브리지 시리얼 줄 무결성만 잰다. **노드 16대가 없어도 된다.**

왜 (2026-09-01 09:45)
---------------------
파이에 꽂은 브리지에서 줄이 73% 깨졌다. 케이블을 바꿔도 같았다:
부팅은 정상인데(부트로더 줄 정상) 직후부터 **직전 줄의 꼬리가 무한 반복**된다.

    b'entry 0x400805b4\r\n'  →  b'5b4\r\n' × 6,988 (12초)
    b'...4931}\r\n'          →  b'4931}\r\n' × 4,704 (10초)

같은 브리지·케이블이 **노트북에서는 깨끗했다.** 그래서 용의자는 파이 쪽
(USB 포트 / cp210x 드라이버 / 전원)이다. 그걸 가르려면 **브리지와 파이만** 있으면 된다 —
노드는 한 대도 필요 없다. 브리지는 노드가 없어도 자기 telemetry 를 계속 낸다:

    {"type":"ST","id":99,...}  {"type":"TOPO",...}  {"type":"HEAP",...}  {"type":"HB","id":99,...}

사용법
------
    python tools/serial_quality.py --port COM4 --seconds 20            # 노트북
    .venv/bin/python3 tools/serial_quality.py --port /dev/ttyUSB0 -s 20  # 파이

    --reset 을 주면 열 때 ESP32 를 강제로 리셋한다(무음일 때만 쓴다).

읽는 법
-------
    깨짐 0~2%   : 정상. 이 포트/케이블로 런을 돌려도 된다
    깨짐 5% 이상: 그 조합은 쓰지 않는다. 포트를 바꿔 다시 잰다

**★ 이 도구는 판을 흔들지 않는다** — 기본값은 리셋 없이 연다(rollcall.py 와 같은 이유).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="COM4 (노트북) 또는 /dev/ttyUSB0 (파이)")
    ap.add_argument("--seconds", "-s", type=float, default=20.0)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--reset", action="store_true",
                    help="열 때 ESP32 를 강제 리셋한다. **무음일 때만** 쓴다")
    ap.add_argument("--label", default="", help="결과에 붙일 이름 (예: '파이 USB2 파란포트')")
    args = ap.parse_args()

    import serial

    s = serial.Serial()
    s.port = args.port
    s.baudrate = args.baud
    s.timeout = 1
    # 기본은 리셋 없이 연다. DTR/RTS 를 건드리면 ESP32 가 재부팅되고,
    # 그러면 「지금 상태」가 아니라 「이 도구가 만든 상태」를 재게 된다.
    s.dtr = False
    s.rts = False
    s.open()

    if args.reset:
        # esptool 식 EN 펄스. 무음일 때(리셋에 물려 있을 때) 되살리는 용도다.
        s.setDTR(False); s.setRTS(True); time.sleep(0.2)
        s.setRTS(False); time.sleep(0.1)
        s.reset_input_buffer()

    good = bad = 0
    kinds = Counter()
    bad_samples = []

    print("시리얼 품질 측정 %.0f초 — %s%s"
          % (args.seconds, args.port, ("  [%s]" % args.label) if args.label else ""))

    t0 = time.time()
    while time.time() - t0 < args.seconds:
        raw = s.readline()
        if not raw:
            continue
        try:
            d = json.loads(raw.decode("utf-8", "strict"))
            good += 1
            if isinstance(d, dict):
                kinds[d.get("type", "?")] += 1
        except Exception:
            bad += 1
            if len(bad_samples) < 5:
                bad_samples.append(repr(raw)[:120])
    s.close()

    total = good + bad
    pct = (100.0 * bad / total) if total else 0.0

    print()
    print("  정상 %d줄 · 깨짐 %d줄 · 합계 %d줄" % (good, bad, total))
    print("  초당 %.1f줄" % (total / args.seconds if args.seconds else 0))
    print("  메시지 종류: %s" % (dict(kinds) or "없음"))
    if bad_samples:
        print("\n  깨진 줄 표본:")
        for b in bad_samples:
            print("    %s" % b)
        # 꼬리 반복 시그니처인지 — 표본이 전부 같으면 그 고장이다.
        if len(set(bad_samples)) == 1:
            print("\n  ★ 표본이 전부 동일 — 「직전 줄 꼬리 무한 반복」 시그니처다.")

    print()
    if total == 0:
        print("  ★ 판정: **무음** — 한 줄도 안 왔다.")
        print("     ESP32 가 리셋에 물려 있을 수 있다. --reset 을 붙여 다시 재 볼 것.")
        print("     그래도 무음이면 브리지 전원(USB 5V)이나 보드를 의심한다.")
        return 2
    if pct < 2.0:
        print("  ★ 판정: **정상** (깨짐 %.1f%%) — 이 조합으로 런을 돌려도 된다." % pct)
        return 0
    print("  ★ 판정: **불량** (깨짐 %.1f%%) — 이 조합은 쓰지 않는다." % pct)
    print("     다음 순서로 하나씩 바꿔 가며 다시 잰다:")
    print("       1) 파이의 다른 USB 포트 (검정=USB2 두 개 · 파랑=USB3 두 개, 넷 다)")
    print("       2) 케이블")
    print("       3) 같은 브리지·케이블을 노트북에 꽂아 재기 (파이 탓인지 가르는 결정적 시험)")
    print("       4) 전원 있는 USB 허브를 사이에 끼우기")
    return 1


if __name__ == "__main__":
    sys.exit(main())
