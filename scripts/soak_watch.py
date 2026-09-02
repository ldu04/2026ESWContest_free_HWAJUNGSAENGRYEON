"""soak_watch.py — 노드 소크(장시간 방치) 감시. 브리지 시리얼을 읽기만 한다.

★ 굽지 않는다. 펌웨어·설정을 바꾸지 않는다. 읽기 전용이다.
★ 본 목적은 **기준선 집합에서 빠지는 노드가 생기는 시각을 추적하는 것**이다.
★ 점호 기준은 사람 목록을 기다리지 않고 **시작 직후 합류 집합**으로 스스로 확정한다.
★ 기본은 여는 순간 DTR/RTS 로 브리지가 한 번 재부팅된다. 그게 t=0 이다.
  이미 안정된 판을 흔들면 안 될 때는 `--no-reset` 을 쓴다(그때 t=0 은 부팅 시각이 아니다).
  그때 나오는 `rst:0x1 (POWERON_RESET)` 은 **우리가 낸 것**이지 브라운아웃이 아니다.

부산물: 4시간은 `getNodeTime()` 의 71.58분 랩어라운드를 3회 이상 지난다.
        노드별 `nt` 역행을 세어 **실물에서 처음으로** 랩어라운드를 관측한다.

쓰는 법:
    python scripts/soak_watch.py --port COM3 --hours 4
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics as st
import sys
import time

# ★ 표준출력/표준오류 고정 — cp949 콘솔에서 문자 하나로 죽지 않게, 튕겨도 줄이 남게.
#   근거: docs/n07_사망시험_판정_20260901.md §7
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HB_PERIOD_S = 1.0        # config.h HEARTBEAT_MS 1000
SILENCE_S = 3.0          # config.h SILENCE_TIMEOUT_MS 3000
DROP_S = 10.0            # 이보다 오래 조용하면 '이탈'로 본다 (침묵 판정의 3배 여유)
BRIDGE_ID = 99
NT_WRAP_S = 4294.967296  # getNodeTime() uint32 마이크로초 → 71.58분

RE_TYPE = re.compile(r'"type"\s*:\s*"([A-Z]+)"')
RE_ID = re.compile(r'"id"\s*:\s*(\d+)')
RE_MID = re.compile(r'"mid"\s*:\s*(\d+)')
RE_ISROOT = re.compile(r'"is_root"\s*:\s*(\d+)')
RE_NT = re.compile(r'"nt"\s*:\s*([0-9.]+)')
# ★ [2026-08-31] 브리지 힙 계측(HEAP 줄)을 같이 모은다. 크래시 직전 값을 남기기 위한 것.
RE_HEAP = re.compile(r'"free"\s*:\s*(\d+).*?"min_free"\s*:\s*(\d+).*?"max_alloc"\s*:\s*(\d+)')
RE_RESET = re.compile(r'E BOD|Brownout|rst:0x|SW_CPU_RESET|POWERON_RESET|brownout', re.I)
# ★ [2026-09-01] 브리지 크래시 3종을 따로 센다. rst:0x 만 보면 '재부팅했다' 까지만 알고
#   **왜** 재부팅했는지를 놓친다. 원인마다 대책이 다르다:
#     abort()      힙 고갈/assert — max_alloc 추이와 같이 본다
#     Guru Meditation  널 포인터·정렬 오류 — 펌웨어 버그
#     task_wdt     워치독 — 블로킹이 길어졌다(송신 지연과 직결)
RE_CRASH = {
    'abort': re.compile(r'abort\(\) was called|assert failed', re.I),
    'guru': re.compile(r'Guru Meditation', re.I),
    'task_wdt': re.compile(r'task_wdt|Task watchdog', re.I),
}


def label(nid):
    return "브리지" if nid == BRIDGE_ID else "n%02d" % (nid + 1)


def hhmmss(s):
    s = int(s)
    return "%d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--hours", type=float, default=4.0)
    ap.add_argument("--baseline-s", type=float, default=120.0,
                    help="이 시간 동안 합류한 집합을 기준선으로 확정한다")
    ap.add_argument("--out", default=os.path.join("results", "hw", "soak_11node"))
    ap.add_argument("--focus", default="4", help="특별 추적할 라벨 nXX")
    ap.add_argument("--no-reset", dest="reset", action="store_false",
                    help="여는 순간 보드를 리셋하지 않는다. 이미 안정된 판을 흔들지 않고 " + 
                         "붙을 때 쓴다 — 그 대신 t=0 은 부팅 시각이 아니다.")
    args = ap.parse_args()

    import serial

    focus_ids = sorted({int(x) - 1 for x in re.split(r"[,\s]+", args.focus) if x.strip()})
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    # ★ buffering=1 (줄 단위). 블록 버퍼면 프로세스가 튕길 때 마지막 수십 KB 가 통째로
    #   사라진다 — 사고 직전 몇 초가 정확히 그 구간이다. 원문 로그는 사고 분석용이므로
    #   여기서 아끼면 안 된다.
    raw = open(args.out + "_raw.log", "w", encoding="utf-8", errors="replace", buffering=1)
    evf = open(args.out + "_events.csv", "w", newline="", encoding="utf-8")
    ev = csv.writer(evf)
    ev.writerow(["t_s", "t_hms", "event", "label", "node_id", "detail"])

    def emit(t, kind, nid, detail=""):
        ev.writerow([round(t, 2), hhmmss(t), kind,
                     label(nid) if nid is not None else "", nid if nid is not None else "", detail])
        evf.flush()

    print("포트 %s · 소크 %.1f시간 · 기준선은 첫 %.0f초 합류 집합으로 자동 확정"
          % (args.port, args.hours, args.baseline_s))
    print("★ 사람 점호 목록을 기다리지 않는다. 어느 보드를 꽂았는지는 아침에 사람이 확인한다.")
    sys.stdout.flush()

    if args.reset:
        ser = serial.Serial(args.port, 115200, timeout=1)
    else:
        # 리셋 없이 연다(dtr/rts 를 내린 채 개방) — 판을 흔들지 않는다.
        ser = serial.Serial()
        ser.port, ser.baudrate, ser.timeout = args.port, 115200, 1
        ser.dtr = False
        ser.rts = False
        ser.open()
    t0 = time.time()
    deadline = t0 + args.hours * 3600.0

    seen = {}          # id -> dict
    resets, parse_fail, other_types = [], 0, {}
    crashes = {k: 0 for k in RE_CRASH}     # 브리지 크래시 3종 집계
    heap = []   # (t, free, min_free, max_alloc)
    baseline = None
    dropped = set()
    last_status = 0.0
    bridge_mid = None

    def snapshot(now, final=False):
        rows = []
        for nid in sorted(seen):
            r = seen[nid]
            g = r["gaps"]
            span = max(1e-9, r["last"] - r["first"])
            rows.append({
                "label": label(nid), "node_id": nid, "hb_count": r["n"],
                "first_s": round(r["first"], 2), "last_s": round(r["last"], 2),
                "span_s": round(span, 2),
                "gap_median_s": round(st.median(g), 3) if g else None,
                "gap_p99_s": round(sorted(g)[int(len(g) * 0.99)], 3) if len(g) >= 100 else None,
                "gap_max_s": round(max(g), 3) if g else None,
                "gaps_over_silence": sum(1 for x in g if x > SILENCE_S),
                "dropouts": r["dropouts"], "downtime_s": round(r["downtime"], 1),
                "hb_yield_pct": round(100.0 * r["n"] / (span / HB_PERIOD_S), 1),
                "nt_wraps": r["wraps"], "nt_last": r["nt_last"],
                "in_baseline": (baseline is not None and nid in baseline),
                "currently_alive": (now - r["last"]) <= DROP_S,
            })
        s = {
            # ★ [2026-09-01] 이 주의문은 예전엔 "11구 허브 기준"으로 **고정 문자열**이었다.
            #   회차가 바뀌어도 그대로 찍혀 나가므로 산출물이 스스로 거짓말을 한다.
            #   실제로 합류한 노드 수로 매번 다시 쓴다.
            "_주의": ("이 회차에 합류한 노드는 %s대다. 전류는 대수에 비례하므로 "
                      "적은 대수의 무결이 16대 무결을 뜻하지 않는다. 전원 구성은 "
                      "산출물에 안 남으므로 사람이 따로 적어야 한다."
                      % (len([i for i in baseline if i != BRIDGE_ID]) if baseline else "?")),
            "16대_미측정": bool(baseline is None
                                or len([i for i in baseline if i != BRIDGE_ID]) < 16),
            "점호_출처": "사람 목록이 아니라 시작 직후 브리지가 읽은 합류 집합(자동 확정)",
            "port": args.port, "elapsed_s": round(now, 1), "final": final,
            "baseline_labels": [label(i) for i in sorted(baseline)] if baseline else None,
            "baseline_node_count": (len([i for i in baseline if i != BRIDGE_ID])
                                    if baseline else None),
            "미합류_후보": ([label(i) for i in range(16) if not baseline or i not in baseline]
                            if baseline else None),
            "bridge_mid": bridge_mid,
            "reset_markers": len(resets), "reset_lines": resets[:30],
            # ★ 크래시 3종 — 0 이 아니면 그 원인부터 본다(힙 / 펌웨어 버그 / 블로킹)
            "crash_counts": dict(crashes),
            "port_reset_on_open": bool(args.reset),
            "parse_fail": parse_fail, "other_types": other_types,
            "per_node": rows,
            "heap_samples": heap[-400:],
            "heap_free_min": (min(h[1] for h in heap) if heap else None),
            "heap_max_alloc_min": (min(h[3] for h in heap) if heap else None),
        }
        with open(args.out + "_summary.json", "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        return rows

    try:
        while time.time() < deadline:
            try:
                line = ser.readline().decode("utf-8", errors="replace").strip()
            except Exception as e:
                emit(time.time() - t0, "SERIAL_ERROR", None, str(e)[:120])
                print("  [시리얼 오류] %s" % e); break
            now = time.time() - t0

            # --- 기준선 확정 ---
            if baseline is None and now >= args.baseline_s:
                baseline = set(seen.keys())
                nodes = sorted(i for i in baseline if i != BRIDGE_ID)
                print()
                print("=" * 68)
                print("★ 기준선 확정 (t=%.0fs) — 노드 %d대 + 브리지 %s"
                      % (now, len(nodes), "O" if BRIDGE_ID in baseline else "★없음"))
                print("   합류: %s" % ", ".join(label(i) for i in nodes))
                miss = [i for i in range(16) if i not in baseline]
                if len(nodes) >= 11:
                    print("   판정: **11대 이상 합류 — 전원 정상.** 4시간 소크로 넘어간다.")
                else:
                    print("   판정: 11대 미만(%d대). **미합류 후보 = 전체 16 − 합류분 = %s**"
                          % (len(nodes), ", ".join(label(i) for i in miss)))
                    print("         어느 보드를 꽂았는지는 아침에 사람이 확인한다. 소크는 그대로 진행한다.")
                print("=" * 68); print()
                sys.stdout.flush()
                emit(now, "BASELINE", None,
                     "노드 %d대: %s" % (len(nodes), "|".join(label(i) for i in nodes)))

            # --- 이탈/복귀 판정 ---
            if baseline is not None:
                for nid in baseline:
                    r = seen.get(nid)
                    if r is None:
                        continue
                    silent = now - r["last"]
                    if nid not in dropped and silent > DROP_S:
                        dropped.add(nid)
                        r["dropouts"] += 1
                        r["drop_at"] = r["last"]
                        print("  [%s] ★ 이탈: %s (마지막 HB t=%.1fs)"
                              % (hhmmss(now), label(nid), r["last"]))
                        sys.stdout.flush()
                        emit(r["last"], "DROP", nid, "마지막 HB 이후 %.1fs 침묵" % silent)

            if not line:
                continue
            raw.write("%9.2f %s\n" % (now, line))

            # ★ 크래시 3종은 리셋 흔적보다 **먼저** 본다. `rst:0x` 는 결과이고 이쪽이 원인이다.
            #   어느 것이냐에 따라 대책이 갈린다(힙 / 펌웨어 버그 / 블로킹).
            for ckind, crx in RE_CRASH.items():
                if crx.search(line):
                    crashes[ckind] += 1
                    resets.append((round(now, 2), "CRASH_" + ckind, line[:120]))
                    emit(now, "CRASH_" + ckind, None, line[:110])
                    print("  [%s] ★★ 크래시(%s): %s" % (hhmmss(now), ckind, line[:70]))
                    sys.stdout.flush()

            if RE_RESET.search(line):
                tag = "EXPECTED_DTR_RESET" if now < 5.0 else "RESET_MARKER"
                resets.append((round(now, 2), tag, line[:120]))
                emit(now, tag, None, line[:110])
                if now >= 5.0:
                    print("  [%s] ★ 리셋/브라운아웃 흔적: %s" % (hhmmss(now), line[:80]))
                    sys.stdout.flush()
            if "PARSE_FAIL" in line:
                parse_fail += 1
                emit(now, "PARSE_FAIL", None, line[:110])

            mt = RE_TYPE.search(line)
            if not mt:
                continue
            typ = mt.group(1)
            if typ == "HEAP":
                mh = RE_HEAP.search(line)
                if mh:
                    heap.append((round(now, 1), int(mh.group(1)), int(mh.group(2)), int(mh.group(3))))
                continue
            if typ == "MESHID":
                m = RE_ISROOT.search(line)
                if m and m.group(1) == "1" and RE_MID.search(line):
                    bridge_mid = RE_MID.search(line).group(1)
                continue
            mi = RE_ID.search(line)
            if not mi:
                other_types[typ] = other_types.get(typ, 0) + 1
                continue
            nid = int(mi.group(1))
            m = RE_NT.search(line)
            nt = float(m.group(1)) if m else None

            if typ != "HB":
                other_types[typ] = other_types.get(typ, 0) + 1
                emit(now, typ, nid, line[:110])
                continue

            r = seen.get(nid)
            if r is None:
                r = seen[nid] = {"first": now, "last": now, "n": 1, "gaps": [],
                                 "dropouts": 0, "downtime": 0.0, "drop_at": None,
                                 "wraps": 0, "nt_last": nt}
                print("  [%s] 합류: %s (id %d) — 누적 %d"
                      % (hhmmss(now), label(nid), nid, len(seen)))
                sys.stdout.flush()
                emit(now, "JOIN", nid, "")
                continue

            gap = now - r["last"]
            r["gaps"].append(gap)
            if nid in dropped:
                dropped.discard(nid)
                down = now - (r["drop_at"] if r["drop_at"] is not None else now)
                r["downtime"] += down
                print("  [%s] ↩ 복귀: %s (이탈 %.1fs)" % (hhmmss(now), label(nid), down))
                sys.stdout.flush()
                emit(now, "REJOIN", nid, "이탈 지속 %.1fs" % down)
            if nt is not None and r["nt_last"] is not None and nt < r["nt_last"] - 1.0:
                r["wraps"] += 1
                emit(now, "NT_WRAP", nid, "nt %.1f -> %.1f (감소 %.1f)"
                     % (r["nt_last"], nt, r["nt_last"] - nt))
                print("  [%s] ⟳ nt 역행: %s  %.1f → %.1f  (랩어라운드 %.1f 예상)"
                      % (hhmmss(now), label(nid), r["nt_last"], nt, NT_WRAP_S))
                sys.stdout.flush()
            r["last"] = now
            r["n"] += 1
            r["nt_last"] = nt

            if now - last_status >= 300.0:
                last_status = now
                rows = snapshot(now)
                alive = sum(1 for x in rows if x["currently_alive"] and x["node_id"] != BRIDGE_ID)
                nd = sum(x["dropouts"] for x in rows)
                print("  [%s] 상태 — 살아있는 노드 %d / 기준선 %s · 누적 이탈 %d회 · 리셋흔적 %d"
                      % (hhmmss(now), alive,
                         len([i for i in baseline if i != BRIDGE_ID]) if baseline else "?",
                         nd, len([x for x in resets if x[1] != "EXPECTED_DTR_RESET"])))
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("  (Ctrl-C — 읽은 데까지로 정리한다)")
    finally:
        ser.close()
        raw.close()

    now = time.time() - t0
    if baseline is None:
        baseline = set(seen.keys())
    rows = snapshot(now, final=True)
    evf.close()

    nodes = [x for x in rows if x["node_id"] != BRIDGE_ID]
    base_nodes = [i for i in baseline if i != BRIDGE_ID]
    print()
    print("=" * 74)
    print("소크 종료 — %s (%.2f시간)" % (hhmmss(now), now / 3600.0))
    print("기준선(자동 확정): 노드 %d대 — %s"
          % (len(base_nodes), ", ".join(label(i) for i in sorted(base_nodes))))
    if len(base_nodes) < 11:
        print("★ 11대 미만이다. 미합류 후보 = 전체 16 − 합류분 = %s"
              % ", ".join(label(i) for i in range(16) if i not in baseline))
        print("  어느 보드를 실제로 꽂았는지는 **미확정** — 아침에 사람이 확인한다.")
    real_resets = [x for x in resets if x[1] != "EXPECTED_DTR_RESET"]
    print("리셋/브라운아웃 흔적 %d건(t=0 의 DTR 리셋 제외) · PARSE_FAIL %d건"
          % (len(real_resets), parse_fail))
    print()
    print("%-8s %8s %7s %9s %9s %8s %7s %8s %6s"
          % ("라벨", "HB수", "수율%", "간격중앙", "간격최대", "침묵초과", "이탈", "이탈시간", "nt랩"))
    for x in rows:
        print("%-8s %8d %7.1f %9s %9s %8d %7d %8.1f %6d"
              % (x["label"], x["hb_count"], x["hb_yield_pct"], x["gap_median_s"],
                 x["gap_max_s"], x["gaps_over_silence"], x["dropouts"],
                 x["downtime_s"], x["nt_wraps"]))
    print()
    for fid in focus_ids:
        f = next((x for x in rows if x["node_id"] == fid), None)
        print("--- 특별 추적 %s (NODE_ID %d) ---" % (label(fid), fid))
        if not f:
            print("    ★ 메시에 합류하지 않았다 — HB 0건.")
            print("    판정: **미확정** — 꽂지 않았을 수도, 합류 실패일 수도 있다. 아침에 사람이 확인한다.")
        else:
            ok = f["dropouts"] == 0 and f["hb_yield_pct"] >= 90
            print("    합류 O · HB %d건 · 수율 %.1f%% · 간격중앙 %s s · 최대 %s s"
                  % (f["hb_count"], f["hb_yield_pct"], f["gap_median_s"], f["gap_max_s"]))
            print("    이탈 %d회 · 총 이탈시간 %.1fs · 침묵초과 %d회"
                  % (f["dropouts"], f["downtime_s"], f["gaps_over_silence"]))
            print("    판정: %s" % ("**보드 정상 — LED 재납땜만 필요.**" if ok
                                    else "★ 합류는 했으나 하트비트가 불안정하다."))
    print()
    print("원문 → %s_raw.log · 이벤트 → %s_events.csv · 요약 → %s_summary.json"
          % (args.out, args.out, args.out))
    print("★ 이 결과는 **11구 허브 회차**다. 16대 동시 전원은 측정되지 않았다.")


if __name__ == "__main__":
    main()
