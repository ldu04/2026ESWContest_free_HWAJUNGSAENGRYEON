"""check_serial_integrity.py — RAW 시리얼을 **보존한 채** 무결성만 분류한다.

왜 (2026-09-01)
---------------
브리지↔파이 시리얼이 깨지는데, 원인 후보가 계층마다 있다:
케이블 · USB 포트 · cp210x 드라이버 · 브리지 보드 · 펌웨어 · 파서.
**첫 번째로 깨지는 계층을 찾기 전에는 아무것도 고치면 안 된다.**

이 도구는 파서 앞단(T3 = 파이 RAW)에서 무엇이 들어왔는지만 본다.
    RAW 저장 → 분류 → 판정   (RAW 는 절대 덮어쓰지 않는다)

오늘 관측된 고장은 이렇게 생겼다 — 이 도구는 이걸 `stale_replay` 로 이름 붙인다:

    b'entry 0x400805b4\\r\\n'  →  b'5b4\\r\\n' × 6,988 (12초)
    b'...,"max_alloc":110580,"peers":0}\\r\\n' 가 초당 수백 회

**펌웨어는 그 줄을 5초에 한 번만 찍는다.** 초당 수백 번 나올 수 없다.
→ ESP32 가 보낸 게 아니라 그 아래(USB-UART/드라이버)가 버퍼를 재생하는 것이다.

사용법
------
    # 1) 잡으면서 분류 (RAW 를 파일로 남긴다)
    python tools/check_serial_integrity.py --port /dev/ttyUSB0 -s 20 \\
        --raw-out results/raw/raw_$(date +%H%M%S).log

    # 2) 이미 잡아 둔 RAW 를 다시 분류 (하드웨어 없이 가능)
    python tools/check_serial_integrity.py --replay results/raw/raw_093312.log

판정 항목
---------
    good_json          완전한 JSON 한 줄
    truncated_json     JSON 이 중간에 잘림 (앞이 잘린 꼬리 조각 포함)
    concatenated       한 줄에 JSON 이 둘 이상 붙음
    stale_replay       **같은 조각이 비정상적으로 반복** ← 오늘의 고장
    boot_noise         부트로더/리셋 출력 (rst:0x, load:, entry 등)
    binary_garbage     UTF-8 로 못 읽는 바이트 (선 뜸/보율 불일치)
    other

그리고 노드별 `ms` 를 **의사 시퀀스**로 써서 유실·역행을 본다
(펌웨어에 seq 를 새로 넣지 않아도 된다 — 재굽기 없이 얻을 수 있는 정보다).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOOT_PAT = re.compile(rb"rst:0x|boot:0x|load:0x|entry 0x|configsip|clk_drv|ets [A-Z]"
                      rb"|mode:DIO|SPIWP|ho \d+ tail|\[REAL SENSOR MODE\]")
# ★ painlessMesh 가 스스로 찍는 정상 로그. JSON 이 아니라고 「깨짐」으로 세면
#   멀쩡한 판이 불량으로 판정된다(2026-09-01 실제로 그랬다).
LIB_PAT = re.compile(rb"^(setLogLevel|STARTUP:|SYSTEM:|CONNECTION:|MESH_STATUS)")


def backlog_split(raw_lines):
    """★★ [2026-09-01] 깨진 줄이 **앞에 몰려 있는가, 전 구간에 흩어져 있는가**를 가른다.

    오늘 이걸 구분 못 해서 오진했다. 실제 캡처를 뜯어보니 이랬다:

        줄 #0 ~ #49,666 : 같은 18바이트 조각 49,667개   ← 밀린 찌꺼기 배출
        줄 #49,668 ~ 끝  : 완전히 정상인 실시간 데이터

    즉 **고장이 아니라 「포트를 열자 낡은 버퍼가 쏟아진 것」**이었고, 다 빠지면 정상이었다.
    896,658 바이트는 115200 baud 로 78초 분량인데 20초 만에 다 받았다 —
    전선으로 온 게 아니라 버퍼에서 USB 속도로 나온 것이다. 그게 결정적 단서였다.

    ★ [2026-09-01 2차 수정] 처음엔 「뒤에서부터 연속으로 정상인 줄」을 셌는데, **실전 캡처는
      거의 항상 줄 중간에서 끊긴다**(임의 시점에 읽기를 멈추므로). 마지막 줄 하나가 잘리면
      연속 카운트가 0이 되어 **홍수를 하나도 못 걷어내고 또 「불량」으로 오판**했다.
      그래서 「반복 조각이 마지막으로 나온 위치」로 자르고, 그 뒤 구간이 실제로 깨끗한지를
      비율로 본다. 끝이 잘려도 흔들리지 않는다.

    ★ 시간으로 자르지 않는다 — 「열고 N초 버리기」는 금지다. 정상 실시간 패킷이 포트를 연
      직후에 들어올 수도 있어서, 시간 기준으로 자르면 멀쩡한 데이터를 버리게 된다.
      **데이터의 성질(반복 쓰레기 조각의 끝)**로만 가른다.

    돌려주는 값: (찌꺼기로 볼 앞부분 줄 수, 판정에 쓸 나머지 줄)
    """
    if len(raw_lines) < 50:
        return 0, raw_lines

    def _is_json(b):
        try:
            json.loads(b.strip().decode("utf-8", "strict"))
            return True
        except Exception:
            return False

    c = Counter(b for b in raw_lines if b.strip())
    if not c:
        return 0, raw_lines
    frag, n = c.most_common(1)[0]
    # 지배적으로 반복되는 **쓰레기** 조각이어야 한다(정상 줄이 반복되는 건 배출이 아니다)
    if n < 50 or n < len(raw_lines) * 0.3 or _is_json(frag):
        return 0, raw_lines

    head = max(i for i, b in enumerate(raw_lines) if b == frag) + 1
    # ★ 경계의 이음매 한 줄은 버린다. 배출이 끝나는 순간 **찌꺼기 꼬리와 실시간 줄이
    #   한 줄로 이어붙는다**(실제 캡처에서 1,962바이트짜리 접합 줄이 나왔다).
    #   이건 고장이 아니라 전환의 필연적 산물이라 판정에서 뺀다. **딱 한 줄만** 뺀다 —
    #   더 버리면 「시간으로 잘라 버리기」와 같아져서 진짜 고장을 감출 수 있다.
    if head < len(raw_lines) and not _is_json(raw_lines[head]):
        head += 1
    live = raw_lines[head:]
    good = sum(1 for b in live if _is_json(b))
    # 잘라낸 뒤가 실제로 깨끗해야 「배출」로 인정한다.
    # 뒤까지 계속 깨져 있으면 그건 배출이 아니라 **지속 고장**이므로 자르지 않는다.
    if len(live) >= 3 and good >= max(2, len(live) * 0.5):
        return head, live
    return 0, raw_lines


def classify(raw_lines):
    """RAW 바이트 줄들을 분류한다. **입력은 바꾸지 않는다.**"""
    kinds = Counter()
    frag = Counter()                      # 반복 조각 세기 (stale_replay 판정용)
    parsed = []                           # 성공한 JSON dict 들
    samples = defaultdict(list)

    for b in raw_lines:
        s = b.rstrip(b"\r\n")
        if not s:
            continue
        if BOOT_PAT.search(s) or LIB_PAT.search(s):
            kinds["boot_noise"] += 1
            if len(samples["boot_noise"]) < 3:
                samples["boot_noise"].append(repr(b)[:90])
            continue
        try:
            text = s.decode("utf-8", "strict")
        except UnicodeDecodeError:
            kinds["binary_garbage"] += 1
            if len(samples["binary_garbage"]) < 3:
                samples["binary_garbage"].append(repr(b)[:90])
            continue
        try:
            d = json.loads(text)
            kinds["good_json"] += 1
            if isinstance(d, dict):
                parsed.append(d)
            continue
        except json.JSONDecodeError:
            pass
        # JSON 이 아니다 — 어떤 식으로 깨졌나
        if text.count("}{") >= 1 or text.count('{"type"') > 1:
            kinds["concatenated"] += 1
        elif text.startswith("{") or text.endswith("}"):
            kinds["truncated_json"] += 1
            frag[text] += 1
        else:
            kinds["other"] += 1
            frag[text] += 1
        if len(samples["broken"]) < 5:
            samples["broken"].append(repr(b)[:90])

    # ── stale_replay 판정 ──
    #  같은 조각이 전체 깨진 줄의 절반 이상을 차지하면 「재생」이다.
    #  무작위 전기 잡음이면 조각이 매번 다르다 — 그게 두 고장을 가르는 지점이다.
    broken_total = kinds["truncated_json"] + kinds["other"]
    top_frag, top_n = (frag.most_common(1)[0] if frag else ("", 0))
    replay = bool(broken_total >= 20 and top_n >= broken_total * 0.5)
    if replay:
        kinds["stale_replay"] = top_n
        kinds["truncated_json"] = max(0, kinds["truncated_json"] - top_n)
        kinds["other"] = max(0, kinds["other"] - (top_n - min(top_n, kinds["truncated_json"])))
    return kinds, parsed, samples, (top_frag, top_n, replay)


def seq_analysis(parsed):
    """노드별 `ms`(펌웨어 millis)를 의사 시퀀스로 써서 유실·역행을 본다."""
    per = defaultdict(list)
    for d in parsed:
        nid, ms = d.get("id"), d.get("ms")
        if isinstance(nid, int) and isinstance(ms, (int, float)):
            per[nid].append(float(ms))
    rows = []
    for nid in sorted(per):
        v = per[nid]
        back = sum(1 for a, b in zip(v, v[1:]) if b < a)      # 시각 역행
        span = (max(v) - min(v)) / 1000.0 if len(v) > 1 else 0.0
        rows.append((nid, len(v), span, back))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--seconds", "-s", type=float, default=20.0)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--raw-out", help="RAW 를 이 파일에 그대로 남긴다(권장)")
    ap.add_argument("--replay", help="이미 잡아 둔 RAW 파일을 다시 분류한다")
    args = ap.parse_args()

    if not args.replay and not args.port:
        print("--port 또는 --replay 중 하나가 필요하다"); return 2

    # ── 수집 (RAW 보존) ──
    if args.replay:
        with open(args.replay, "rb") as f:
            raw_lines = f.readlines()
        src = "재생: %s (%d줄)" % (args.replay, len(raw_lines))
    else:
        import serial
        s = serial.Serial()
        s.port, s.baudrate, s.timeout = args.port, args.baud, 1
        s.dtr = False; s.rts = False        # 리셋 없이 연다(판을 흔들지 않는다)
        s.open()
        raw_lines, t0 = [], time.time()
        while time.time() - t0 < args.seconds:
            b = s.readline()
            if b:
                raw_lines.append(b)
        s.close()
        src = "포트 %s · %.0f초" % (args.port, args.seconds)
        if args.raw_out:
            os.makedirs(os.path.dirname(os.path.abspath(args.raw_out)), exist_ok=True)
            with open(args.raw_out, "wb") as f:
                f.writelines(raw_lines)
            src += "  → RAW %s" % args.raw_out

    # ★ 먼저 「밀린 찌꺼기 배출」 구간을 떼어낸다. 안 떼면 정상 포트를 고장으로 오진한다.
    n_backlog, live_lines = backlog_split(raw_lines)
    kinds, parsed, samples, (top_frag, top_n, replay) = classify(live_lines)
    total = sum(kinds.values())

    print("=" * 70)
    print("  RAW 시리얼 무결성 — T3(파이 RAW) 계층")
    print("=" * 70)
    print("  %s" % src)
    if n_backlog:
        print("  총 %d줄 중 앞 %d줄 = **밀린 찌꺼기 배출**로 보고 제외" % (len(raw_lines), n_backlog))
        print("     (포트를 열자 낡은 버퍼가 쏟아진 것. 고장이 아니다 — 다 빠지면 정상으로 흐른다)")
    print("  판정 대상 %d줄" % total)
    print()
    for k in ("good_json", "stale_replay", "truncated_json", "concatenated",
              "boot_noise", "binary_garbage", "other"):
        if kinds.get(k):
            print("   %-16s %6d  (%4.1f%%)" % (k, kinds[k], 100.0 * kinds[k] / max(1, total)))
    print()
    if replay:
        print("  ★ stale_replay 검출 — 같은 조각이 %d회 반복:" % top_n)
        print("     %r" % top_frag[:70])
        print("     이 조각이 펌웨어의 출력 주기보다 훨씬 자주 나오면 **ESP32 가 보낸 게 아니다.**")
        print("     → 의심 계층: USB-UART 칩 / cp210x 드라이버 / USB 포트 (펌웨어·파서 아님)")
        print()
    for k in ("boot_noise", "binary_garbage", "broken"):
        if samples.get(k):
            print("  [%s 표본]" % k)
            for x in samples[k]:
                print("     %s" % x)
            print()

    rows = seq_analysis(parsed)
    if rows:
        print("  노드별 (ms 를 의사 시퀀스로 사용 — 재굽기 없이 얻는 정보)")
        print("   id   표본   관측폭(s)   시각역행")
        for nid, n, span, back in rows:
            print("   %2d %6d %10.1f %10d%s" % (nid, n, span, back, "  ★역행" if back else ""))
        print()

    good = kinds.get("good_json", 0)
    pct_bad = 100.0 * (total - good) / max(1, total)
    if total == 0:
        print("판정: 무음 — 한 줄도 안 왔다 (T2/T3 경계 또는 전원)"); return 2
    if pct_bad < 2.0:
        print("판정: **정상** (비정상 %.1f%%) — T3 는 깨끗하다. 여기서 문제가 보이면 T4(파서) 이후를 본다." % pct_bad)
        return 0
    print("판정: **불량** (비정상 %.1f%%) — T3 에서 이미 깨졌다. **파서를 원인으로 지목하지 말 것.**" % pct_bad)
    return 1


if __name__ == "__main__":
    sys.exit(main())
