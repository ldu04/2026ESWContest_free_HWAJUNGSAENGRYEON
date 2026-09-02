# -*- coding: utf-8 -*-
"""본편 런(run_205330) 대표 수치 재계산 — 저장소 파일만으로 검산한다.

    python tools/recompute_run205330.py

무엇을 하나
    results/hw/run_205330.json (2026-09-01 16노드 실증의 프레임별 산출물) 과
    results/hw/run_205330_deaths.csv (사망 대장 16건) 만 읽어서
    docs/실측값_대장.md §6-A 의 네 값을 처음부터 다시 계산한다.

        방향 추정 오차   2.85 °
        속도 추정 오차   +1.67 %
        사망             16 / 16
        대피 경보        13 / 16 노드가 사망 전 수신

왜 있나
    보고서와 덱이 인용하는 수치를 저장소 밖의 무언가를 믿지 않고 확인할 수 있어야 한다.
    이 스크립트는 대장의 값을 **읽지 않는다.** 아래 EXPECTED 에 적힌 값과 비교만 한다.
    값이 어긋나면 0 이 아닌 코드로 끝난다.

참값의 정의 — 여기가 헷갈리는 지점이다
    「참값」은 세 가지로 정의될 수 있고 셋 다 값이 다르다(docs/방향참값_출처_20260830.md).
    보고서가 쓰는 헤드라인 참값은 그중 ① 이다.

        ① 점화점 → 판 중심          55.4826 °   ← 이 스크립트가 쓰는 값
        ② 국소 법선 벡터평균         57.2618 °
        ③ 전역 단일 평면적합         54.7696 °

    ① 의 「판 중심」은 **실측 좌표의 바운딩박스 중심** (0.3030, 0.3015) 이다(D-073).
    노드 좌표의 산술평균 (0.30244, 0.30150) 이 아니다 — 이 둘은 0.13° 차이를 낳는다.
    명목 격자(0.20 m 등간격) 기준이면 중심이 (0.3000, 0.3000) 이고 참값은 55.6698 ° 가 된다.
    D-073 이 명목 → 실측으로 고쳤고, 그래서 55.6698 → 55.4826 이 되었다.
"""

import csv
import io
import json
import math
import os
import statistics
import sys

# ── 상수 — 전부 출처가 있다 ────────────────────────────────────────────────
IGNITION = (0.02, -0.11)  # 점화점 [m]. docs/방향참값_출처_20260830.md
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_JSON = os.path.join(ROOT, "results", "hw", "run_205330.json")
DEATHS_CSV = os.path.join(ROOT, "results", "hw", "run_205330_deaths.csv")

# docs/실측값_대장.md §6-A 가 정본으로 못박은 값. 이 스크립트는 이것을 재현해야 한다.
EXPECTED = {
    "dir_err_deg": 2.85,
    "speed_err_pct": 1.67,
    "deaths": 16,
    "alerted_before_death": 13,
    "lead_min_s": 87,
    "lead_median_s": 344,
    "lead_max_s": 523,
    "lead_mean_s": 351,
}


def bearing_deg(dx, dy):
    """+x 축에서 반시계로 잰 각도 [deg]."""
    return math.degrees(math.atan2(dy, dx))


