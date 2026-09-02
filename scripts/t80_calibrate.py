"""t80_calibrate.py — t80 당일 교정. 노드 1대의 **자기 시리얼**을 읽는다.

왜 자기 시리얼인가: 비루트 노드는 HB 를 메시로만 보내고 자기 시리얼에는 안 찍는다
(`node.ino` `sendJson` 의 `if (NODE_IS_ROOT)`). 무선으로 받으면 도착률이 10% 안팎이라
**80℃ 통과 순간을 놓친다.** 그래서 펌웨어에 `TT` 트레이스를 넣고(비루트 전용) 그것을 읽는다.

측정 규약
---------
    t80 = (가열 시작) → (온도가 처음 80.0℃ 이상이 된 샘플)
    체류 = round(1.7 × t80중앙값),  상한 22초   (설계헌장_데모_2026-08-17 §5)

**가열 시작은 소리 카운트다운으로 맞춘다.** 사용자가 열풍기를 잡고 있어 키 입력을 못 하므로,
「3 · 2 · 1 · 시작」을 TTS 로 읽어 주고 **「시작」 시점을 t=0 으로 박는다.**
사람의 반응 지연이 그대로 들어가지만, 3회 모두 같은 방식이라 **회차 간 비교는 공정하다.**
(이 지연은 t80 을 과대평가하는 쪽 = 안전측이다.)

예열
----
열풍기가 400℃ 에 오르는 데 시간이 걸린다. **1회차 전에만** `--warmup` 초(기본 **300 = 5분**)를 기다린다.
그동안 **열풍기는 판 밖을 향해야 한다** — 노드를 향하면 잔열로 t80 이 짧게 나온다.
2회차부터는 이미 뜨거우므로 `--regrip` 초(기본 15)만 자세 잡는 시간을 준다.

★ 안전
    · 80℃ 를 넘는 순간 화면에 크게 찍고 소리로 알린다. **그때 열풍기를 뗀다.**
    · 통과 후 3초가 지나도 온도가 계속 오르면 경고를 1초마다 반복한다.
    · DS18B20 절대한계는 125℃ 다. 예비 센서가 1개뿐이라 **절대 파손시키지 않는다.**
    · 마지막 회차만 통과 후 5초를 더 기록해 125℃ 까지 **외삽**한다(실측 아님).

    python scripts/t80_calibrate.py --port COM3
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import statistics as st
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

THRESH = 80.0          # config.h TEMP_THRESHOLD_C
LIMIT = 125.0          # DS18B20 절대한계 (부품 파손)
COOL_TO = 30.0         # 다음 회차 전 냉각 목표
COOL_HOLD = 10.0       # 그 아래로 이 시간만큼 안정되어야 한다
ALERT = r"C:\Users\Public\esp32\alert.ps1"
RE_TT = None


def say(msg):
    try:
        subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", ALERT, "-Say", msg],
                       capture_output=True, timeout=25)
    except Exception:
        pass


def big(msg):
    line = "█" * 64
    print("\n" + line)
    print("  " + msg)
    print(line + "\n")
    sys.stdout.flush()


def read_temp(line):
    """TT 트레이스에서 (ms, temp, state) 를 뽑는다."""
    import re
    global RE_TT
    if RE_TT is None:
        RE_TT = re.compile(r'"type":"TT","ms":(\d+),"temp":([-0-9.]+),"st":"(\w+)"')
    m = RE_TT.search(line)
    if not m:
        return None
    return int(m.group(1)), float(m.group(2)), m.group(3)


def drain(ser, seconds, samples, t0, tag):
    """seconds 동안 읽으며 샘플을 모은다. (마지막 온도, 마지막 시각) 반환."""
    end = time.time() + seconds
    last = None
    while time.time() < end:
        ln = ser.readline().decode("utf-8", "replace").strip()
        r = read_temp(ln)
        if r:
            ms, tmp, stt = r
            now = time.time() - t0
            samples.append({"trial": tag, "t_s": round(now, 3), "board_ms": ms,
                            "temp_c": tmp, "state": stt})
            last = (now, tmp, stt)
    return last


def cool_down(ser, samples, tag):
    print("  냉각 대기 — %.0f℃ 아래로 내려가 %.0f초 안정되면 다음 회차." % (COOL_TO, COOL_HOLD))
    sys.stdout.flush()
    t0 = time.time()
    below_since = None
    last_print = 0
    while True:
        ln = ser.readline().decode("utf-8", "replace").strip()
        r = read_temp(ln)
        if not r:
            if time.time() - t0 > 600:
                print("  ★ 10분이 지나도 트레이스가 없다. 포트를 확인하라."); return False
            continue
        ms, tmp, stt = r
        now = time.time() - t0
        samples.append({"trial": "%s-cool" % tag, "t_s": round(now, 3), "board_ms": ms,
                        "temp_c": tmp, "state": stt})
        if tmp < COOL_TO:
            if below_since is None:
                below_since = time.time()
            elif time.time() - below_since >= COOL_HOLD:
                print("  냉각 완료 — %.1f℃ (%.0f초 걸렸다)" % (tmp, now))
                return True
        else:
            below_since = None
        if now - last_print >= 15:
            last_print = now
            print("    %5.0f초  %.1f℃" % (now, tmp)); sys.stdout.flush()
        if now > 900:
            print("  ★ 15분이 지나도 %.0f℃ 아래로 안 내려간다. 값 %.1f℃." % (COOL_TO, tmp))
            return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--tail", type=float, default=5.0,
                    help="마지막 회차에서 80℃ 통과 후 더 기록할 초(외삽용)")
    ap.add_argument("--warmup", type=float, default=300.0,
                    help="1회차 전 열풍기 예열 대기(초). 기본 300초=5분 (400℃ 도달까지)")
    ap.add_argument("--regrip", type=float, default=15.0,
                    help="2회차부터 자세 잡는 시간(초). 열풍기는 이미 뜨겁다")
    ap.add_argument("--out", default=os.path.join("results", "hw", "t80_calib"))
    args = ap.parse_args()

    import serial
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    ser = serial.Serial(args.port, 115200, timeout=1)
    print("포트 %s · %d회 교정" % (args.port, args.trials))
    print("규약: t80 = 가열 시작 → 온도 첫 %.1f℃ 도달.  체류 = round(1.7 × 중앙값), 상한 22초" % THRESH)
    print("★ 80℃ 를 넘는 순간 알립니다. **그때 열풍기를 떼세요.**")
    print("★ DS18B20 한계 %.0f℃. 예비 센서 1개뿐 — 계속 지지면 죽습니다.\n" % LIMIT)

    samples = []
    t80s = []          # 카운트다운 「시작」 기준
    t80_auto = []      # 온도 상승 검출 기준 (사람 반응 지연과 무관)
    tail_rows = []

    # 트레이스가 나오는지 먼저 확인
    print("트레이스 확인 중…")
    ok = None
    t0 = time.time()
    while time.time() - t0 < 15:
        r = read_temp(ser.readline().decode("utf-8", "replace"))
        if r:
            ok = r
            break
    if not ok:
        print("★ TT 트레이스가 안 나온다. 이 노드에 트레이스 펌웨어가 안 올라갔거나 포트가 다르다.")
        print("  굽기: powershell -File C:\\Users\\Public\\esp32\\flash_node.ps1 -Index <id> -Port %s" % args.port)
        return 2
    print("  OK — 현재 %.1f℃ (상태 %s)\n" % (ok[1], ok[2]))

    for k in range(1, args.trials + 1):
        is_last = (k == args.trials)
        print("=" * 64)
        print("  %d 회차 / %d" % (k, args.trials))
        print("=" * 64)
        # ── 예열 / 자세 잡기 ──────────────────────────────────────────
        if k == 1 and args.warmup > 0:
            big("열풍기를 켜세요 — **판 밖을 향한 채로** %.0f분(%.0f초) 예열합니다" % (args.warmup/60.0, args.warmup))
            print("  ★ 노드를 향하면 안 됩니다. 예열 중 잔열이 판에 가면 t80 이 짧게 나옵니다.")
            sys.stdout.flush()
            say("열풍기를 켜고 판 밖을 향하게 하세요. %.0f분 예열합니다" % (args.warmup/60.0))
            wt0 = time.time()
            spoken = set()
            while time.time() - wt0 < args.warmup:
                left = args.warmup - (time.time() - wt0)
                for mark in (240, 180, 120, 60, 30, 10):
                    if mark not in spoken and left <= mark:
                        spoken.add(mark)
                        print("    예열 %.0f초 남음" % mark); sys.stdout.flush()
                        say(("%d분 남았습니다" % (mark // 60)) if mark >= 60 and mark % 60 == 0
                            else ("%d초 남았습니다" % mark))
                drain(ser, 1.0, samples, wt0, "warmup")
            print("  예열 끝. 이제 겨눕니다."); sys.stdout.flush()
        else:
            print("  %.0f초 안에 열풍기를 노드에 겨누세요 (이미 뜨겁습니다)" % args.regrip)
            sys.stdout.flush()
            say("%d회차. %.0f초 안에 노드에 겨누세요" % (k, args.regrip))
            drain(ser, args.regrip, samples, time.time(), "regrip")

        # 카운트다운 직전 온도를 기준선으로 잡는다(자동 검출용)
        base = drain(ser, 2.0, samples, time.time(), "base-%d" % k)
        baseline = base[1] if base else None
        say("겨누세요. 셋 둘 하나 시작에 맞춰 대세요")
        time.sleep(1.0)
        for c in (3, 2, 1):
            print("  %d …" % c); sys.stdout.flush()
            say(str(c))
        big("지금 가열 시작")
        say("시작")
        t_start = time.time()

        crossed = None
        onset = None          # 온도가 기준선 +1.0℃ 를 처음 넘은 시각(자동 검출)
        warn_next = None
        peak = -999
        while True:
            ln = ser.readline().decode("utf-8", "replace").strip()
            r = read_temp(ln)
            now = time.time() - t_start
            if r:
                ms, tmp, stt = r
                peak = max(peak, tmp)
                samples.append({"trial": k, "t_s": round(now, 3), "board_ms": ms,
                                "temp_c": tmp, "state": stt})
                if onset is None and baseline is not None and tmp >= baseline + 1.0:
                    onset = now
                if crossed is None:
                    print("    %5.1f초  %6.2f℃  %s%s" % (now, tmp, stt,
                          "  ← 상승 시작" if onset is not None and abs(now-onset) < 1e-9 else ""))
                    sys.stdout.flush()
                    if tmp >= THRESH:
                        crossed = now
                        t80s.append(now)
                        t80_auto.append((now - onset) if onset is not None else None)
                        big("★★ %.1f℃ 통과 — t80 = %.2f 초 — 지금 열풍기를 떼세요 ★★" % (tmp, now))
                        say("팔십도 통과. 열풍기를 떼세요")
                        warn_next = time.time() + 3.0
                else:
                    if is_last:
                        tail_rows.append((now - crossed, tmp))
                    # 통과 후에도 계속 오르면 경고 반복
                    if warn_next and time.time() >= warn_next and tmp > THRESH:
                        big("★ 아직 %.1f℃ — 한계 %.0f℃. 열풍기를 떼세요" % (tmp, LIMIT))
                        say("열풍기를 떼세요")
                        warn_next = time.time() + 1.0
                    if tmp >= LIMIT - 10:
                        big("★★★ %.1f℃ — 한계 %.0f℃ 임박. 즉시 치우세요" % (tmp, LIMIT))
                        say("위험. 즉시 치우세요")
            if crossed is not None:
                need = args.tail if is_last else 2.0
                if (time.time() - t_start) - crossed >= need:
                    break
            if now > 120:
                print("  ★ 120초가 지나도 %.1f℃ 에 도달하지 않았다. 이 회차는 버린다." % THRESH)
                say("도달 실패")
                break

        if crossed is not None:
            print("\n  %d회차 t80 = %.2f 초 · 최고 %.2f℃" % (k, crossed, peak))
        say("열풍기를 치우세요. 냉각을 기다립니다")
        if k < args.trials:
            if not cool_down(ser, samples, k):
                print("  ★ 냉각 실패 — 중단한다."); break
            # 다음 회차를 위해 노드를 되살린다(DEAD 는 송신을 멈춘다)
            print("  노드 리셋(DTR) — DYING/DEAD 상태를 ALIVE 로 되돌린다")
            ser.setDTR(False); ser.setRTS(True); time.sleep(0.08)
            ser.setRTS(False); time.sleep(1.5)

    ser.close()

    # ---- CSV ----
    csv_path = args.out + "_curve.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["trial", "t_s", "board_ms", "temp_c", "state"])
        w.writeheader(); w.writerows(samples)

    print("\n" + "=" * 64)
    print("  결과")
    print("=" * 64)
    if not t80s:
        print("  ★ 유효한 t80 이 없다."); return 1
    print("   %-6s %12s %12s" % ("회차", "카운트다운", "온도상승"))
    for i, v in enumerate(t80s, 1):
        a = t80_auto[i-1] if i-1 < len(t80_auto) else None
        print("   %-6d %10.2f 초 %10s" % (i, v, ("%.2f 초" % a) if a is not None else "—"))
    auto = [x for x in t80_auto if x is not None]
    if auto:
        print("\n   ★ 두 기준의 차 = 사람 반응 지연 + TTS 지연 = 중앙값 %.2f 초"
              % (st.median(t80s) - st.median(auto)))
        print("     아래 판정은 **온도상승 기준**을 쓴다 — 사람 타이밍과 무관해 재현성이 높다.")
    src = auto if len(auto) == len(t80s) and auto else t80s
    med = st.median(src)
    sd = st.pstdev(src) if len(src) > 1 else 0.0
    dwell = min(22, round(1.7 * med))
    print("\n   중앙값 %.2f 초 · 산포 σ = %.2f 초 (n=%d)" % (med, sd, len(t80s)))
    print("   ★ 체류 = round(1.7 × %.2f) = %d 초   (상한 22초 적용 후: **%d 초**)"
          % (med, round(1.7 * med), dwell))
    if round(1.7 * med) > 22:
        print("   ★★ 상한 22초를 넘겼다 — 헌장 §5 대로 거리를 1cm 줄이고 재측정할 것.")
    print("\n   ★ σ = %.2f 초 는 **사망시각 산포의 첫 실측치**다." % sd)
    print("     그동안 강건성 실험은 잔차 분포에서 빌린 대리값을 썼다.")

    # ---- 125℃ 외삽 (마지막 회차) ----
    if len(tail_rows) >= 3:
        xs = [a for a, _ in tail_rows]; ys = [b for _, b in tail_rows]
        n = len(xs); mx = sum(xs)/n; my = sum(ys)/n
        den = sum((x-mx)**2 for x in xs)
        slope = sum((x-mx)*(y-my) for x, y in zip(xs, ys))/den if den > 1e-9 else 0.0
        last_t, last_c = tail_rows[-1]
        print("\n" + "-" * 64)
        print("  파손 여유 — **외삽값이다. 실측이 아니다.**")
        print("   통과 후 %.1f초 구간 기울기 = %.2f ℃/초 (표본 %d)" % (last_t, slope, n))
        print("   마지막 관측 %.1f℃" % last_c)
        if slope > 0.05:
            rem = (LIMIT - last_c) / slope
            print("   → %.0f℃ 까지 **약 %.1f 초** 남는다 (통과 시점 기준 %.1f 초)"
                  % (LIMIT, rem, last_t + rem))
            print("   ※ 선형 외삽이다. 실제로는 지수적으로 포화하므로 **실제 여유는 이보다 길다**(보수적).")
        else:
            print("   → 기울기가 %.2f ℃/초 로 거의 0 이다. 열풍기를 이미 뗐거나 포화했다." % slope)
            print("     이 회차로는 파손 여유를 외삽할 수 없다.")
        print("   ★ 실제로 파손시키지 않았다. 옛 조건 실측치 19.8초(임계 60℃ 시절)와는 조건이 다르다.")
    print("\n  곡선 CSV → %s  (%d 샘플)" % (csv_path, len(samples)))
    say("교정 완료. 체류 %d 초" % dwell)
    return 0


if __name__ == "__main__":
    sys.exit(main())
