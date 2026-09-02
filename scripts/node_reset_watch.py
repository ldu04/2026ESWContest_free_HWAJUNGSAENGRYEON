"""node_reset_watch.py — 노드 **한 대의 자기 시리얼**을 읽어 재부팅 흔적만 찾는다.

왜: 2026-08-31 소크에서 노드 6대의 mesh nodeTime 이 실시각 t≈2527s 에 동시에 ~0 으로
    되돌아갔다. 감소량 3057s 는 uint32 랩 주기 4294.967s 가 **아니다.** 두 가설이 있다.
      H1) 허브 전원 순간 저하 → 노드 6대가 동시 **재부팅** (브리지는 노트북 직결이라 무사)
      H2) 재부팅 없이 painlessMesh 시간축만 재설정
    브리지 시리얼만으로는 못 가른다. **노드 자기 시리얼에 `rst:0x` 가 찍히는지**가 결정적이다.

★ 읽기 전용. 굽지 않는다. 다만 **포트를 여는 순간 그 노드가 한 번 재부팅된다**(DTR/RTS).
  그 1회는 우리가 낸 것이므로 t<5s 의 흔적은 EXPECTED 로 표시한다.
"""
from __future__ import annotations

import argparse
import re
import sys
import time

# ★ 표준출력/표준오류 고정 — cp949 콘솔에서 문자 하나로 죽지 않게, 튕겨도 줄이 남게.
#   근거: docs/n07_사망시험_판정_20260901.md §7
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

RE_RESET = re.compile(r'rst:0x|E BOD|Brownout|brownout|SW_CPU_RESET|POWERON_RESET|'
                      r'SW_RESET|RTCWDT|TG\dWDT|boot:0x', re.I)
RE_MESHID = re.compile(r'"type"\s*:\s*"MESHID"')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--minutes", type=float, default=180.0)
    ap.add_argument("--out", default="results/hw/node_reset_watch")
    args = ap.parse_args()

    import serial
    ser = serial.Serial(args.port, 115200, timeout=1)
    t0 = time.time()
    deadline = t0 + args.minutes * 60.0
    # ★ 줄 단위 버퍼 — 튕겨도 거기까지는 남는다(soak_watch.py 와 같은 이유)
    log = open(args.out + "_%s.log" % args.port, "w", encoding="utf-8", errors="replace",
               buffering=1)

    print("포트 %s · %.0f분 · 재부팅 흔적만 찍는다" % (args.port, args.minutes))
    print("★ 지금 이 포트를 열면서 그 노드가 한 번 재부팅된다(우리가 낸 것). t<5s 는 EXPECTED.")
    sys.stdout.flush()

    boots = 0
    try:
        while time.time() < deadline:
            try:
                line = ser.readline().decode("utf-8", errors="replace").strip()
            except Exception as e:
                print("[시리얼 오류] %s" % e); break
            if not line:
                continue
            now = time.time() - t0
            hit = RE_RESET.search(line)
            mid = RE_MESHID.search(line)
            if hit or mid:
                tag = "EXPECTED(우리가 낸 DTR 리셋)" if now < 5.0 else "★ 자발 재부팅"
                if mid:
                    tag += " / MESHID(부팅 배너)"
                boots += (0 if now < 5.0 else 1)
                msg = "%9.2f %-28s %s" % (now, tag, line[:110])
                print(msg); sys.stdout.flush()
                log.write(msg + "\n"); log.flush()
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        dur = time.time() - t0
        tail = ("자발 재부팅 흔적 %d건 / %.1f분" % (boots, dur / 60.0))
        print(); print(tail)
        print("판정: %s" % ("H1(전원 저하 → 재부팅)을 지지한다" if boots
                            else "재부팅 흔적 없음 → H2(시간축만 재설정) 쪽이다"))
        log.write(tail + "\n"); log.close()


if __name__ == "__main__":
    main()
