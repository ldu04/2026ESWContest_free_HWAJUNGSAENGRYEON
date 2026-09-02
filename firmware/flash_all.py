#!/usr/bin/env python3
"""flash_all.py — 16보드 순차 플래시 (노드별 ID/좌표 주입) [지시서 #4 §1-5, DoD 3]

각 보드에 nodes.csv의 (NODE_ID, NODE_X, NODE_Y)를 **빌드 플래그**로 주입해 순차로 굽는다.
동일 스케치(node/node.ino)를 ID만 바꿔 16번 굽는 절차를 자동화.

사전 준비:
  - arduino-cli 설치 + ESP32 코어: `arduino-cli core install esp32:esp32`
  - 라이브러리: `arduino-cli lib install painlessMesh ArduinoJson OneWire DallasTemperature "Adafruit NeoPixel"`
  - 보드 하나씩 USB 연결(포트는 --port 로).

사용:
  python firmware/flash_all.py --port COM5            # Windows 예
  python firmware/flash_all.py --port /dev/ttyUSB0 --only 0,1,2   # 일부만
  python firmware/flash_all.py --dry-run              # 명령만 출력(실행 안 함)

주의: 이 개발기엔 arduino-cli가 없을 수 있음 → --dry-run 으로 명령을 확인하고
      실제 플래시는 arduino-cli 설치된 PC에서 수행. [DECISIONS D-025]
"""
import argparse
import csv
import os
import subprocess
import sys

# ★ 표준출력/표준오류 고정 — cp949 콘솔에서 문자 하나로 죽지 않게, 튕겨도 줄이 남게.
#   근거: docs/n07_사망시험_판정_20260901.md §7
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
SKETCH = os.path.join(HERE, "node")
NODES = os.path.join(HERE, "node", "nodes.csv")
FQBN = "esp32:esp32:esp32"          # 일반 ESP32 DevKit


# ─────────────────────────────────────────────────────────────────────
# ★ [2026-08-27] USB 시리얼 번호 충돌 사전 점검 — 16보드 날의 시한폭탄
#
# CP210x 개체 중에는 USB 시리얼을 **"0001" 로 그대로 출고**한 것이 흔하다.
# 같은 시리얼 두 개가 **동시에** 꽂히면 Windows 가 인스턴스 ID 충돌로
# 하나를 아예 안 잡는다(COM 포트가 안 생긴다).
#
# 실측(2026-08-27, 4보드): 시리얼을 보고한 개체 1개("0001") + 안 한 개체 3개.
#   시리얼 없는 개체는 USB **경로**로 식별되므로 서로 충돌하지 않는다.
#   0001 이 하나뿐이라 이번엔 안 터졌다. 16개 중 0001 이 둘 이상이면 그날 터진다.
#
# 그래서 굽기 전에 세어보고, 중복이 있으면 **순차 굽기**로 전환한다
# (한 번에 하나만 꽂아 굽는 것 — 충돌 자체를 피한다).
def usb_serial_census():
    """연결된 CP210x 계열의 USB 시리얼을 센다. (serial_or_path, count) 목록과 중복 여부."""
    try:
        from serial.tools import list_ports
    except Exception:
        return [], False, "pyserial 이 없어 점검을 건너뛴다(pip install pyserial)"
    rows = []
    for p in list_ports.comports():
        sn = getattr(p, "serial_number", None)
        rows.append((p.device, sn if sn else "(시리얼 없음)", getattr(p, "hwid", "")))
    counts = {}
    for _dev, sn, _hw in rows:
        if sn and sn != "(시리얼 없음)":
            counts[sn] = counts.get(sn, 0) + 1
    dupes = {k: v for k, v in counts.items() if v > 1}
    return rows, bool(dupes), dupes


def load_nodes():
    with open(NODES, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_flags(row):
    # 빌드 프로퍼티로 -D 매크로 주입 (config.h 기본값을 오버라이드)
    defs = (f"-DNODE_ID={row['NODE_ID']} "
            f"-DNODE_X={row['NODE_X']}f -DNODE_Y={row['NODE_Y']}f "
            f"-DFAKE_TEMP_RAMP=0")     # 실물은 실제 센서 사용
    # ★ [2026-08-27] `build.extra_flags` 를 쓰면 안 된다 — **플랫폼 기본 플래그를 덮어쓴다.**
    #   esp32 core 3.3.11 에서 실측한 증상(플래그를 줄 때만 발생):
    #       painlessmesh/connection.hpp:40: error: expected ')' before '*' token
    #       painlessmesh/connection.hpp:146: error: 'AsyncClient' does not name a type
    #   플래그 없이 빌드하면 멀쩡하므로 라이브러리 문제로 오인하기 쉽다.
    #   사용자 -D 매크로는 **compiler.cpp.extra_flags** 로 준다(사용자 전용 슬롯이라 안 덮어쓴다).
    return ["--build-property", f"compiler.cpp.extra_flags={defs}"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="대상 시리얼 포트(COM5, /dev/ttyUSB0 등)")
    ap.add_argument("--only", help="특정 NODE_ID만(쉼표구분)")
    ap.add_argument("--dry-run", action="store_true", help="명령만 출력")
    args = ap.parse_args()

    # ★ 굽기 전에 USB 시리얼 충돌부터 본다(위 주석 참조).
    census, has_dupes, dupes = usb_serial_census()
    if census:
        print("=== 연결된 시리얼 장치 ===")
        for dev, sn, hw in census:
            print(f"  {dev:8s}  serial={sn}")
        n0001 = sum(1 for _d, sn, _h in census if sn == "0001")
        print(f"  시리얼 '0001' 개체: {n0001} 개")
    if has_dupes:
        print()
        print("!! 경고: 같은 USB 시리얼이 2개 이상 동시에 꽂혀 있다 -> " + repr(dupes))
        print("   Windows 가 충돌로 하나를 안 잡을 수 있다.")
        print("   -> **순차 굽기로 전환한다**: 한 번에 한 보드만 꽂고 Enter 를 칠 것.")
        print()

    rows = load_nodes()
    if args.only:
        keep = set(args.only.split(","))
        rows = [r for r in rows if r["NODE_ID"] in keep]

    for r in rows:
        cmd = ["arduino-cli", "compile", "--upload", "-b", FQBN]
        if args.port:
            cmd += ["-p", args.port]
        cmd += build_flags(r) + [SKETCH]
        role = r["ROLE"]
        print(f"\n=== NODE_ID={r['NODE_ID']} ({role}) @ ({r['NODE_X']},{r['NODE_Y']}) ===")
        print(" ", " ".join(cmd))
        if args.dry_run:
            continue
        input(f"  → NODE {r['NODE_ID']} 보드를 {args.port or '지정 포트'}에 연결하고 Enter…")
        rc = subprocess.call(cmd)
        if rc != 0:
            print(f"  [실패] NODE {r['NODE_ID']} (rc={rc}). 중단.")
            sys.exit(rc)
        print(f"  [완료] NODE {r['NODE_ID']}")

    print("\n모든 보드 플래시 완료." if not args.dry_run else "\n(dry-run) 명령 출력 완료.")


if __name__ == "__main__":
    main()
