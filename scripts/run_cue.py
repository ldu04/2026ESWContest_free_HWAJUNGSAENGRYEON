"""run_cue.py — 촬영 런 진행 안내. 예열 카운트다운 + 16노드 큐 + 받침대 이동을 **소리로** 부른다.

왜: 런이 25분 48초이고 손에 열풍기가 있어 화면을 못 본다. 동선표를 눈으로 좇으면
    반드시 놓친다. 그래서 **다음에 할 일을 미리 말해 주는 도구**가 필요하다.

시간 기준
---------
표(`docs/D1_리허설_절차서.md` §1-B)의 시각은 **n01 사망 = 0:00** 기준이다.
n01 가열 시작은 **−0:21**(체류 21초)이므로, 카운트다운 「시작」 시점이 표시각 −0:21 이다.
이 도구는 그 기준을 그대로 쓴다 — 화면 시계와 표가 같은 숫자를 가리킨다.

예열
----
**t80 을 5분 예열 조건에서 쟀다.** 체류 21초는 그 t80 에서 나온 값이므로
**촬영도 같은 5분 예열이어야 한다.** 짧으면 t80 이 길어져 노드가 안 죽는다(S4).
예열 중에는 **열풍기를 판 밖으로** 향한다 — 판을 향하면 노드가 미리 데워져 S2 가 된다.

    python scripts/run_cue.py                 # 예열 5분 후 런
    python scripts/run_cue.py --preheat 0     # 예열 건너뛰고 바로 카운트다운
    python scripts/run_cue.py --dry           # 소리 없이 타이밍만 확인
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ★ 표준출력/표준오류 고정 — cp949 콘솔에서 문자 하나로 죽지 않게, 튕겨도 줄이 남게.
#   근거: docs/n07_사망시험_판정_20260901.md §7
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "gateway", "deploy_config.json")
ALERT = r"C:\Users\Public\esp32\alert.ps1"
ORIGIN = (0.02, -0.11)
DWELL = 21.0

# 받침대 이동 — (앞 노드 사망 후, 어디로)
MOVES = [("n10", "오른쪽"), ("n08", "왼쪽"), ("n14", "오른쪽")]
USE = {"n05": "왼쪽", "n09": "왼쪽", "n13": "왼쪽",
       "n08": "오른쪽", "n12": "오른쪽", "n16": "오른쪽"}

_V = None


# ── 음성용 노드 이름 ──────────────────────────────────────────────────
#  ★ [2026-09-01] 예전엔 n01 만 "엔공일" 로 하드코딩돼 있고 나머지 15개는 "n02" 같은
#    원문자열이 그대로 TTS 에 들어갔다. 한국어 음성이 그걸 어떻게 읽을지 예측할 수 없어,
#    **첫 노드와 이후 노드가 다르게 들렸다.** 사용자가 「처음이랑 달라서 헷갈린다」고
#    말한 것이 이것이다. 전 노드를 같은 형식으로 읽는다.
_KOR_D = {"0": "공", "1": "일", "2": "이", "3": "삼", "4": "사",
          "5": "오", "6": "육", "7": "칠", "8": "팔", "9": "구"}


def spk(node):
    """'n07' -> '엔공칠',  'n16' -> '엔십육'  (음성 전용. 화면 표기는 그대로 nXX)"""
    try:
        k = int(str(node).lstrip("nN"))
    except (TypeError, ValueError):
        return str(node)
    if k < 10:
        return "엔공" + _KOR_D[str(k)]
    if k == 10:
        return "엔십"
    return "엔십" + _KOR_D[str(k % 10)]


def say(msg, dry=False, critical=False):
    """보통 문장은 말하는 중이면 버린다. 「떼세요」 같은 안전 문장만 끊고 들어간다.

    왜: 카운트다운이 서로를 취소해 「삼… 일…」이 토막나 들렸다(2026-08-31).
    """
    global _V
    if dry:
        print("      🔊 %s" % msg)
        return
    if _V is None:
        from voice import Voice
        _V = Voice()
    _V.say(msg, critical=critical)


def ms(x):
    s = int(round(x))
    sg = "-" if s < 0 else ""
    s = abs(s)
    return "%s%d:%02d" % (sg, s // 60, s % 60)


def schedule():
    with open(CFG, encoding="utf-8") as f:
        d = json.load(f)
    P = {n["id"]: (n["x"], n["y"]) for n in d["nodes"]}
    v = float(d["config"]["v_front_expected"])
    r = {i: math.hypot(P[i][0] - ORIGIN[0], P[i][1] - ORIGIN[1]) for i in P}
    order = sorted(r, key=lambda i: r[i])
    rmin = r[order[0]]
    t = {i: (r[i] - rmin) / v for i in r}

    def lab(i):
        return "n%02d" % (i + 1)

    ev = []
    prev = None
    for i in order:
        heat = t[i] - DWELL
        gap = None if prev is None else heat - t[prev]
        dist = None if prev is None else math.hypot(P[i][0] - P[prev][0],
                                                    P[i][1] - P[prev][1]) * 100
        ev.append({"t": heat, "kind": "HEAT", "node": lab(i), "death": t[i],
                   "gap": gap, "dist": dist, "sup": USE.get(lab(i))})
        # ★ [2026-08-31] 체류 종료 큐. 없으면 사람은 언제 떼는지 알 방법이 없다.
        #   1회차 사고: 「지금 n01 가열」만 말하고 끝내서, 노드가 안 죽자 사용자가
        #   온도도 모른 채 계속 지졌다. 사망 LED 를 종료 신호로 삼은 설계가 틀렸다 —
        #   센서가 죽으면 그 신호는 **영원히 오지 않는다**. 시계로 강제한다.
        for r in (10.0, 5.0):
            ev.append({"t": t[i] - r, "kind": "TICK", "node": lab(i), "left": r})
        ev.append({"t": t[i], "kind": "STOP", "node": lab(i)})
        prev = i
    idx = {lab(i): i for i in order}
    for dead, side in MOVES:
        ev.append({"t": t[idx[dead]], "kind": "MOVE", "node": dead, "side": side})
    ev.sort(key=lambda e: e["t"])
    return ev, v, t[order[-1]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preheat", type=float, default=300.0, help="열풍기 예열(초). 기본 300=5분")
    ap.add_argument("--dry", action="store_true", help="소리 없이 타이밍만")
    ap.add_argument("--out", default=os.path.join("results", "hw", "run_cue_log.csv"))
    args = ap.parse_args()

    ev, v, total = schedule()
    print("=" * 66)
    print("  촬영 런 안내 — 체류 %.0f초 · v %.3f mm/s · 총 런 %s" % (DWELL, v * 1000, ms(total)))
    print("=" * 66)
    print("  시각 기준: **n01 사망 = 0:00**. n01 가열 시작은 %s 다." % ms(-DWELL))
    print("  받침대: 런 전 **왼쪽**. 이동 3회는 소리로 알린다.")
    print()

    # ── 예열 ────────────────────────────────────────────────────────────
    if args.preheat > 0:
        print("█" * 66)
        print("  열풍기를 켜세요 — **판 밖을 향한 채로** %.0f분 예열" % (args.preheat / 60))
        print("█" * 66)
        print("  ★ 판을 향하면 노드가 미리 데워져 대본보다 일찍 죽습니다(S2).")
        sys.stdout.flush()
        say("열풍기를 켜고 판 밖을 향하게 하세요. %.0f분 예열합니다" % (args.preheat / 60), args.dry)
        t0 = time.time()
        spoken = set()
        while True:
            left = args.preheat - (time.time() - t0)
            if left <= 0:
                break
            for mark in (240, 180, 120, 60, 30, 10):
                if mark not in spoken and left <= mark:
                    spoken.add(mark)
                    txt = ("%d분 남았습니다" % (mark // 60)) if mark >= 60 and mark % 60 == 0 \
                          else ("%d초 남았습니다" % mark)
                    print("    예열 %s" % txt)
                    say(txt, args.dry)
            time.sleep(0.2)
        print("  예열 완료.\n")

    # ── 카운트다운 ──────────────────────────────────────────────────────
    say("받침대 왼쪽. 엔공일 겨누세요", args.dry)
    time.sleep(4.0)
    for c in (3, 2, 1):
        print("  %d …" % c)
        sys.stdout.flush()
        say(str(c), args.dry)
        time.sleep(1.0)
    print("\n" + "█" * 66)
    print("  ★ 지금 n01 가열 시작  (표시각 %s)" % ms(-DWELL))
    print("█" * 66 + "\n")
    say("시작. 엔공일 가열", args.dry)
    t_zero = time.time() + DWELL      # n01 사망 시각 = 표시각 0:00

    rows = []
    pending = [e for e in ev if e["kind"] != "HEAT" or e["node"] != "n01"]
    warned = set()
    last_clock = -99
    while pending:
        now = time.time() - t_zero
        e = pending[0]
        if e["kind"] in ("STOP", "TICK"):
            lead = 0.0
        elif e["kind"] == "MOVE" or (e.get("gap") or 99) > 20:
            lead = 10.0
        else:
            lead = max(3.0, (e.get("gap") or 10) * 0.5)
        key = id(e)
        if lead > 0 and key not in warned and now >= e["t"] - lead:
            warned.add(key)
            if e["kind"] == "MOVE":
                say("%.0f초 뒤 받침대 %s" % (lead, e["side"]), args.dry)
            else:
                extra = " 받침대 %s" % e["sup"] if e.get("sup") else ""
                say("%.0f초 뒤 %s 가열%s" % (lead, spk(e["node"]), extra), args.dry)
        if now >= e["t"]:
            pending.pop(0)
            if e["kind"] == "TICK":
                say("%.0f초" % e["left"], args.dry)
            elif e["kind"] == "STOP":
                print("\n>>> [%s] ★★ %s 떼세요 (체류 %.0f초 종료) ★★"
                      % (ms(now), e["node"], DWELL))
                say("%s 떼세요" % spk(e["node"]), args.dry, critical=True)
                rows.append({"t_table": round(e["t"], 1), "t_actual": round(now, 1),
                             "kind": "STOP", "node": e["node"], "detail": "체류종료"})
            elif e["kind"] == "MOVE":
                print("\n>>> [%s] 받침대 → %s  (다음 가열까지 여유 있음)" % (ms(now), e["side"]))
                say("지금 받침대 %s" % e["side"], args.dry)
                rows.append({"t_table": round(e["t"], 1), "t_actual": round(now, 1),
                             "kind": "MOVE", "node": e["node"], "detail": e["side"]})
            else:
                tight = (e.get("gap") or 99) < 15
                bar = "█" * 66 if tight else ""
                if bar:
                    print("\n" + bar)
                print(">>> [%s] **%s 가열 시작**  (사망 %s · 이동 %s · %s)"
                      % (ms(now), e["node"], ms(e["death"]),
                         ("%.0f초" % e["gap"]) if e["gap"] else "-",
                         ("%.1fcm" % e["dist"]) if e["dist"] else "-"))
                if bar:
                    print(bar)
                say("지금 %s 가열" % spk(e["node"]), args.dry)
                rows.append({"t_table": round(e["t"], 1), "t_actual": round(now, 1),
                             "kind": "HEAT", "node": e["node"],
                             "detail": "사망 %s" % ms(e["death"])})
            sys.stdout.flush()
        if int(now) != last_clock and int(now) % 15 == 0:
            last_clock = int(now)
            nxt = pending[0] if pending else None
            print("    [%s]  다음: %s (%s 뒤)"
                  % (ms(now), (nxt["node"] + (" 이동" if nxt["kind"] == "MOVE" else " 가열"))
                     if nxt else "없음",
                     ("%.0f초" % (nxt["t"] - now)) if nxt else "-"))
            sys.stdout.flush()
        time.sleep(0.05)

    print("\n" + "=" * 66)
    print("  런 종료 — 마지막 사망 %s" % ms(total))
    print("=" * 66)
    say("런 종료. 열풍기를 끄세요", args.dry)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["t_table", "t_actual", "kind", "node", "detail"])
        w.writeheader()
        w.writerows(rows)
    print("  큐 기록 → %s" % args.out)
    print("  ★ 게이트웨이는 **Ctrl-C 로** 끝내야 사망 대장·대시보드가 써진다.")


if __name__ == "__main__":
    sys.exit(main())
