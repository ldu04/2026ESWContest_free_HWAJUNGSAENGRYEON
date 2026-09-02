"""serial_source.py — 라인 소스 추상화 (실 pyserial / 모의 스트림 공통 인터페이스) [지시서 #4 §2].

게이트웨이는 소스 종류를 몰라도 되게, '한 줄씩 JSON 문자열을 yield'하는 통일 인터페이스를 제공.
  - file  : 저장된 mock_stream.jsonl 재생(기본)
  - stdin : 파이프 입력('-')
  - mock  : sim engine에서 즉석 생성('mock')
  - serial: 실 루트 ESP32 USB 시리얼(--port COMx). pyserial은 필요할 때만 import(실물 단계).
"""
import json
import os
import sys
import time

# ★ 표준출력/표준오류 고정 — cp949 콘솔에서 문자 하나로 죽지 않게, 튕겨도 줄이 남게.
#   근거: docs/n07_사망시험_판정_20260901.md §7
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


class BridgeNotFound(RuntimeError):
    """브리지를 못 찾았을 때 **명시적으로** 터진다.

    ★ 조용히 빈 입력으로 도는 것이 제일 나쁘다 — 게이트웨이가 프레임 0개로 정상 종료하면
      "메시가 안 붙었나" "펌웨어가 이상한가" 를 몇 시간 헤매게 된다. 실패는 시끄러워야 한다.
    """


def find_bridge_port(baud: int = 115200, per_port_s: float = 6.0, reset: bool = True):
    """열려 있는 COM 포트를 순회하며 MESHID 배너를 읽어 **브리지 포트를 찾는다.**

    ★ 왜 COM 번호를 고정하면 안 되나 (2026-08-27 실측):
      보드에 붙은 CP210x 중 일부는 USB 시리얼 번호를 보고하지 않아서, Windows 가
      **USB 포트 경로**로 장치를 식별한다. 즉 **다른 USB 구멍에 꽂으면 COM 번호가 바뀐다.**
      데모 당일 브리지를 옆 포트에 꽂는 순간 --port COM3 은 엉뚱한 보드를 열거나 아무것도 못 읽는다.
      그래서 번호가 아니라 **역할(role)** 로 찾는다.

    반환: (port, meshid_dict).  못 찾으면 BridgeNotFound.
    """
    import serial
    from serial.tools import list_ports

    ports = [p.device for p in list_ports.comports()]
    if not ports:
        raise BridgeNotFound("연결된 COM 포트가 하나도 없다. USB 를 확인할 것.")

    seen = []
    for dev in ports:
        try:
            ser = serial.Serial(dev, baud, timeout=0.4)
        except Exception as e:                      # 다른 프로그램이 잡고 있으면 건너뛴다
            seen.append((dev, f"열기 실패: {e}"))
            continue
        try:
            if reset:
                # MESHID 는 부팅 1회뿐이라 리셋해서 다시 받는다.
                # DTR 은 건드리지 않는다(IO0 HIGH 유지 = 정상 부팅). RTS 로 EN 만 눌렀다 뗀다.
                ser.dtr = False
                ser.rts = True
                time.sleep(0.12)
                ser.rts = False
            ser.reset_input_buffer()
            t0 = time.time()
            role = None
            while time.time() - t0 < per_port_s:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", "ignore").strip()
                if '"MESHID"' not in line:
                    continue
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                role = m.get("role")
                seen.append((dev, f'id={m.get("id")} role={role} mid={m.get("mid")}'))
                if m.get("is_root") == 1 or role == "ROOT(bridge)":
                    ser.close()
                    return dev, m
                break
            if role is None:
                seen.append((dev, "MESHID 없음(구 펌웨어이거나 응답 없음)"))
        finally:
            if ser.is_open:
                ser.close()

    detail = "\n".join(f"    {d}: {info}" for d, info in seen) or "    (없음)"
    raise BridgeNotFound(
        "브리지를 찾지 못했다. role=ROOT(bridge) 인 포트가 없다.\n"
        f"  연결된 포트: {ports}\n{detail}\n"
        "  확인: 브리지가 -DNODE_ID=99(BRIDGE_INDEX)로 구워졌는가 / is_root=1 인가.")



