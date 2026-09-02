"""gaps_to_coords.py — 인접 간격 24개(가로 12·세로 12) → 노드 16개 절대좌표.

배경: 자로 재기 쉬운 것은 **이웃 사이 간격**이지 원점부터의 절대거리가 아니다.
      그래서 간격을 재고 **누적합**으로 절대좌표를 복원한다.

★ 가정 (측정하지 않은 것) — 문서에 반드시 같이 남긴다:
    · 각 행은 수평, 각 열은 수직이라고 가정한다.
    · **판의 기울어짐(회전)·직각도는 측정하지 않았다.**
      기울어져 있으면 이 방법은 그 성분을 좌표에 반영하지 못한다.

입력 파일 형식 (cm, 주석 `#` 허용):

    # 가로 간격 — 행마다 3개씩, 아래 행(n01~n04)부터
    H r0: 20.1 20.2 20.1
    H r1: 20.2 20.2 20.2
    H r2: 20.1 20.1 20.2
    H r3: 20.2 20.1 20.2
    # 세로 간격 — 열마다 3개씩, 왼쪽 열(n01/n05/n09/n13)부터
    V c0: 20.1 20.1 20.1
    V c1: 20.1 20.0 20.1
    V c2: 20.0 20.0 20.1
    V c3: 20.1 20.0 20.1

라벨 규약: **nXX -> id = XX - 1**, `id = row*4 + col`, 원점 = 좌하단 n01.

    python scripts/gaps_to_coords.py gaps.txt              # 좌표 출력 + 검산
    python scripts/gaps_to_coords.py gaps.txt --emit coords.txt
    → 그 다음: python scripts/apply_measured_coords.py coords.txt
"""
from __future__ import annotations

import argparse
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROWS = COLS = 4
NOMINAL_CM = 20.0


def parse(path):
    H = {}
    V = {}
    txt = open(path, encoding="utf-8").read() if path != "-" else sys.stdin.read()
    for raw in txt.splitlines():
        line = raw.split("#")[0].strip()
        if not line:
            continue
        m = re.match(r"^([HV])\s*([rc])(\d)\s*:\s*(.+)$", line, re.I)
        if not m:
            raise SystemExit("형식을 못 읽었다: %r\n  예) H r0: 20.1 20.2 20.1" % raw)
        kind, _, idx, vals = m.group(1).upper(), m.group(2), int(m.group(3)), m.group(4)
        nums = [float(x) for x in re.split(r"[,\s]+", vals.strip()) if x]
        if len(nums) != 3:
            raise SystemExit("%s %s%d 의 간격이 3개가 아니다(%d개)" % (kind, _, idx, len(nums)))
        (H if kind == "H" else V)[idx] = nums
    for k in range(ROWS):
        if k not in H:
            raise SystemExit("가로 간격 H r%d 가 없다" % k)
        if k not in V:
            raise SystemExit("세로 간격 V c%d 가 없다" % k)
    return H, V


def build(H, V):
    """x[r][c] = 행 r 의 가로 간격 누적합, y[r][c] = 열 c 의 세로 간격 누적합."""
    xs = {}
    ys = {}
    for r in range(ROWS):
        acc = 0.0
        for c in range(COLS):
            xs[(r, c)] = acc
            if c < COLS - 1:
                acc += H[r][c]
    for c in range(COLS):
        acc = 0.0
        for r in range(ROWS):
            ys[(r, c)] = acc
            if r < ROWS - 1:
                acc += V[c][r]
    return xs, ys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gaps")
    ap.add_argument("--emit", default="", help="apply_measured_coords.py 입력 파일로 저장")
    args = ap.parse_args()

    H, V = parse(args.gaps)
    xs, ys = build(H, V)

    print("=== 입력한 간격 24개 (cm) ===")
    for r in range(ROWS):
        print("  가로 행%d (n%02d→n%02d→n%02d→n%02d): %s   합 %.1f"
              % (r, r * 4 + 1, r * 4 + 2, r * 4 + 3, r * 4 + 4,
                 " ".join("%.1f" % v for v in H[r]), sum(H[r])))
    for c in range(COLS):
        print("  세로 열%d (n%02d→n%02d→n%02d→n%02d): %s   합 %.1f"
              % (c, c + 1, c + 5, c + 9, c + 13,
                 " ".join("%.1f" % v for v in V[c]), sum(V[c])))

    rs = [sum(H[r]) for r in range(ROWS)]
    cs = [sum(V[c]) for c in range(COLS)]
    print()
    print("=== 검산 ===")
    print("  행 총합: %s   (편차 %.2f cm)" % (" / ".join("%.1f" % v for v in rs), max(rs) - min(rs)))
    print("  열 총합: %s   (편차 %.2f cm)" % (" / ".join("%.1f" % v for v in cs), max(cs) - min(cs)))
    nom = 3 * NOMINAL_CM
    allg = [v for r in range(ROWS) for v in H[r]] + [v for c in range(COLS) for v in V[c]]
    print("  명목 총합 %.1f cm 대비: 행 %+.1f ~ %+.1f · 열 %+.1f ~ %+.1f"
          % (nom, min(rs) - nom, max(rs) - nom, min(cs) - nom, max(cs) - nom))
    print("  간격 24개: 최소 %.1f · 중앙 %.1f · 최대 %.1f · 평균 %.3f (명목 %.1f)"
          % (min(allg), sorted(allg)[len(allg) // 2], max(allg),
             sum(allg) / len(allg), NOMINAL_CM))

    print()
    print("=== 복원된 절대좌표 (cm) ===")
    lines = []
    for r in range(ROWS):
        for c in range(COLS):
            nid = r * COLS + c
            lines.append("n%02d x=%.2f y=%.2f" % (nid + 1, xs[(r, c)], ys[(r, c)]))
    for r in range(ROWS - 1, -1, -1):          # 위 행부터 찍어 판 모양대로 보이게
        print("  " + "   ".join("n%02d(%5.2f,%5.2f)" % (r * COLS + c + 1, xs[(r, c)], ys[(r, c)])
                                for c in range(COLS)))

    if args.emit:
        with open(args.emit, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print()
        print("→ %s 에 저장했다. 다음:" % args.emit)
        print("   python scripts/apply_measured_coords.py %s" % args.emit)


if __name__ == "__main__":
    main()
