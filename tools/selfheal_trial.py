"""selfheal_trial.py — 자가치유 본시험. 브리지 시리얼을 열어놓고 **사람에게 뽑기/꽂기 신호**를 준다.

왜 (2026-09-01)
---------------
본편 런(run_205330)에서 자가치유(경로 재구성)의 **직접 증거를 하나도 못 얻었다**.
`topology.links` 는 좌표 기반 이웃 그래프이고, `relay` 는 0/0(시뮬 전용), 홉수 필드는 없다.
그래서 브리지만 `-DTOPO_FULL_SUBTREE=1` 로 다시 굽고, TOPO 의 `sub` 트리를 관측한다.

★ 뽑고 꽂는 것은 **사람이 한다.** 이 도구는 시각을 재고 신호를 줄 뿐이다.
★ 콘솔 출력은 명령이 끝나야 보이므로 **신호는 음성으로** 낸다(실시간으로 닿는 유일한 채널).
★ 포트는 dtr=False · rts=False 로만 연다 — **보드를 리셋시키면 시험 자체가 무의미해진다**
  (재부팅으로 복구된 것과 재라우팅으로 복구된 것을 구분할 수 없게 된다).

    python tools/selfheal_trial.py --port COM5 --node n15 \
        --seconds 240 --pull-at 40 --replug-at 160 \
        --out results/hw/mesh_selfheal16_<날짜시각>_pull_n15.log
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_KOR = {"0": "공", "1": "일", "2": "이", "3": "삼", "4": "사",
        "5": "오", "6": "육", "7": "칠", "8": "팔", "9": "구"}


def spk(node):
    """'n15' -> '엔십오' (음성 전용)"""
    try:
        k = int(str(node).lstrip("nN"))
    except (TypeError, ValueError):
        return str(node)
    if k < 10:
        return "엔공" + _KOR[str(k)]
    if k == 10:
        return "엔십"
    return "엔십" + _KOR[str(k % 10)]


def say(msg):
    """notify.py 로 음성. 실패해도 시험을 멈추지 않는다."""
    try:
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "notify.py"), "--beep", msg],
                       cwd=ROOT, capture_output=True, timeout=30)
    except Exception:
        pass


def load_mid_map():
    """보드대장에서 mid → 라벨. 트리를 사람이 읽는 이름으로 바꾼다."""
    import re
    m2l = {4113565437: "브리지"}
    p = os.path.join(ROOT, "docs", "보드대장_MAC_NODEID.md")
    try:
        for line in open(p, encoding="utf-8"):
            m = re.match(r"\|\s*(n\d\d|\(브리지\))\s*\|\s*(\d+)\s*\|\s*`[^`]+`\s*\|\s*(\d+)", line)
            if m:
                m2l[int(m.group(3))] = m.group(1).strip("()")
    except OSError:
        pass
    return m2l


def flatten(sub, m2l):
    """sub 트리 → [(라벨, 홉수, 자식수, 하위노드수)]"""
    out = []

    def w(n, d):
        lab = m2l.get(n["nodeId"], str(n["nodeId"]))
        kids = n.get("subs") or []
        below = 0
        for k in kids:
            below += 1 + w(k, d + 1)
        out.append((lab, d, len(kids), below))
        return below
    w(sub, 0)
    return out


def pick_target(sub, m2l):
    """**그 시점 트리에서** 자식이 가장 많은 중계 노드를 고른다.

    ★ 기준선의 노드를 그대로 쓰면 안 된다 — painlessMesh 는 관측 사이에도 스스로
      트리를 바꾼다(실제로 pull_n15 시험에서 n15 가 홉1→홉6 말단으로 내려가 있었다).
    동점이면 하위 노드 수가 많은 쪽, 그다음 홉수가 얕은 쪽.
    """
    rows = [r for r in flatten(sub, m2l) if r[1] > 0 and r[2] > 0]   # 브리지·말단 제외
    if not rows:
        return None
    rows.sort(key=lambda r: (-r[2], -r[3], r[1]))
    return rows[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--node", default="n15")
    ap.add_argument("--seconds", type=float, default=240.0)
    ap.add_argument("--pull-at", type=float, default=40.0)
    ap.add_argument("--replug-at", type=float, default=160.0,
                    help="음수면 되꽂기 신호를 내지 않는다")
    ap.add_argument("--pick-at", type=float, default=None,
                    help="이 시각의 직전 TOPO 트리에서 뽑을 노드를 **자동으로 고른다**")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import serial
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = args.port, args.baud, 1
    s.dtr = False          # ★ 리셋 금지
    s.rts = False
    s.open()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    f = open(args.out, "wb")
    kor = spk(args.node)

    def mark(tag, t, wall):
        """신호 시각을 로그에 주석으로 남긴다. '#' 로 시작해 파서가 건너뛴다."""
        line = ("# [%s] t=%.2f wall=%s node=%s\n"
                % (tag, t, time.strftime("%H:%M:%S", time.localtime(wall)), args.node)).encode()
        f.write(line)
        f.flush()
        print(line.decode().rstrip())

    m2l = load_mid_map()
    last_topo = [None]          # 관측하면서 계속 갱신 — 고를 때 이 값을 쓴다
    cue_at = args.pick_at if args.pick_at is not None else args.pull_at

    t0 = time.time()
    mark("START", 0.0, t0)
    say("자가치유 시험 시작. %.0f초 뒤에 뽑을 노드를 알려드립니다. "
        "★ 뽑을 때 노트북 USB 쪽은 건드리지 마세요" % cue_at)
    pulled = replugged = False

    while True:
        el = time.time() - t0
        if el >= args.seconds:
            break
        if not pulled and el >= cue_at:
            pulled = True
            # ── 그 시점 트리에서 대상을 고른다 ──
            if args.pick_at is not None and last_topo[0] and last_topo[0].get("sub"):
                tgt = pick_target(last_topo[0]["sub"], m2l)
                if tgt:
                    args.node, hop, kids, below = tgt
                    kor = spk(args.node)
                    reason = "홉%d · 자식%d명 · 하위 %d개" % (hop, kids, below)
                else:
                    reason = "중계 노드를 못 찾았다 — 기본값 유지"
            else:
                reason = "자동선택 없음(사전 지정)"
            mark("PULL_CUE", el, time.time())
            mark("TARGET", el, time.time())
            f.write(("# [TARGET_INFO] node=%s %s\n" % (args.node, reason)).encode()); f.flush()
            print("\n" + "█" * 62)
            print("★★★  지금 %s 를 허브에서 뽑으세요  ★★★" % args.node)
            print("      선정 근거: %s" % reason)
            print("█" * 62 + "\n")
            say("지금 %s 를 허브에서 뽑으세요" % kor)
        if args.replug_at >= 0 and not replugged and el >= args.replug_at:
            replugged = True
            mark("REPLUG_CUE", el, time.time())
            print("\n" + "█" * 62)
            print("★★★  지금 %s 를 다시 꽂으세요  ★★★" % args.node)
            print("█" * 62 + "\n")
            say("지금 %s 를 다시 꽂으세요" % kor)
        b = s.readline()
        if b:
            f.write(b)
            # 뽑을 대상을 고르려면 **가장 최근 TOPO** 를 들고 있어야 한다
            if b'"TOPO"' in b:
                try:
                    import json as _j
                    last_topo[0] = _j.loads(b.decode("utf-8", "strict"))
                except Exception:
                    pass

    mark("END", time.time() - t0, time.time())
    say("시험 종료")
    f.close()
    s.close()
    print("\n기록 → %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
