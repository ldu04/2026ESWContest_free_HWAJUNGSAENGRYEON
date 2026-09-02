"""run_experiment.py — stock vs ours 비교 + 파라미터 스윕 → 지표 CSV (지시서 #1 §7, §11-DoD 3).

산출:
  results/comparison_stock_vs_ours.csv   # 같은 시나리오, 두 모드 대비표
  results/density_sweep.csv              # 노드 밀도↑ 시 추정 정밀도↑ 근거
  results/verification_sweep.csv         # K_confirm·silence_timeout 오탐/미탐 트레이드오프
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 콘솔(cp949)에서도 한글 출력이 깨지지 않도록 UTF-8로 재설정.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from sim.config import Config
from sim.engine import Engine


def run_one(**overrides) -> dict:
    cfg = Config(**overrides)
    eng = Engine(cfg)
    for _ in eng.stream():
        pass
    return eng.summarize()


def write_csv(path, rows, fields):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"[csv] {path}  ({len(rows)} rows)")


def print_table(title, rows, fields):
    print(f"\n=== {title} ===")
    print(" | ".join(f"{f}" for f in fields))
    for r in rows:
        print(" | ".join(f"{r.get(f)}" for f in fields))


def experiment_comparison(outdir):
    rows = []
    for mode in ("stock", "ours"):
        s = run_one(mode=mode)
        rows.append(s)
    fields = ["mode", "n_nodes", "final_delivery_rate", "reroute_delay_ms_mean",
              "reroute_delay_ms_max", "final_dir_err_deg", "final_speed_err_pct",
              "final_arrival_err_s", "confirmed_deaths", "false_positive_rate"]
    write_csv(os.path.join(outdir, "comparison_stock_vs_ours.csv"), rows, fields)
    print_table("stock vs ours (같은 화재 시나리오)", rows, fields)
    print("  >> stock = 연결성/전달률만. ours = 화선 방향·속도·ETA 추가(추정 컬럼).")


def experiment_density(outdir):
    # (rows, cols): 9, 12, 16, 20, 25 노드
    grids = [(3, 3), (4, 3), (4, 4), (4, 5), (5, 5)]
    rows = []
    for r, c in grids:
        s = run_one(mode="ours", grid_rows=r, grid_cols=c)
        s["grid"] = f"{r}x{c}"
        rows.append(s)
    fields = ["grid", "n_nodes", "final_dir_err_deg", "final_speed_err_pct",
              "final_arrival_err_s", "final_delivery_rate"]
    write_csv(os.path.join(outdir, "density_sweep.csv"), rows, fields)
    print_table("노드 밀도 스윕 (밀도↑ → 추정 정밀도↑ = 성김 방어 근거)", rows, fields)


def experiment_verification(outdir):
    rows = []
    for K in (2, 3, 4):
        for st in (2.0, 3.0, 4.0):
            # dropout을 높여 오탐 압박을 준다
            s = run_one(mode="ours", K_confirm=K, silence_timeout=st, p_dropout=0.08)
            s["K_confirm"] = K
            s["silence_timeout"] = st
            rows.append(s)
    fields = ["K_confirm", "silence_timeout", "false_positive_rate",
              "detect_lag_s_mean", "confirmed_deaths", "final_dir_err_deg"]
    write_csv(os.path.join(outdir, "verification_sweep.csv"), rows, fields)
    print_table("오탐 방어 스윕 (K·timeout ↔ 오탐률/미탐지연 트레이드오프, dropout=0.08)",
                rows, fields)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="results")
    ap.add_argument("--only", choices=["comparison", "density", "verification"],
                    default=None, help="특정 실험만 실행")
    args = ap.parse_args()

    if args.only in (None, "comparison"):
        experiment_comparison(args.outdir)
    if args.only in (None, "density"):
        experiment_density(args.outdir)
    if args.only in (None, "verification"):
        experiment_verification(args.outdir)

    print("\n완료. CSV는 results/ 에 저장됨.")


if __name__ == "__main__":
    main()
