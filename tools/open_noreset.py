"""open_noreset.py — 시리얼 포트를 **보드를 재부팅하지 않고** 연다.

왜 (2026-09-01)
---------------
`serial.Serial(dev, baud)` 는 여는 순간 DTR/RTS 를 걸어 **ESP32 를 리셋한다.**
런 직전 점검 도구가 그러면
  - 그 노드가 메시에서 떨어져 재합류까지 기다려야 하고,
  - 「지금 상태」가 아니라 「도구가 만든 상태」를 재게 되며,
  - 사망(DEAD) 같은 **상태 증거가 지워진다.** n07 이 죽었다는 증거도 리셋 한 번이면 사라졌다.

`rollcall.py` · `heat_one.py` 는 이미 이렇게 열고 있었다. 이 모듈은 그 방식을
한 곳에 모아 `temp_voice.py` · `sensor_probe.py` 도 같이 쓰게 한다.
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def open_serial(port, baud=115200, timeout=0.4, reset=False):
    """리셋 없이 연다. `reset=True` 일 때만 DTR 을 걸어 보드를 재부팅한다."""
    import serial
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, baud, timeout
    s.dtr = False
    s.rts = False
    if reset:
        s.dtr = True
    s.open()
    return s
