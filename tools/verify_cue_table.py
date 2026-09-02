"""verify_cue_table.py — **음성 큐(run_cue.py)와 절차서 동선표가 같은지** 기계로 대조한다.

왜 (2026-09-01)
---------------
동선표는 사람이 보고, 음성 큐는 사람이 듣는다. 런 중에 둘이 어긋나면 **아무도 모른다** —
표를 안 보고 소리만 듣고 있기 때문이다. 체류시간이나 좌표를 한 번 고칠 때마다 둘이
갈라질 수 있으므로 **런 전 점검에서 매번 대조한다.**

두 소스는 서로 독립이다:
  · 음성 큐  = `run_cue.schedule()` 이 deploy_config.json 에서 **계산**한 값
  · 동선표   = `docs/D1_리허설_절차서.md` §1-B-1 에 **적혀 있는** 값
같은 값이 두 곳에 있으면 언젠가 어긋난다. 그래서 표를 정본으로 두지 않고 매번 맞춰 본다.

    python tools/verify_cue_table.py
"""
from __future__ import annotations

import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

DOC = os.path.join(ROOT, "docs", "D1_리허설_절차서.md")
# | 2 | n02 | 2:45 | 3:06 | 165초 | 19.8 cm |  |
ROW = re.compile(r"^\|\s*\d+\s*\|\s*\**(n\d\d)\**\s*\|\s*(−?-?\d+:\d\d)\s*\|\s*(\d+:\d\d)\s*\|")
TOL_S = 1.0        # 표는 초 단위 반올림이라 1초까지는 같은 값으로 본다


def parse_mmss(s):
    s = s.replace("−", "-").strip()
    neg = s.startswith("-")
    mm, ss = s.lstrip("-").split(":")
    v = int(mm) * 60 + int(ss)
    return -v if neg else v


def doc_rows():
    out = []
    for line in open(DOC, encoding="utf-8"):
        m = ROW.match(line.strip())
        if m:
            out.append((m.group(1), parse_mmss(m.group(2)), parse_mmss(m.group(3))))
    return out


def main():
    import run_cue
    ev, v, total = run_cue.schedule()
    heats = [e for e in ev if e["kind"] == "HEAT"]
    cue = [(e["node"], e["t"], e["death"]) for e in heats]

    doc = doc_rows()
    print("음성 큐 %d행 · 동선표 %d행 · 체류 %.0f초 · v %.3f mm/s · 총 런 %d:%02d"
          % (len(cue), len(doc), run_cue.DWELL, v * 1000, int(total) // 60, int(total) % 60))
    print()

    bad = 0
    if len(cue) != len(doc):
        print("★ 행 수가 다르다 — 큐 %d / 표 %d" % (len(cue), len(doc)))
        bad += 1
    print("  #  노드   큐 가열   표 가열   큐 사망   표 사망   판정")
    for i in range(max(len(cue), len(doc))):
        c = cue[i] if i < len(cue) else None
        d = doc[i] if i < len(doc) else None
        if c is None or d is None:
            print("  %2d  %-5s  %s" % (i + 1, (c or d)[0], "★ 한쪽에만 있다"))
            bad += 1
            continue
        ok = (c[0] == d[0] and abs(c[1] - d[1]) <= TOL_S and abs(c[2] - d[2]) <= TOL_S)
        if not ok:
            bad += 1
        print("  %2d  %-5s %8.1f %9d %9.1f %9d   %s"
              % (i + 1, c[0], c[1], d[1], c[2], d[2], "일치" if ok else "★ 불일치"))
    print()
    print("★ 동선표 대조 %s" % ("통과 — 16행 전부 일치" if bad == 0
                                else "실패 %d행 — 절차서를 route_table.py 로 다시 뽑아라" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
