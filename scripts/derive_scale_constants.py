"""derive_scale_constants.py — [D-3] `residual_gate_s` 를 드라이런 잔차 분포에서 뽑는다.

왜 이 스크립트가 따로 있나
--------------------------
`dt_window` / `alert_horizon` / `speed_true` 는 물리에서 **닫힌 식**으로 나온다
(gateway.py `_derive_scale()`). 그러나 `residual_gate_s` 는 그렇지 않다 —
"국소 평면 적합이 얼마나 안 맞는가"는 격자 기하·사망 순서·측정 잡음이 함께 만드는 값이라
식이 아니라 **분포**에서 나온다. 그래서 드라이런을 돌려 잔차를 모으고 median + 3σ 를 쓴다.

★ 규율: 값을 보고 기준을 옮기지 않는다.
  여기서 뽑은 수를 `gateway/deploy_config.json` 의 `residual_gate_s` 에 **적은 다음**
  판정한다. 판정 결과가 마음에 안 든다고 이 스크립트를 다시 돌려 값을 바꾸지 않는다.

잔차의 정의는 `sim/verification.py::Verifier._residual` 과 **같다**:
  대상 노드 i 의 이웃 중 이미 채택된 사망들 {j} 로 평면 t = a·x + b·y + c 를 최소제곱 적합하고,
  |t_i - (a·x_i + b·y_i + c)| 를 잔차로 쓴다. 자기 자신은 적합에 넣지 않는다.
  (여기서 sim 을 import 하지 않고 같은 식을 다시 쓰는 이유: 이 스크립트는 CSV 만 읽는
   사후 분석이라 Verifier 의 내부 장부 상태가 필요 없기 때문이다. 식은 동일하다.)

쓰는 법
-------
    python scripts/derive_scale_constants.py                 # 드라이런까지 자동
    python scripts/derive_scale_constants.py --deaths <csv>  # 이미 있는 사망 대장으로
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY = os.path.join(ROOT, "gateway", "deploy_config.json")
STREAM = os.path.join(ROOT, "results", "dashboard", "dryrun_fw_stream.jsonl")
DEATHS = os.path.join(ROOT, "results", "dashboard", "dryrun_deaths.csv")


def run_dryrun(deploy_path: str, v_front: float, theta_deg: float, out_stream: str,
               out_deaths: str) -> None:
    """벤치 규모(느린 전선)로 펌웨어 방언 스트림을 만들고 어댑터+게이트웨이에 통과시킨다."""
    with open(deploy_path, encoding="utf-8") as f:
        dep = json.load(f)
    rows = dep["deployment"]["grid_rows"]
    cols = dep["deployment"]["grid_cols"]
    sp = dep["deployment"]["spacing_m"]
    # 전선이 격자를 완전히 가로지르는 시간 + 여유. 짧으면 뒤쪽 노드가 안 죽어 표본이 준다.
    span = math.hypot((cols - 1) * sp, (rows - 1) * sp)
    t_max = span / v_front * 1.6 + 60.0
    os.makedirs(os.path.dirname(out_stream), exist_ok=True)
    print(f"[dryrun] 격자 대각 {span:.3f} m / v {v_front:g} m/s → t_max {t_max:.0f} s")
    sys.path.insert(0, os.path.join(ROOT, "gateway"))
    from mock_fw_serial import generate            # noqa: E402
    n = 0
    with open(out_stream, "w", encoding="utf-8") as f:
        for line in generate(deploy_path=deploy_path, fake=1, theta_deg=theta_deg,
                             speed=v_front, t_max=t_max,
                             warm_scale=sp * 0.45):   # 온도 상승 스케일도 격자에 맞춘다
            f.write(line.rstrip("\n") + "\n")
            n += 1
    print(f"[dryrun] 합성 펌웨어 스트림 {n}줄 → {out_stream}")
    cmd = [sys.executable, os.path.join(ROOT, "gateway", "gateway.py"),
           "--fw", "--in", out_stream, "--deploy", deploy_path,
           "--out-deaths", out_deaths]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    for ln in (r.stdout or "").splitlines():
        print("   | " + ln)
    if r.returncode != 0:
        print((r.stderr or "")[-2000:], file=sys.stderr)
        raise SystemExit(f"gateway 실패 (exit {r.returncode})")


def residuals(deploy_path: str, deaths_csv: str):
    with open(deploy_path, encoding="utf-8") as f:
        dep = json.load(f)
    rr = float(dep["config"]["radio_range_m"])
    pos = {int(n["id"]): (float(n["x"]), float(n["y"])) for n in dep["nodes"]}
    rows = []
    with open(deaths_csv, encoding="utf-8-sig", newline="") as f:
        for d in csv.DictReader(f):
            if str(d.get("accepted", "1")).strip() not in ("1", "True", "true"):
                continue
            rows.append((int(d["id"]), float(d["death_t_est"])))
    if not rows:
        raise SystemExit("채택된 사망이 0건이다 — 잔차를 뽑을 표본이 없다.")
    rows.sort(key=lambda r: r[1])                 # 사망 시각 순 = 채택된 순서
    tmap, out, skipped = {}, [], 0
    for uid, t in rows:
        if uid not in pos:
            continue
        nb = [j for j in tmap
              if math.hypot(pos[uid][0] - pos[j][0], pos[uid][1] - pos[j][1]) <= rr + 1e-12]
        if len(nb) < 3:                            # 평면 3파라미터 → 하한 3
            skipped += 1
            tmap[uid] = t
            continue
        A = np.array([[pos[j][0], pos[j][1], 1.0] for j in nb])
        b = np.array([tmap[j] for j in nb])
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        out.append(abs(t - (sol[0] * pos[uid][0] + sol[1] * pos[uid][1] + sol[2])))
        tmap[uid] = t
    return out, skipped, len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", default=DEPLOY)
    ap.add_argument("--deaths", default=None, help="이미 있는 사망 대장 CSV")
    ap.add_argument("--thetas", default="0,30,45,60,90,135,210,315",
                    help="드라이런 전선 방향 목록(도). 한 방향만 보면 그 기하에 과적합된다.")
    args = ap.parse_args()

    with open(args.deploy, encoding="utf-8") as f:
        dep = json.load(f)
    v = float(dep["config"]["v_front_expected"])
    rr = float(dep["config"]["radio_range_m"])
    sp = float(dep["config"]["spacing_m"])
    print("=" * 72)
    print("규모 상수 유도 — v_front_expected = %.6g m/s" % v)
    print("  dt_window     = %.4g / %.6g = %10.1f s" % (rr, v, rr / v))
    print("  alert_horizon = %.4g / %.6g = %10.1f s" % (sp, v, sp / v))
    print("  speed_true    = %.6g m/s (단일화)" % v)
    print("=" * 72)

    if args.deaths is not None:
        res, skipped, n = residuals(args.deploy, args.deaths)
    else:
        # ★ 한 방향만 보면 그 방향의 기하에 맞춘 문턱이 된다. 전선 방향을 바꿔가며 모아
        #   **방향에 상관없이** 버틸 문턱을 잡는다. 표본 수도 이래야 의미 있게 확보된다.
        thetas = [float(x) for x in args.thetas.split(",") if x.strip()]
        res, skipped, n = [], 0, 0
        for th in thetas:
            print()
            print("-" * 72)
            print("[dryrun] theta = %.1f 도" % th)
            st = STREAM.replace(".jsonl", "_t%03d.jsonl" % int(round(th)))
            dc = DEATHS.replace(".csv", "_t%03d.csv" % int(round(th)))
            run_dryrun(args.deploy, v, th, st, dc)
            r1, s1, n1 = residuals(args.deploy, dc)
            print("   잔차 %d건 (건너뜀 %d)" % (len(r1), s1))
            res += r1; skipped += s1; n += n1
        print("-" * 72)
    if not res:
        raise SystemExit("잔차 표본이 0개다 — 이웃 3개 이상 확보된 사망이 없다.")
    a = np.array(res)
    med, sd = float(np.median(a)), float(a.std(ddof=1)) if len(a) > 1 else 0.0
    gate = med + 3.0 * sd
    print()
    print("국소 적합 잔차 (sim/verification.py::_residual 과 같은 식)")
    print("  채택 사망 %d건 중 표본 %d건 (이웃<3 이라 건너뛴 것 %d건)" % (n, len(a), skipped))
    print("  min %.2f · median %.2f · mean %.2f · max %.2f · sigma %.2f  (초)"
          % (a.min(), med, a.mean(), a.max(), sd))
    print("  ★ residual_gate_s = median + 3sigma = %.2f + 3 x %.2f = **%.1f s**" % (med, sd, gate))
    print()
    print("  이 값을 gateway/deploy_config.json 의 config.residual_gate_s 에 적는다.")
    print("  (sim 기본값 2.0 s 는 시뮬 규모다. 벤치에서 그대로 쓰면 분기③이 전건 기각된다.)")
    return gate


if __name__ == "__main__":
    main()
