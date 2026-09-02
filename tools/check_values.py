"""check_values.py — **옛 값이 되살아났는지** 문서를 훑는다. 읽기 전용.

왜 (2026-09-01)
---------------
같은 숫자가 여러 문서에 흩어져 있으면 언젠가 어긋난다. 실제로 어긋났다:
`D1_리허설_절차서.md` §4-6 과 `파이_준비_절차.md` 의 「시작 로그 기대값」이
**D-069 시절 값(v 0.00061 · 590.2 · 327.9 · 36.4)** 그대로였다. 그 두 문서는
**런 시작 전에 눈으로 대조하는 검산표**라, 틀린 채로 두면 **맞는 런을 틀렸다고 판정한다.**

정본은 `docs/실측값_대장.md` 다. 이 스크립트는 그 대장을 대신하지 않는다 —
**옛 값이 「현재 값」인 척 다시 나타났는지**만 본다.

판정
  ★FAIL  런에 쓰는 문서(RUNTIME_DOCS)에서 옛 값이 나왔다. 검산이 반대로 작동한다
  확인    그 밖의 문서에서 나왔다. 이력 서술이면 정상이다 — 사람이 한 번 본다

    python tools/check_values.py
    python tools/check_values.py --all      # 이력 서술까지 전부 보여준다
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ★ 런 시작 전에 사람이 눈으로 대조하는 문서. 여기서 옛 값이 나오면 무조건 FAIL 이다.
RUNTIME_DOCS = [
    "docs/D1_리허설_절차서.md",
    "docs/파이_준비_절차.md",
    "docs/현장_조립카드.md",
]

# (이름, 정본, [옛값...])  — 옛값은 **문자열 그대로** 찾는다
#
# ★ [2026-09-01] 이 표 자체가 옛 값이었다. 두 군데가 정본을 못 따라가고 있었다:
#   1) v 가 D-075(텀 압축)로 0.000523 → 0.000579 가 됐는데 여기는 0.000523 이 정본이었다
#   2) **하트비트가 결정 (가′)로 1000 → 10000 ms 가 됐는데 여기는 1000 ms 가 정본이었다**
#   즉 「옛 값 검사기」가 옛 값을 들고 있었다. 통과해도 아무것도 보장하지 못하는 상태였다.
#   ⇒ 근본 대책은 tools/consistency_audit.py (정본에서 유도해 대조). 이 표는 문서 문구용이다.
RULES = [
    # ★ [2026-09-01 2차] 0.000579 → 0.0005785. 반올림이 n07→n09 이동창을 6.998 s 로 만들어
    #   이동 실측 floor(7 s)를 1.6 ms 차이로 밑돌았고, 총 런도 23:18 이 되어 문서(23:19)와
    #   어긋났다. 0.0005785 면 7.023 s 로 floor 를 넘는다(총 런 23:20).
    ("화선 속도 v_front_expected", "0.0005785", ["0.000579", "0.000523", "0.00061", "0.0011"]),
    ("dt_window",                  "622.3",    ["621.8", "688.3", "590.2", "327.3"]),
    ("alert_horizon",              "345.7",    ["345.4", "382.4", "327.9", "181.8"]),
    ("residual_gate_s",            "165.1",    ["62.5", "62.4", "69.1 s", "36.4 s", "59.3 s", "20.4 s"]),
    ("체류시간",                    "21초",     ["체류 18", "체류시간 18"]),
    ("총 런",                      "23:20",    ["23:19", "1399", "25:48", "1548", "22:07", "12:12"]),
    # "1000 ms" 는 "10000 ms" 의 부분문자열이 아니다(뒤가 공백이 아니라 0). 오탐 없음.
    ("하트비트 주기",               "10000 ms", ["1000 ms", "하트비트 1초", "HB 1초",
                                                "하트비트 5초", "HB 5초", "5초 간격"]),
    ("침묵 문턱",                   "30000",    ["3000 ms", "침묵 3초"]),
]

# 이력 서술로 보이는 줄 — 날짜 표시나 「이전/옛/→」가 있으면 정상일 가능성이 높다
HISTORY = re.compile(r"\[20\d\d-\d\d-\d\d\]|이전|옛|과거|→|->|D-0\d\d|정정|였다|이었다")


def scan(paths, patterns):
    hits = []
    for rel in paths:
        p = os.path.join(ROOT, rel)
        if not os.path.isfile(p):
            continue
        for i, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
            for name, cur, olds in patterns:
                for old in olds:
                    if old in line:
                        hits.append((rel, i, name, cur, old, line.strip(), bool(HISTORY.search(line))))
    return hits


def all_docs():
    out = []
    for base in ("docs", "gateway", "scripts", "tools"):
        d = os.path.join(ROOT, base)
        if not os.path.isdir(d):
            continue
        for dp, dn, fn in os.walk(d):
            dn[:] = [x for x in dn if x not in ("__pycache__", "_archive", "cowork")]
            for f in sorted(fn):
                if f.endswith((".md", ".py", ".json")):
                    out.append(os.path.relpath(os.path.join(dp, f), ROOT).replace("\\", "/"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="이력 서술까지 전부 보여준다")
    args = ap.parse_args()

    print("=" * 74)
    print("  옛 값 되살아남 검사 — 정본은 docs/실측값_대장.md")
    print("=" * 74)

    crit = scan(RUNTIME_DOCS, RULES)
    crit = [h for h in crit if not h[6]]          # 이력 서술은 뺀다
    print()
    print("★ 런 검산 문서 %d개 — 옛 값 %d건" % (len(RUNTIME_DOCS), len(crit)))
    for rel, i, name, cur, old, line, _ in crit:
        print("   FAIL %s:%d  [%s] 옛값 '%s' (정본 %s)" % (rel, i, name, old, cur))
        print("        %s" % line[:110])
    if not crit:
        print("   없음 — 통과")

    others = [h for h in scan(all_docs(), RULES) if h[0] not in RUNTIME_DOCS]
    shown = others if args.all else [h for h in others if not h[6]]
    print()
    print("· 그 밖의 문서 — 옛 값 %d건%s"
          % (len(shown), "" if args.all else " (이력 서술로 보이는 줄은 숨김, --all 로 전부)"))
    by = {}
    for rel, i, name, cur, old, line, hist in shown:
        by.setdefault(rel, []).append((i, name, old))
    for rel in sorted(by):
        items = by[rel]
        print("   %-46s %d건  %s" % (rel, len(items),
                                     ", ".join("%s:%d" % (n, i) for i, n, _ in items[:3])))
    if not shown:
        print("   없음")

    print()
    print("  ★ 검사 %s" % ("통과" if not crit else "실패 %d건 — 런 검산표가 틀렸다" % len(crit)))
    return 1 if crit else 0


if __name__ == "__main__":
    sys.exit(main())