def main():
    for p in (RUN_JSON, DEATHS_CSV):
        if not os.path.isfile(p):
            print("없다: %s" % p)
            return 2

    with io.open(RUN_JSON, encoding="utf-8") as f:
        run = json.load(f)

    nodes = run["meta"]["nodes"]
    frames = run["frames"]["ours"]
    final = frames[-1]
    est = final["est"]

    # ── 1. 방향 ────────────────────────────────────────────────────────────
    # 참값: 점화점 → 판 중심(실측 좌표의 바운딩박스 중심)
    xs = [n["pos"][0] for n in nodes]
    ys = [n["pos"][1] for n in nodes]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    dir_true = bearing_deg(cx - IGNITION[0], cy - IGNITION[1])

    # 추정: 최종 프레임의 est.dir (단위벡터)
    dir_est = bearing_deg(est["dir"][0], est["dir"][1])
    dir_err = dir_est - dir_true

    # ── 2. 속도 ────────────────────────────────────────────────────────────
    v_est = est["speed"]
    v_true = run["meta"]["config"]["speed_true"]
    speed_err_pct = (v_est - v_true) / v_true * 100.0

    # ── 3. 사망 ────────────────────────────────────────────────────────────
    with io.open(DEATHS_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    death_t = {int(r["id"]): float(r["death_t_est"]) for r in rows}

    # ── 4. 대피 경보 ───────────────────────────────────────────────────────
    # ★ 리드타임의 사망시각은 **프레임에서 노드가 처음 DEAD 로 보인 시각**이다.
    #   deaths.csv 의 death_t_est(노드가 자기 시계로 각인한 값)가 아니다. 둘은 다르다:
    #
    #       프레임 state==DEAD   중앙 344 · 최대 523 · 평균 351   ← 대장 §6-A 의 정본
    #       deaths.csv           중앙 346 · 최대 526 · 평균 348
    #
    #   왜 프레임 쪽인가: 리드타임은 「경보가 켜진 뒤 그 노드가 관측에서 사라지기까지」의
    #   길이다. 경보 시각을 프레임에서 집으므로 사망 시각도 같은 시계(프레임 t)에서 집어야
    #   같은 축 위의 뺄셈이 된다. 각인 시각은 노드 자기 시계라 축이 다르다.
    #   (덱 차트도 같은 정의를 쓴다 — scripts/make_deck_charts.py 의 chart_leadtime)
    first_alert = {}
    dead_seen = {}
    for fr in frames:
        for a in fr["est"].get("alerts") or []:
            first_alert.setdefault(a["id"], fr["t"])
        for n in fr["nodes"]:
            if n.get("state") == "DEAD":
                dead_seen.setdefault(n["id"], fr["t"])
    leads = sorted(
        dead_seen[i] - first_alert[i]
        for i in first_alert
        if i in dead_seen and dead_seen[i] > first_alert[i]
    )
    # 참고용 — 각인 시각으로 잡으면 얼마나 달라지는지 함께 보여 준다.
    leads_stamp = sorted(
        death_t[i] - first_alert[i]
        for i in first_alert
        if i in death_t and death_t[i] > first_alert[i]
    )

    # ── 출력 ───────────────────────────────────────────────────────────────
    print("=" * 68)
    print("본편 런 재계산 — run_205330 (2026-09-01, ESP32 16노드)")
    print("=" * 68)
    print("최종 프레임        t = %.1f s  (프레임 %d개)" % (final["t"], len(frames)))
    print()
    print("판 중심(실측 바운딩박스)  ( %.4f , %.4f )  m" % (cx, cy))
    print("점화점                    ( %.4f , %.4f )  m" % IGNITION)
    print()
    print("방향  참값 %.4f °   추정 %.4f °   오차 %+.4f °  ->  %.2f °"
          % (dir_true, dir_est, dir_err, round(dir_err, 2)))
    print("속도  참값 %.7f   추정 %.9f   오차 %+.4f %%  ->  %+.2f %%"
          % (v_true, v_est, speed_err_pct, round(speed_err_pct, 2)))
    print("사망  %d / %d 노드" % (len(death_t), len(nodes)))
    print("경보  %d / %d 노드가 사망 전 수신" % (len(leads), len(nodes)))
    if leads:
        print("      리드타임  최소 %.0f · 중앙 %.0f · 최대 %.0f · 평균 %.0f 초"
              % (leads[0], statistics.median(leads), leads[-1], sum(leads) / len(leads)))
        print("      (참고) 각인 시각 기준이면  최소 %.0f · 중앙 %.0f · 최대 %.0f · 평균 %.0f 초"
              % (leads_stamp[0], statistics.median(leads_stamp),
                 leads_stamp[-1], sum(leads_stamp) / len(leads_stamp)))
    print()

    # ── 대조 ───────────────────────────────────────────────────────────────
    got = {
        "dir_err_deg": round(dir_err, 2),
        "speed_err_pct": round(speed_err_pct, 2),
        "deaths": len(death_t),
        "alerted_before_death": len(leads),
        "lead_min_s": round(leads[0]) if leads else -1,
        "lead_median_s": round(statistics.median(leads)) if leads else -1,
        "lead_max_s": round(leads[-1]) if leads else -1,
        "lead_mean_s": round(sum(leads) / len(leads)) if leads else -1,
    }
    print("docs/실측값_대장.md §6-A 대조")
    bad = 0
    for k, want in EXPECTED.items():
        ok = got[k] == want
        bad += 0 if ok else 1
        print("  %-22s 대장 %-8s 재계산 %-8s  %s"
              % (k, want, got[k], "일치" if ok else "★ 불일치"))
    print()
    if bad:
        print("★ %d개 항목이 대장과 다르다. 대장이나 이 스크립트 중 하나가 틀렸다." % bad)
        return 1
    print("전 항목 일치. 보고서의 대표 수치는 이 저장소의 파일만으로 재현된다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
