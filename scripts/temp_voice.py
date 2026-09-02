"""temp_voice.py — 가열 중 온도를 **음성으로** 알리는 안전장치.

왜 필요한가 (2026-08-31 사고)
-----------------------------
리허설에서 n01 을 가열했는데 LED 가 빨개지지 않았고, 사용자는 열풍기를 든 채
화면을 볼 수 없어 **온도를 전혀 모른 채 계속 가열**했다. 200℃까지 올라가도
아무도 몰랐을 구조였다. 눈으로 보는 계측은 이 작업에서 존재하지 않는 것과 같다.
**손이 바쁠 때 유일하게 전달되는 채널은 소리다.**

이중 감시
---------
1) 온도 자체를 읽어 말한다 (40℃부터 5℃ 간격, 70℃ 이상은 매번).
2) **센서 고장을 따로 잡는다.** 펌웨어 readTemp() 는 DS18B20 읽기 실패(-127)를
   직전값으로 덮어쓴다. 그래서 센서가 빠지면 온도가 25.00 에 **얼어붙고** 노드는
   영원히 살아있는 것처럼 보인다. 값이 FREEZE_S 초 동안 한 번도 안 변하면
   「센서 안 읽힘」이라고 말한다 — 이게 이번 사고의 원인 후보다.
3) HARD_STOP_C 를 넘으면 **반복해서** 떼라고 말한다 (DS18B20 절대한계 125℃).

    python scripts/temp_voice.py              # 노트북에 꽂힌 모든 노드 감시
    python scripts/temp_voice.py --ports COM8 # 특정 포트만
    python scripts/temp_voice.py --quiet      # 소리 없이 화면만
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import threading
import time

import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import serial
import serial.tools.list_ports

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from open_noreset import open_serial          # noqa: E402

# ★ 표준출력/표준오류 고정 — cp949 콘솔에서 문자 하나로 죽지 않게, 튕겨도 줄이 남게.
#   근거: docs/n07_사망시험_판정_20260901.md §7
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

WARN_C = 60.0          # 펌웨어 WARN_TEMP_C
DEATH_C = 80.0         # 펌웨어 TEMP_THRESHOLD_C
HARD_STOP_C = 105.0    # 여기 넘으면 반복 경고 (DS18B20 절대한계 125℃)
FREEZE_S = 8.0         # 가열 중인데 이 시간 동안 값이 안 변하면 센서 고장 의심
ARM_RISE_C = 2.0       # 기준온도보다 이만큼 오르면 「가열 중」으로 본다
STEP_LO = 5.0          # 40~70℃ 구간 알림 간격
QUIET_S = 1.2          # 같은 노드 재알림 최소 간격

TT = re.compile(r'"type":"TT","ms":(\d+),"temp":([-0-9.]+),"st":"(\w+)"')
MID = re.compile(r'"type":"MESHID","id":(\d+)')
ROOT = re.compile(r'"is_root":1')


from voice import Voice          # 끊김/밀림 방지는 voice.py 가 맡는다


class Watch:
    """포트 하나를 감시한다. 노드 하나에 해당한다."""

    def __init__(self, port, voice, reset=False):
        self.port = port
        self.v = voice
        self.reset = reset
        self.name = port
        self.temp = None
        self.state = "?"
        self.last_change = time.time()
        self.last_val = None
        self.next_mark = None
        self.last_said = 0.0
        self.frozen_said = False
        self.base = None
        self.armed = False
        self.alive = True
        self.rising = False

    def label(self, nid):
        self.name = "n%02d" % (nid + 1)

    def speak(self, msg, force=False, beep=False):
        now = time.time()
        if not force and now - self.last_said < QUIET_S:
            return
        self.last_said = now
        self.v.say(msg, critical=beep)

    def feed(self, t, st):
        now = time.time()
        prev = self.temp
        self.temp = t
        self.state = st

        # ── 기준온도 / 가열 개시 판정 ─────────────────────────────────────
        #   실온에 가만히 있는 노드는 **당연히** 값이 안 변한다(9비트 → 0.5℃ 계단).
        #   그걸 고장으로 부르면 매번 울어서 진짜 경고를 묻어버린다. 그래서
        #   「가열이 시작된 노드」에만 고정 감지를 건다 — 기준보다 ARM_RISE_C 오른 뒤부터.
        if self.base is None:
            self.base = t
        if not self.armed and t >= self.base + ARM_RISE_C:
            self.armed = True
            self.speak("%s 가열 감지" % self.name, force=True)

        # ── 센서 고정 감지 (가열 중인 노드만) ─────────────────────────────
        if self.last_val is None or abs(t - self.last_val) >= 0.06:
            self.last_val = t
            self.last_change = now
            if self.frozen_said:
                self.frozen_said = False
                self.speak("%s 온도 다시 읽힙니다" % self.name, force=True)
        elif self.armed and not self.frozen_said and now - self.last_change >= FREEZE_S:
            self.frozen_said = True
            self.speak("경고. %s 온도가 %.0f 도에서 멈췄습니다. 센서 안 읽힘. 가열 중지"
                       % (self.name, t), force=True, beep=True)

        if prev is None:
            self.next_mark = max(40.0, (int(t / STEP_LO) + 1) * STEP_LO)
            return
        self.rising = t > prev + 0.05

        # ── 임계 통과 ─────────────────────────────────────────────────────
        if prev < DEATH_C <= t:
            self.speak("%s 팔십도 통과. 떼세요" % self.name, force=True, beep=True)
            self.next_mark = 90.0
            return
        if prev < HARD_STOP_C <= t:
            self.speak("위험. %s 백오도. 즉시 떼세요" % self.name, force=True, beep=True)
        if t >= HARD_STOP_C:
            self.speak("위험 %.0f 도. 떼세요" % t, beep=True)
            return
        if prev < WARN_C <= t:
            self.speak("%s 육십도" % self.name, force=True)
            self.next_mark = 65.0
            return
        if self.next_mark is not None and t >= self.next_mark:
            self.speak("%s %.0f 도" % (self.name, t))
            self.next_mark += STEP_LO if t < 70 else 5.0

    def run(self):
        try:
            # ★ 리셋 없이 연다. 그냥 열면 DTR 이 걸려 **그 노드가 재부팅되고** 메시에서
            #   떨어진다. 전수시험은 16대를 차례로 여는데, 예전 방식이면 판을 통째로
            #   흔들었다. 게다가 DEAD 같은 상태 증거가 리셋으로 지워진다.
            s = open_serial(self.port, 115200, timeout=0.4, reset=self.reset)
        except Exception as e:
            print("  [%s] 열기 실패: %s" % (self.port, e))
            self.alive = False
            return
        buf = ""
        while self.alive:
            try:
                buf += s.read(256).decode("utf-8", "replace")
            except Exception:
                break
            while "\n" in buf:
                ln, buf = buf.split("\n", 1)
                if ROOT.search(ln):
                    # ★ 브리지 포트를 잡으면 게이트웨이가 열지 못해 런이 통째로 죽는다.
                    #   COM 번호로 거르지 않는다 — 번호는 꽂는 순서마다 바뀐다. 역할로 거른다.
                    print("  [%s] 브리지다 — 감시에서 제외하고 포트를 놓는다" % self.port)
                    self.alive = False
                    self.temp = None
                    break
                m = MID.search(ln)
                if m:
                    self.label(int(m.group(1)))
                m = TT.search(ln)
                if m:
                    self.feed(float(m.group(2)), m.group(3))
        try:
            s.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ports", nargs="*", default=None)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--exclude", nargs="*", default=["COM16", "COM17"])
    ap.add_argument("--reset", action="store_true",
                    help="여는 순간 보드를 리셋한다(기본은 리셋하지 않는다)")
    args = ap.parse_args()

    ports = args.ports or sorted(
        p.device for p in serial.tools.list_ports.comports()
        if p.device not in args.exclude)
    if not ports:
        print("포트가 없다"); return 1

    v = Voice(args.quiet)
    ws = [Watch(p, v, reset=args.reset) for p in ports]
    for w in ws:
        threading.Thread(target=w.run, daemon=True).start()

    print("=" * 62)
    print("  음성 온도계 — 포트 %d개  (%s)" % (len(ports), ", ".join(ports)))
    print("  60℃ 경고 · 80℃ 사망 · 105℃ 위험 · 6초 정지시 센서고장")
    print("=" * 62)
    time.sleep(2.5)
    live = [w for w in ws if w.temp is not None]
    print("  온도 나오는 노드 %d개:" % len(live))
    for w in ws:
        print("    %-6s %-5s %s" % (w.port, w.name,
                                    ("%.2f C" % w.temp) if w.temp is not None else "— 응답 없음"))
    v.say("온도계 준비 완료. 노드 %d 개 감시 중" % len(live))
    print("  Ctrl-C 로 종료.\n")

    try:
        last = 0.0
        while True:
            time.sleep(0.05)
            if time.time() - last >= 1.0:
                last = time.time()
                hot = sorted((w for w in ws if w.temp is not None),
                             key=lambda w: -w.temp)[:4]
                print("  " + " | ".join("%s %5.1fC %s" % (w.name, w.temp, w.state)
                                        for w in hot))
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("\n  종료")
    for w in ws:
        w.alive = False
    return 0


if __name__ == "__main__":
    sys.exit(main())
