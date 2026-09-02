"""heat_one.py — 노드 **한 대**를 안전하게 가열한다. 센서 시험과 사망 시험에 함께 쓴다.

왜 이 도구가 따로 필요한가 (2026-09-01)
---------------------------------------
리허설 1회차에서 사용자는 **온도를 모른 채, 언제 떼는지도 모른 채** 노드를 계속 지졌다.
화상 직전까지 갔다. 원인은 두 가지였고 둘 다 도구의 부재였다.
  ① 온도를 소리로 알려주는 장치가 없었다 — 손이 바빠 화면을 못 본다.
  ② 「떼세요」를 말해 주는 장치가 없었다 — 사망 LED 를 종료 신호로 삼았는데,
     센서가 죽은 노드는 **영원히 죽지 않으므로** 그 신호가 오지 않는다.

그래서 이 도구는 **시계로 강제 종료**하고, 온도는 **보조**로만 쓴다.
온도를 못 읽는 노드라도 21초 뒤에는 반드시 「떼세요」가 나간다.

    python scripts/heat_one.py n07 --port COM3          # 온도 보면서 21초 가열
    python scripts/heat_one.py n02 --dwell 8 --no-kill  # 센서 반응만 확인(안 죽임)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# ★ 표준출력/표준오류 고정 — cp949 콘솔에서 문자 하나로 죽지 않게, 튕겨도 줄이 남게.
#   근거: docs/n07_사망시험_판정_20260901.md §7
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from voice import Voice                          # noqa: E402

TT = re.compile(r'"temp":([-0-9.]+),"st":"(\w+)"')
HARD_STOP_C = 105.0


class Temp:
    """노드 시리얼에서 온도를 읽는다. 포트가 없으면 조용히 비활성."""

    def __init__(self, port, voice):
        self.v = voice
        self.cur = None
        self.base = None
        self.peak = None
        self.state = "?"
        self.alive = True
        self.s = None
        self.said_80 = False
        self.said_hot = 0.0
        if not port:
            return
        try:
            import serial
            # ★ 리셋 없이 연다. 포트를 그냥 열면 DTR 이 걸려 **노드가 재부팅되고**,
            #   그러면 메시에서 떨어져 임종신호가 브리지에 도달하지 못한다 —
            #   사망 시험이 통째로 무의미해진다.
            self.s = serial.Serial()
            self.s.port, self.s.baudrate, self.s.timeout = port, 115200, 0.3
            self.s.dtr = False
            self.s.rts = False
            self.s.open()
            threading.Thread(target=self._run, daemon=True).start()
        except Exception as e:
            print("  [온도] %s 열기 실패: %s — 시계만으로 진행한다" % (port, e))
            self.s = None

    def _run(self):
        while self.alive:
            try:
                ln = self.s.readline().decode("utf-8", "replace")
            except Exception:
                break
            m = TT.search(ln)
            if not m:
                continue
            self.cur = float(m.group(1))
            self.state = m.group(2)
            if self.base is None:
                self.base = self.cur
            self.peak = self.cur if self.peak is None else max(self.peak, self.cur)
            if not self.said_80 and self.cur >= 80.0:
                self.said_80 = True
                self.v.say("팔십도 통과", critical=True)
            if self.cur >= HARD_STOP_C and time.time() - self.said_hot > 2.0:
                self.said_hot = time.time()
                self.v.say("위험 %.0f 도. 즉시 떼세요" % self.cur, critical=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("node")
    ap.add_argument("--port", default=None, help="그 노드의 시리얼 포트(있으면 온도를 본다)")
    ap.add_argument("--dwell", type=float, default=21.0)
    ap.add_argument("--no-kill", action="store_true", help="사망시키지 않는다(센서 반응만)")
    ap.add_argument("--quiet", action="store_true",
                    help="소리 없이 화면만. 도구 자체를 시험할 때 쓴다 — 새벽에 시험하려고 "
                         "음성을 끄는 용도이지, 실제 가열에 쓰라는 뜻이 아니다.")
    ap.add_argument("--preheat", type=float, default=300.0,
                    help="열풍기 예열(초). 기본 300=5분. 0 이면 건너뛴다")
    args = ap.parse_args()

    v = Voice(args.quiet)
    t = Temp(args.port, v)
    time.sleep(1.5)

    print("=" * 60)
    print("  %s 가열 — 체류 %.0f초%s" % (args.node, args.dwell,
                                        "  (사망시키지 않음)" if args.no_kill else ""))
    if t.s:
        print("  온도: %s 에서 읽는다 (현재 %s)"
              % (args.port, ("%.2f C" % t.cur) if t.cur is not None else "대기"))
    else:
        print("  ★ 온도를 볼 수 없다 — **시계로만** 통제한다. 21초에 반드시 뗀다.")
    print("=" * 60)

    # ── 예열 ────────────────────────────────────────────────────────────
    #   ★ 예열을 **이 도구 안에서** 한다. 열풍기를 손에 든 뒤에는 사용자가 키보드를
    #     칠 수 없다(2026-09-01 사용자 지적). 예열·카운트다운·가열·「떼세요」가
    #     한 번의 실행으로 끊김 없이 이어져야 한다.
    #   ★ t80 을 5분 예열 조건에서 쟀다. 짧으면 t80 이 길어져 21초에 안 죽는다.
    if args.preheat > 0:
        print("\n" + "=" * 60)
        print("  열풍기를 켜세요 — **판 밖을 향한 채로** %.0f분 예열" % (args.preheat / 60))
        print("  ★ 판을 향하면 노드가 미리 데워져 시험이 틀어집니다.")
        print("=" * 60)
        sys.stdout.flush()
        v.say("열풍기를 켜고 판 밖을 향하게 하세요. %.0f분 예열합니다" % (args.preheat / 60))
        p0 = time.time()
        spoken = set()
        while True:
            left = args.preheat - (time.time() - p0)
            if left <= 0:
                break
            for mark in (240, 180, 120, 60, 30, 10):
                if mark not in spoken and left <= mark:
                    spoken.add(mark)
                    if mark >= 60 and mark % 60 == 0:
                        txt = "%d분 남았습니다" % (mark // 60)
                    else:
                        txt = "%d초 남았습니다" % mark
                    print("    예열 %s" % txt)
                    sys.stdout.flush()
                    v.say(txt)
            time.sleep(0.2)
        print("  예열 완료.\n")
        v.say("예열 완료", critical=True)
        time.sleep(1.5)

    v.say("%s 겨누세요" % args.node)
    time.sleep(3.5)
    for c in (3, 2, 1):
        print("  %d …" % c); sys.stdout.flush()
        v.say(str(c)); time.sleep(1.0)
    v.say("가열 시작", critical=True)
    print("\n  ★ 가열 시작\n")
    t0 = time.time()

    said = set()
    while True:
        el = time.time() - t0
        left = args.dwell - el
        if left <= 0:
            break
        for mark in (10, 5):
            if mark not in said and left <= mark:
                said.add(mark)
                v.say("%d초" % mark)
        if int(el) not in said:
            said.add(int(el))
            print("  %4.0fs  %s  (남은 %.0f초)"
                  % (el, ("%.2f C" % t.cur) if t.cur is not None else "온도 미상", left))
            sys.stdout.flush()
        time.sleep(0.05)

    v.say("%s 떼세요" % args.node, critical=True)
    print("\n  ★★ 떼세요 ★★\n")
    t.alive = False
    time.sleep(6.0)                       # 뗀 뒤 잔열 상승분을 본다
    if t.s:
        rise = (t.peak - t.base) if (t.peak is not None and t.base is not None) else None
        print("  기준 %.2f · 최고 %.2f · 상승 %s"
              % (t.base or -1, t.peak or -1, ("%.2f C" % rise) if rise is not None else "-"))
        print("  마지막 상태: %s" % t.state)
        if rise is not None and rise >= 2.0:
            print("  ★ 센서 반응 확인 (+%.1f℃)" % rise)
            v.say("센서 정상")
        else:
            print("  ★ 센서 반응 없음 — 배선을 확인하라")
            v.say("센서 반응 없음. 배선을 확인하세요", critical=True)
        try:
            t.s.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
