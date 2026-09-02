"""export_snapshots.py — engine 시나리오 → 대시보드용 스냅샷 직렬화 (지시서 #3 §2).

코어 불변: engine이 이미 yield하는 Snapshot(dict)을 **직렬화만** 한다(estimator/network 손대지 않음, [D-019]).
같은 시드·시나리오를 ours·stock 두 모드로 돌려 대비 재생을 가능케 한다.

산출:
  results/dashboard/snapshots.json   # 스펙 산출물(서버/타 소비자용)
  dashboard/data.js                  # window.SNAPSHOTS=… (file:// 직접 열람용, [D-020])
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sim.config import Config
from sim.engine import Engine


def _round(o, nd=3):
    """중첩 구조의 float를 반올림(파일 크기 축소). dict의 int 키는 JSON에서 문자열로."""
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round(v, nd) for v in o]
    return o


def run_mode(cfg) -> tuple[list, dict]:
    eng = Engine(cfg)
    frames = [ _round(s) for s in eng.stream() ]
    summary = eng.summarize()
    return frames, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--theta", type=float, default=30.0)
    ap.add_argument("--speed", type=float, default=1.5)
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--cols", type=int, default=4)
    args = ap.parse_args()

    base = dict(seed=args.seed, theta_deg=args.theta, speed_true=args.speed,
                grid_rows=args.rows, grid_cols=args.cols)

    print("ours 모드 시뮬레이션…")
    ours_frames, ours_sum = run_mode(Config(mode="ours", **base))
    print("stock 모드 시뮬레이션…")
    stock_frames, stock_sum = run_mode(Config(mode="stock", **base))

    # 메타(정적 정보) — 첫 프레임에서 노드 좌표·경계 추출
    nodes0 = ours_frames[0]["nodes"]
    xs = [n["pos"][0] for n in nodes0]
    ys = [n["pos"][1] for n in nodes0]
    pad = 8.0
    cfg0 = Config(mode="ours", **base)

    payload = {
        "meta": {
            "note": "engine Snapshot 직렬화(코어 불변). ours/stock 동일 시드.",
            "config": {
                "seed": args.seed, "grid_rows": args.rows, "grid_cols": args.cols,
                "spacing_m": cfg0.spacing_m, "radio_range_m": cfg0.radio_range_m,
                "speed_true": args.speed, "theta_deg": args.theta,
                "alert_horizon": cfg0.alert_horizon, "dt": cfg0.dt,
            },
            "nodes": [{"id": n["id"], "pos": n["pos"], "is_sink": n["is_sink"]}
                      for n in nodes0],
            "fire_dir": _round(list(cfg0.direction())),
            "bounds": {"xmin": min(xs) - pad, "xmax": max(xs) + pad,
                       "ymin": min(ys) - pad, "ymax": max(ys) + pad},
            "summary": {"ours": _round(ours_sum), "stock": _round(stock_sum)},
        },
        "frames": {"ours": ours_frames, "stock": stock_frames},
    }

    outdir = os.path.join("results", "dashboard")
    os.makedirs(outdir, exist_ok=True)
    json_path = os.path.join(outdir, "snapshots.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    # file:// 직접 열람용 data.js
    js_path = os.path.join("dashboard", "data.js")
    with open(js_path, "w", encoding="utf-8") as f:
        f.write("window.SNAPSHOTS = ")
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    kb = os.path.getsize(json_path) / 1024
    print(f"\n[export] frames: ours={len(ours_frames)}, stock={len(stock_frames)}")
    print(f"[export] {json_path} ({kb:.0f} KB)")
    print(f"[export] {js_path}")
    print(f"[summary ours ] dir={ours_sum['final_dir_err_deg']}°, "
          f"speed_err={ours_sum['final_speed_err_pct']}%, "
          f"delivery={ours_sum['final_delivery_rate']}")
    print("대시보드: dashboard/index.html 을 브라우저로 열면 됩니다.")


if __name__ == "__main__":
    main()
