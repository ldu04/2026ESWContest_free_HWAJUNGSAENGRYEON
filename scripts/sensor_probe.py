"""sensor_probe.py — 노드 하나의 온도센서가 **살아있는지** 배선을 만지며 확인한다.

왜 필요한가: 펌웨어가 읽기 실패를 직전값으로 덮어써서(node.ino:79-80, 초기값 25.0f)
「센서 없음」과 「실온 25℃」가 화면에서 구별되지 않는다. 구별하는 유일한 방법은
**온도를 흔들어 보는 것**이고, 손은 배선을 만지느라 바쁘므로 결과는 **소리로** 나가야 한다.

    python scripts/sensor_probe.py COM3          # n01 감시
    python scripts/sensor_probe.py COM3 --reopen # 배선 바꿀 때마다 재부팅시켜 다시 읽기
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# ★ 표준출력/표준오류 고정 — cp949 콘솔에서 문자 하나로 죽지 않게, 튕겨도 줄이 남게.
#   근거: docs/n07_사망시험_판정_20260901.md §7
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import serial                                    # noqa: E402
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from open_noreset import open_serial          # noqa: E402
from voice import Voice                          # noqa: E402

TT = re.compile(r'"temp":([-0-9.]+),"st":"(\w+)"')
MID = re.compile(r'"type":"MESHID","id":(\d+)')
MOVE_C = 2.0          # ★ 이만큼 올라야 「반응」이다.
#   0.3 으로 뒀다가 n07 의 **양자화 떨림**(9비트 = 0.5℃ 계단, 25.50↔26.00)을
#   「센서 살아있음」으로 오판했다. 계단 하나는 신호가 아니다 — 기준보다 2℃ 이상
#   **올라야** 반응이다. 내려가는 건 반응으로 치지 않는다.
IDLE_SAY_S = 20.0     # 변화 없을 때 이 간격으로 상태를 말한다


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ports", nargs="+")
    ap.add_argument("--minutes", type=float, default=15.0)
    ap.add_argument("--reset", action="store_true",
                    help="여는 순간 보드를 리셋한다(기본은 리셋하지 않는다)")
    args = ap.parse_args()

    v = Voice()

    class W:
        """포트 하나. 대조군(정상 노드)과 의심 노드를 **동시에** 본다 —
        측정 경로가 맞는지 증명하려면 같은 코드로 반응하는 노드가 옆에 있어야 한다."""

        def __init__(self, dev):
            self.dev = dev
            self.name = dev
            self.base = None
            self.last = None
            self.n = 0
            self.reacted = False
            self.peak = None
            # ★ 리셋 없이 연다 — 그냥 열면 DTR 이 걸려 그 노드가 재부팅된다.
            #   배선을 고치며 반응을 보는 도구인데 매번 리셋하면 직전 상태가 사라진다.
            self.s = open_serial(dev, 115200, timeout=0.2, reset=args.reset)

        def poll(self):
            ln = self.s.readline().decode("utf-8", "replace")
            m = MID.search(ln)
            if m:
                self.name = "n%02d" % (int(m.group(1)) + 1)
                print("  %s = %s" % (self.dev, self.name))
            m = TT.search(ln)
            if not m:
                return
            t = float(m.group(1))
            self.n += 1
            self.peak = t if self.peak is None else max(self.peak, t)
            if self.base is None:
                self.base = self.last = t
                print("  %s 기준 %.2f C" % (self.name, t))
                return
            if t - self.base >= MOVE_C and t - self.last >= 0.4:
                self.last = t
                print("  ★ %s  %.2f C  (기준 %+.2f)" % (self.name, t, t - self.base))
                if not self.reacted:
                    self.reacted = True
                    v.say("%s 센서 살아있습니다" % self.name, critical=True)
                else:
                    v.say("%s %.0f 도" % (self.name, t))

    ws = []
    for dev in args.ports:
        try:
            ws.append(W(dev))
        except Exception as e:
            print("  %s 열기 실패: %s" % (dev, e))
    if not ws:
        return 1

    print("=" * 60)
    print("  센서 시험 — %s   (%.0f분)" % (", ".join(args.ports), args.minutes))
    print("=" * 60)
    v.say("센서 시험 시작. 센서를 손으로 꽉 잡으세요")

    last_idle = time.time()
    t_end = time.time() + args.minutes * 60
    while time.time() < t_end:
        for w in ws:
            w.poll()
        if time.time() - last_idle >= IDLE_SAY_S:
            last_idle = time.time()
            quiet = [w for w in ws if not w.reacted and w.base is not None]
            print("  … " + " | ".join("%s %.2f(n=%d)%s"
                                      % (w.name, w.last if w.last is not None else -1,
                                         w.n, " 반응O" if w.reacted else " 고정")
                                      for w in ws))
            if quiet:
                v.say("%s 아직 반응 없음" % ", ".join(w.name for w in quiet))

    print()
    for w in ws:
        print("  판정 %s : %s  (표본 %d, 기준 %.2f, 최고 %.2f)"
              % (w.name, "정상 — 반응함" if w.reacted else "★ 반응 없음",
                 w.n, w.base or -1, w.peak or -1))
        w.s.close()
    ok = [w.name for w in ws if w.reacted]
    ng = [w.name for w in ws if not w.reacted]
    v.say("시험 종료. 정상 %s. 반응 없음 %s"
          % (", ".join(ok) or "없음", ", ".join(ng) or "없음"), critical=True)
    time.sleep(4)
    return 0


if __name__ == "__main__":
    sys.exit(main())
