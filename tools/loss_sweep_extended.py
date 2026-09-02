"""loss_sweep_extended.py — 패킷 유실 스윕을 **실제 동작점까지** 늘린다. 합성 실험.

왜 (2026-09-01)
---------------
기존 강건성 실험(`scripts/run_night_experiments.py` exp_d)의 유실 스윕은
**p = 0.10 / 0.20 / 0.30** 까지다. 그런데 같은 날 소크에서 실측한 하트비트 유실은
**약 0.93** 이다(도착률 5~9%). **검증한 범위 밖에 실제가 있다.**

이건 이 프로젝트가 전에도 한 번 당한 형태다 — 센서 열관성 τ 를 0~10초에서 검증했는데
실측은 11~92초였다(장애요인 ④). 같은 실수를 반복하지 않으려고 여기까지 늘려 본다.

유실이 무엇을 뜻하는지 주의:
  · exp_d 의 `loss_p` 는 **사망 사건이 게이트웨이에 도달하지 못할 확률**이다.
  · 임종신호(LG)는 `node.ino:424` 에서 **1회**만 나가므로, LG 유실 확률 ≈ 하트비트 유실 확률.
  · 따라서 **오늘 실측 동작점은 p ≈ 0.93** 이다.

★ 이 실험은 **합성**이다(전 행 fake=1). 실물에서 방향을 잰 적은 없다.

    python tools/loss_sweep_extended.py
"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.chdir(ROOT)

import run_night_experiments as X          # noqa: E402

# 실측 동작점(0.93)을 사이에 두고 촘촘히
PS = (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.93, 0.95)
N = 800

# 추정기가 성립하려면 사망이 최소 3건 필요하다(exp_d 의 `len(keep) < 3` 게이트).
MIN_DEATHS = 3


def main():
    print("=" * 78)
    print("  패킷 유실 확장 스윕 — 합성(fake=1) · 회당 %d회 · 사망 최소 %d건"
          % (N, MIN_DEATHS))
    print("  실측 동작점: 유실 ≈ 0.93 (하트비트 도착률 7.3%, 2026-09-01 소크)")
    print("=" * 78)

    # ★ 강령 §2·§4 — 원본 산출물을 덮어쓰지 않는다. exp_d 는 expD_packetloss.csv 로
    #   쓰도록 되어 있으므로, 쓰기 함수를 가로채 **새 파일**로 보낸다.
    #   8/31 회차의 원자료는 그대로 남는다.
    orig_write = X.write_csv

    def write_to_new(name, rows, fields):
        if name == "expD_packetloss.csv":
            name = "expD_packetloss_extended.csv"
        return orig_write(name, rows, fields)

    X.write_csv = write_to_new
    try:
        summ = X.exp_d(n=N, ps=PS)
    finally:
        X.write_csv = orig_write

    print()
    print("  유실 p   추정 성립   남은 사망   방향오차 중앙값   p90      최대")
    print("  " + "-" * 72)
    for p in PS:
        s = summ["p_%s" % p]
        ok = N - s["추정_불가_횟수"]
        e = s["오차"]
        star = "  ← 실측 동작점" if abs(p - 0.93) < 1e-9 else ""
        med = e.get("median")
        if med is None:
            print("  %5.2f   %4d/%d      %-9s  %s" % (p, ok, N, "-", "전부 추정 불가"))
            continue
        print("  %5.2f   %4d/%d      %7.2f     %8.2f°  %7.2f° %7.2f°%s"
              % (p, ok, N, s["남은_사망_평균"], med, e["p90"], e["max"], star))

    out = os.path.join(ROOT, "results", "night", "expD_packetloss_extended_summary.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "_주의": "전부 합성(fake=1). 실측 아님. 방향을 실물에서 잰 적은 없다.",
            "_왜": "기존 스윕은 p<=0.30 이었는데 실측 유실은 약 0.93 이다. 검증 범위 밖에 실제가 있었다.",
            "n_per_p": N,
            "min_deaths_for_estimate": MIN_DEATHS,
            "실측_동작점": {"p": 0.93, "근거": "하트비트 도착률 7.3% (results/hw/soak_16node_20260901_night_*)"},
            "sweep": summ,
        }, f, ensure_ascii=False, indent=2)
    print()
    print("  요약 → %s" % os.path.relpath(out, ROOT).replace("\\", "/"))
    print("  원자료 → results/night/expD_packetloss_extended.csv (원본 expD_packetloss.csv 는 그대로 둔다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
