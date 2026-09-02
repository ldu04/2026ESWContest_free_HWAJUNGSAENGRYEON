"""route_table.py — 열풍기 동선표를 실측 좌표에서 다시 뽑는다.

배경: 체류 시간(t80 교정 결과)이나 화선 속도가 바뀌면 동선표가 통째로 바뀐다.
      손으로 고치면 반드시 틀린다 — 사망 시각·이동 시간·이동 거리가 서로 얽혀 있다.

물리(대본 B, D-069 와 동일):
    사망 시각 t_i = (r_i - r_min) / v ,  r_i = 점화점에서 노드까지의 거리
    가열 시작   = 사망 시각 - 체류
    이동 시간   = (다음 가열 시작) - (앞 노드 사망)  = 사망 간격 - 체류

★ 좌표는 `gateway/deploy_config.json` 에서 읽는다. 명목 격자로 계산하려면 --nominal.
★ 이 스크립트는 **아무 파일도 고치지 않는다.** 표만 찍는다.

    python scripts/route_table.py                          # 현행(설정값 v, 체류 21)
    python scripts/route_table.py --dwell 22 --speed 0.000438
    python scripts/route_table.py --dwell 22 --solve 15    # 이동 15초를 만드는 v 를 역산
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "gateway", "deploy_config.json")
ORIGIN = (0.02, -0.11)          # 대본 B 점화점 (m)
ROWS = COLS = 4
# 준비 시간(분): 전원 재인가 → 합류 40초 → 안정 3분 → 게이트웨이 1분 → 대시보드 2분
PREP_MIN = 6.7
WRAP_MIN = 4294.967296 / 60.0   # 71.58 분
UPTIME_WARN_MIN = 40.0


def ms(x):
    s = int(round(x))
    sign = "-" if s < 0 else ""
    s = abs(s)
    return "%s%d:%02d" % (sign, s // 60, s % 60)


def load_positions(nominal=False):
    if nominal:
        return {r * COLS + c: (c * 0.20, r * 0.20) for r in range(ROWS) for c in range(COLS)}
    with open(CFG, encoding="utf-8") as f:
        d = json.load(f)
    return {n["id"]: (n["x"], n["y"]) for n in d["nodes"]}, d


def main():
    ap = argparse.ArgumentParser()
    # ★ [2026-09-01] 기본값 18 -> 21. D-074 로 체류가 21초가 된 뒤에도 18 로 남아 있어,
    #   플래그 없이 그냥 돌리면 **옛 대본 표가 조용히 나왔다.** 절차서는 늘 --dwell 21 을
    #   붙여 왔기에 드러나지 않았을 뿐이다. 기본값이 정본과 같아야 한다.
    ap.add_argument("--dwell", type=float, default=21.0, help="체류 시간(초). 정본 21 (D-074)")
    ap.add_argument("--speed", type=float, default=None, help="화선 속도(m/s). 없으면 설정값")
    ap.add_argument("--solve", type=float, default=None,
                    help="이 이동 여유(초)를 만드는 v 를 역산해서 쓴다")
    ap.add_argument("--nominal", action="store_true", help="명목 격자로 계산(대조용)")
    # ★ [2026-09-01] 런 중 대본 대조용. 게이트웨이가 이 파일을 읽어 **사망이 대본과 어긋나면
    #   그 자리에서 경고**한다(중단기준 S2/S3). 지금까지 게이트웨이는 대본을 몰라서
    #   「대본보다 20초 이른 사망」을 런이 끝난 뒤에야 알 수 있었다.
    #   시각은 **n01 사망 = 0** 기준 상대초다(절대시계를 맞출 필요가 없다).
    ap.add_argument("--emit-schedule", metavar="경로",
                    help="사망 대본을 JSON 으로 쓴다 (게이트웨이 --schedule 에 물린다)")
    args = ap.parse_args()

    # ★ [2026-09-01 전수 스캔] 여기 `vcfg = 0.00061` (D-069) 이 박혀 있었다.
    #   `--nominal` 은 **좌표**를 명목 격자로 쓰겠다는 뜻인데 **속도까지 두 세대 전 값으로**
    #   되돌리고 있었다. 그 모드로 대조표를 뽑으면 현재 대본과 안 맞는 숫자가 조용히 나온다.
    #   좌표만 바꾸고 v 는 양쪽 다 정본(deploy_config.json)에서 읽는다.
    if args.nominal:
        P = load_positions(nominal=True)
        _P2, d = load_positions()
        vcfg = float(d["config"]["v_front_expected"])
        src = "명목 격자 0.20 m (v 는 정본)"
    else:
        P, d = load_positions()
        vcfg = float(d["config"]["v_front_expected"])
        src = "실측 좌표 (measured=%s)" % d["deployment"].get("measured")

    r = {i: math.hypot(p[0] - ORIGIN[0], p[1] - ORIGIN[1]) for i, p in P.items()}
    order = sorted(r, key=lambda i: r[i])
    dr_min = min(r[order[k]] - r[order[k - 1]] for k in range(1, len(order)))

    if args.solve is not None:
        v = dr_min / (args.dwell + args.solve)
        how = "역산 (이동 %.1f초 목표)" % args.solve
    else:
        v = args.speed if args.speed else vcfg
        how = "지정" if args.speed else "설정값"

    rmin = r[order[0]]
    t = {i: (r[i] - rmin) / v for i in r}
    total = t[order[-1]]

    def lab(i):
        return "n%02d" % (i + 1)

    print("좌표 출처 : %s" % src)
    print("점화점    : (%.2f, %.2f) m" % ORIGIN)
    print("화선 속도 : %.6f m/s = %.3f mm/s   [%s]" % (v, v * 1000, how))
    print("체류      : %.1f 초" % args.dwell)
    print("총 런     : %s (%.0f 초)" % (ms(total), total))
    up = PREP_MIN + total / 60.0
    print("uptime 합 : %.1f 분 (준비 %.1f분 + 런)   %s" %
          (up, PREP_MIN,
           "★ 40분 경고선 초과" if up > UPTIME_WARN_MIN else "(40분 경고선 안)"))
    print("랩 여유   : %.1f 분 (랩 %.1f분)" % (WRAP_MIN - up, WRAP_MIN))
    print()
    if args.emit_schedule:
        import json as _json
        t0 = t[order[0]]                       # 첫 사망(n01)을 0 으로 놓는다
        sched = {
            "_doc": "런 중 대본 대조용. 시각은 **첫 사망(n01)=0** 기준 상대초. "
                    "게이트웨이가 --schedule 로 읽어 S2(이른 사망)·S3(대본에 없는 사망)를 "
                    "그 자리에서 잡는다. 손으로 고치지 말고 route_table.py 로 다시 뽑을 것.",
            "v_front_expected": vcfg,
            "dwell_s": args.dwell,
            "order": [int(i) for i in order],
            "death_s": {str(int(i)): round(t[i] - t0, 3) for i in order},
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.emit_schedule)), exist_ok=True)
        with open(args.emit_schedule, "w", encoding="utf-8") as _f:
            _json.dump(sched, _f, ensure_ascii=False, indent=1)
        print("대본 → %s  (노드 %d개, 첫 사망 기준 상대초)"
              % (args.emit_schedule, len(order)))
        print()

    print("| # | 노드 | 가열 시작 | 사망 | 앞 노드에서 이동 시간 | 이동 거리 |")
    print("|---|---|---|---|---|---|")
    prev = None
    tight = []
    for k, i in enumerate(order):
        heat = t[i] - args.dwell
        if prev is None:
            print("| %d | %s | %s | %s | — | — |" % (k + 1, lab(i), ms(heat), ms(t[i])))
        else:
            mv = heat - t[prev]
            dist = math.hypot(P[i][0] - P[prev][0], P[i][1] - P[prev][1]) * 100
            mark = "**" if mv < 15 else ""
            if mv < 15:
                tight.append((lab(prev), lab(i), mv, dist))
            print("| %d | %s | %s | %s | %s%.1f 초%s | %.1f cm |"
                  % (k + 1, lab(i), ms(heat), ms(t[i]), mark, mv, mark, dist))
        prev = i
    print()
    if tight:
        print("★ 15초 미만 구간 %d개:" % len(tight))
        for a, b, mv, dist in tight:
            print("   %s → %s : %.1f 초 · %.1f cm  %s"
                  % (a, b, mv, dist, "← 이동 실측 7초보다 짧다. 실행 불가" if mv < 7 else ""))
    else:
        print("15초 미만 구간: 없음")
    print()
    print("유도 상수 (코드가 자동 계산): dt_window = %.1f s · alert_horizon = %.1f s"
          % (0.36 / v, 0.20 / v))
    print("★ residual_gate_s 는 분포에서 뽑는 값이라 자동으로 안 따라온다 —")
    print("  scripts/derive_scale_constants.py 로 다시 뽑을 것.")


if __name__ == "__main__":
    main()
