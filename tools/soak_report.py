"""soak_report.py — 소크 산출물에서 **런 가능 여부에 걸리는 것만** 뽑아 찍는다. 읽기 전용.

왜 (2026-09-01)
---------------
`soak_watch.py` 는 원문 로그(수십 MB)와 이벤트 CSV(수천 줄)를 남긴다. 새벽에 그걸
눈으로 훑을 수는 없다. 리허설 가능 여부를 정하는 것은 **여섯 가지**다:

  1) 브리지 크래시 3종 (abort · Guru Meditation · task_wdt)
  2) 힙 최저 (max_alloc) — 크래시의 선행 지표
  3) 노드별 하트비트 도착률 — **단발 임종신호의 통과 확률이 곧 이 값이다**
  4) 브리지 자기 하트비트 도착률 — 무선을 안 거치므로 병목 위치를 가른다
  5) 포트 개방 배수 — 첫 60초의 쓰레기가 계속되는 고장인지 배수인지
  6) 노드 이탈 · 시계 역행

    python tools/soak_report.py results/hw/soak_16node_20260901_night
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HB_PERIOD_S = 1.0          # firmware/node/config.h HEARTBEAT_MS 1000
BRIDGE_ID = 99
DRAIN_S = 70.0             # 포트 개방 배수 구간(이 앞은 「지금 상태」가 아니다)


def load_raw(path):
    """soak_watch 의 원문 로그는 '%9.2f %s' 꼴이다."""
    for line in open(path, encoding="utf-8", errors="replace"):
        if len(line) < 11:
            continue
        try:
            t = float(line[:9])
        except ValueError:
            continue
        yield t, line[10:].rstrip("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix", help="예: results/hw/soak_16node_20260901_night")
    args = ap.parse_args()

    raw = args.prefix + "_raw.log"
    summ_p = args.prefix + "_summary.json"
    if not os.path.exists(raw):
        print("원문 로그가 없다: %s" % raw)
        return 2

    hb = collections.defaultdict(list)     # id -> [(t, ms)]
    frag = collections.Counter()           # 반복 조각(비 JSON)
    frag_by_min = collections.Counter()
    heap = []
    crashes = collections.Counter()
    crash_at = []                          # [(t, 직전 브리지 uptime ms)]
    bridge_ms = None
    t_max = 0.0
    CRASH = {"abort": re.compile(r"abort\(\) was called|assert failed", re.I),
             "guru": re.compile(r"Guru Meditation", re.I),
             "task_wdt": re.compile(r"task_wdt|Task watchdog", re.I)}

    for t, b in load_raw(raw):
        t_max = max(t_max, t)
        for k, rx in CRASH.items():
            if rx.search(b):
                crashes[k] += 1
                crash_at.append((t, bridge_ms))
        if not (b.startswith("{") and b.endswith("}")):
            frag[b[:40]] += 1
            frag_by_min[int(t // 60)] += 1
            continue
        try:
            m = json.loads(b)
        except Exception:
            continue
        ty = m.get("type")
        if ty == "HB" and isinstance(m.get("id"), int) and "ms" in m:
            hb[m["id"]].append((t, m["ms"]))
            if m["id"] == BRIDGE_ID:
                bridge_ms = m["ms"]
        elif ty == "HEAP":
            heap.append((t, m.get("free"), m.get("min_free"), m.get("max_alloc")))

    print("=" * 78)
    print("  소크 보고 — %s" % os.path.basename(args.prefix))
    print("  관측 %.1f분 · 하트비트 주기 %.0f초(config.h HEARTBEAT_MS)" % (t_max / 60, HB_PERIOD_S))
    print("=" * 78)

    # ── 1) 크래시 ─────────────────────────────────────────────────────
    print()
    print("1) 브리지 크래시 3종")
    if not crashes:
        print("   없음")
    for k, v in crashes.items():
        print("   ★★ %-9s %d회" % (k, v))
    # ★ 크래시 **간격**이 런 길이(25:48)보다 짧으면 런 도중에 죽는다. 그게 관문이다.
    if len(crash_at) >= 2:
        gaps = [crash_at[i][0] - crash_at[i - 1][0] for i in range(1, len(crash_at))]
        print("   크래시 시각: %s" % ", ".join("t=%.0f초(브리지 uptime %s)"
              % (t, ("%.1f분" % (ms / 60000)) if ms else "?") for t, ms in crash_at))
        print("   ★★ 크래시 간격: %s" % ", ".join("%.1f분" % (g / 60) for g in gaps))
        if min(gaps) < 26 * 60:
            print("   ★★★ 최단 간격이 런(25:48)보다 짧다 — **런 도중에 죽을 수 있다.**")
            print("        「uptime 40분 미만」 규칙만으로는 부족하다.")

    # ── 2) 힙 ─────────────────────────────────────────────────────────
    print()
    print("2) 브리지 힙")
    if heap:
        ma = [h[3] for h in heap if h[3] is not None]
        fr = [h[1] for h in heap if h[1] is not None]
        lo_i = min(range(len(heap)), key=lambda i: heap[i][3] if heap[i][3] is not None else 1e9)
        print("   free   최저 %d / 최고 %d" % (min(fr), max(fr)))
        print("   max_alloc 최저 **%d** (t=%.0f초) / 최고 %d" % (min(ma), heap[lo_i][0], max(ma)))
        print("   → max_alloc 이 40k 아래로 내려간 뒤 크래시가 왔다(2026-09-01 관측)")
    else:
        print("   HEAP 표본 없음")

    # ── 3)4) 도착률 ───────────────────────────────────────────────────
    print()
    print("3) 하트비트 도착률  ※ 배수 구간(첫 %.0f초) 제외" % DRAIN_S)
    span = max(1e-9, t_max - DRAIN_S)
    exp = span / HB_PERIOD_S
    rows = []
    for i in sorted(hb):
        n = sum(1 for t, _ in hb[i] if t >= DRAIN_S)
        rows.append((i, n, 100.0 * n / exp))
    nodes = [r for r in rows if r[0] != BRIDGE_ID]
    print("   기대 %.0f개/노드" % exp)
    for i, n, pct in sorted(nodes, key=lambda r: r[2]):
        print("     n%02d  %5d  %5.1f%%" % (i + 1, n, pct))
    missing = [i for i in range(16) if i not in hb]
    if missing:
        print("     ★ 무응답: %s  (DEAD 인 노드는 HB 를 아예 안 보낸다 — node.ino:121)"
              % ", ".join("n%02d" % (i + 1) for i in missing))
    if nodes:
        print("   노드 평균 **%.1f%%**  (최저 %.1f / 최고 %.1f)"
              % (sum(r[2] for r in nodes) / len(nodes),
                 min(r[2] for r in nodes), max(r[2] for r in nodes)))
    br = [r for r in rows if r[0] == BRIDGE_ID]
    if br:
        print()
        print("4) 브리지 자기 하트비트 **%.1f%%** — 무선을 안 거치는데도 이만큼 잃는다" % br[0][2])
        seq = [ms for t, ms in hb[BRIDGE_ID] if t >= DRAIN_S]
        gaps = [(seq[k] - seq[k - 1]) / 1000.0 for k in range(1, len(seq))]
        gaps = [g for g in gaps if 0 < g < 60]
        if gaps:
            print("   ms 간격 중앙값 **%.3f초** (설계 %.1f초)" % (st.median(gaps), HB_PERIOD_S))
            print("   → 1.0 근처면 호스트가 잃은 것, 그보다 크면 **브리지 loop() 가 굶은 것**")

    # ── 5) 배수 ───────────────────────────────────────────────────────
    print()
    print("5) 포트 개방 배수 — 반복 조각이 언제 나오나")
    if frag:
        top = frag.most_common(1)[0]
        print("   가장 흔한 조각 %r × %d" % (top[0], top[1]))
        first = sum(v for k, v in frag_by_min.items() if k == 0)
        rest = sum(v for k, v in frag_by_min.items() if k > 0)
        print("   0~1분 **%d줄** / 1분 이후 **%d줄**" % (first, rest))
        print("   → 첫 1분에 몰리면 **계속되는 고장이 아니라 배수**다. 기동 후 1분을 버리면 된다")
    else:
        print("   깨진 줄 없음")

    # ── 6) 이탈 ───────────────────────────────────────────────────────
    print()
    print("6) 이탈 · 시계")
    ev = args.prefix + "_events.csv"
    if os.path.exists(ev):
        kinds = collections.Counter()
        for line in open(ev, encoding="utf-8", errors="replace"):
            f = line.split(",")
            if len(f) > 2:
                kinds[f[2]] += 1
        for k, v in kinds.most_common(8):
            if k != "event":
                print("   %-22s %d" % (k, v))
    if os.path.exists(summ_p):
        s = json.load(open(summ_p, encoding="utf-8"))
        print()
        print("   기준선 %s대 · 미합류 %s · 완주 %s"
              % (s.get("baseline_node_count"), s.get("미합류_후보"), s.get("final")))

    print()
    print("=" * 78)
    print("  ★ 런 가능 여부의 관문: (3) 도착률이 낮으면 **단발 임종신호가 그 확률로 유실된다.**")
    print("     근거·대책: docs/n07_사망시험_판정_20260901.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