# ★ [2026-09-01] 줄 조립기 — `Serial.readline()` 을 직접 쓰지 않는 이유.
#   readline(timeout=1) 은 개행을 못 만나면 **읽은 데까지 잘라서 돌려준다.** 노드 펌웨어는
#   한 줄을 `Serial.print` 여러 번으로 나눠 찍고, 그 사이에 painlessMesh 의 WiFi 작업이
#   1초 넘게 선점하는 일이 있다. 그러면 한 줄이 두 조각으로 갈라져 **둘 다 못 쓰는 쓰레기**가 된다.
#   실측(2026-09-01 점호 120초): 정상 286줄 대 깨진 3664줄 — 프레임의 93%를 이렇게 잃고 있었다.
#   바이트를 모아 두었다가 **개행에서만** 자르면 이 손실이 사라진다.
def _assemble(ser, chunk=4096):
    buf = b""
    while True:
        b = ser.read(chunk if ser.in_waiting == 0 else min(chunk, ser.in_waiting))
        if not b:
            yield None                     # 침묵도 사건이다(호출자가 감시한다)
            continue
        buf += b
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            t = raw.strip()
            if t:
                yield t.decode("utf-8", "ignore")
        if len(buf) > 8192:                # 개행 없이 이만큼 쌓이면 쓰레기다 — 버린다
            buf = b""

def _open_port(dev, baud, reset: bool):
    """데이터 포트를 연다.

    ★ [2026-09-01 발견] `serial.Serial(dev, baud)` 는 여는 순간 DTR/RTS 를 걸어
      **그 보드를 재부팅한다.** 브리지가 루트이므로 브리지가 리셋되면 **메시 시각이
      0 으로 되돌아간다.** 01:12 회차에서 게이트웨이가 기동 직후 「시각 역행
      2887.879s → 6.843s · SUSPECT_NOT_WRAP」을 뱉고 스스로 "이 회차를 그대로 쓰지
      말 것" 이라고 경고한 것이 이것으로 설명된다.

      기본값은 **바꾸지 않았다**(reset=True). 지금까지의 절차·산출물이 이 동작 위에
      서 있고, 런 전 전원 재인가 규칙과도 얽혀 있어 사람이 정할 일이다.
      `--no-port-reset` 으로 끌 수 있게만 해 두었다. 판단 근거: docs/아침보고서.md
    """
    import serial
    if reset:
        return serial.Serial(dev, baud, timeout=1)
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = dev, baud, 1
    s.dtr = False
    s.rts = False
    s.open()
    return s


def iter_lines(spec: str, seed: int = 42, baud: int = 115200, port_reset: bool = True):
    if spec == "mock":
        from mock_serial import generate            # 즉석 생성
        from sim.config import Config
        for line in generate(Config(mode="ours", seed=seed)):
            yield line
    elif spec == "-":
        for line in sys.stdin:
            line = line.strip()
            if line:
                yield line
    elif spec == "auto":
        # ★ COM 번호를 고정하지 않고 **역할로** 브리지를 찾는다(위 find_bridge_port 주석 참조).
        # ※ port_reset=False 면 배너 탐색도 리셋 없이 한다. MESHID 는 부팅 1회뿐이라
        #   이미 떠 있는 보드에서는 안 잡힌다 — 그때는 --port COM* 로 직접 지정할 것.
        dev, meta = find_bridge_port(baud=baud, reset=port_reset)
        print(f"[bridge] {dev} 에서 브리지를 찾았다: "
              f"id={meta.get('id')} role={meta.get('role')} mid={meta.get('mid')}",
              file=sys.stderr)
        ser = _open_port(dev, baud, port_reset)
        yield from _assemble(ser)
    elif spec.upper().startswith("COM") or spec.startswith("/dev/"):
        ser = _open_port(spec, baud, port_reset)
        yield from _assemble(ser)
    else:  # 파일 경로
        with open(spec, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield line
