"""run_demo.py — 한 번 실행 + 애니메이션 (지시서 #1 §11-DoD 1).

애니메이션에서 (노드 순차 사망 → 경로 자가치유 → 추정 화살표가 참 전선을 추종 → 대피경보)가 보인다.

사용:
    python scripts/run_demo.py                     # 기본(ours), results/demo.gif 저장
    python scripts/run_demo.py --show              # 창으로 표시
    python scripts/run_demo.py --mode stock        # 비교용 stock
    python scripts/run_demo.py --save results/demo.mp4
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from sim.config import Config
from sim.engine import Engine
from viz.animate import render


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["ours", "stock"], default="ours")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--theta", type=float, default=30.0)
    ap.add_argument("--speed", type=float, default=1.5)
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--save", default="results/demo.gif",
                    help="저장 경로(.gif/.mp4). --show와 함께면 둘 다.")
    ap.add_argument("--show", action="store_true", help="창으로 표시(비저장)")
    ap.add_argument("--fps", type=int, default=12)
    args = ap.parse_args()

    cfg = Config(mode=args.mode, seed=args.seed, theta_deg=args.theta,
                 speed_true=args.speed, grid_rows=args.rows, grid_cols=args.cols)

    eng = Engine(cfg)
    snapshots = list(eng.stream())
    summary = eng.summarize(os.path.join(cfg.results_dir, f"metrics_{args.mode}.csv"))

    print(f"\n=== 실행 요약 (mode={args.mode}) ===")
    for k, v in summary.items():
        print(f"  {k:24s}: {v}")
    print(f"  스냅샷 프레임 수         : {len(snapshots)}")

    save = None if args.show and args.save == "results/demo.gif" else args.save
    render(snapshots, cfg, save_path=save, show=args.show, fps=args.fps)


if __name__ == "__main__":
    main()
