"""check_truth.py — TRUTH CONSISTENCY AUDIT 자동화. **정본에서 유도해 대조한다.**

왜 이게 `check_values.py` 와 다른가 (2026-09-01)
-----------------------------------------------
`check_values.py` 는 「옛 값 문자열」을 손으로 적은 표와 문서를 대조한다. 그래서
**그 표 자체가 옛 값이 되면 통과해도 아무 보장이 없다.** 실제로 오늘 그랬다:

    · v 가 0.000523 → 0.000579 (D-075) 로 갔는데 표의 정본은 0.000523 이었다
    · 하트비트가 1000 → 10000 ms (결정 가′) 가 됐는데 표의 정본은 1000 ms 였다

이 도구는 손으로 적은 정답표를 **두지 않는다.** 대신 **authoritative source 를 직접 읽어**
파생값을 계산하고, 그 값을 복제해 갖고 있는 모든 곳이 일치하는지 본다.
값을 바꾸면 「안 따라온 곳」이 자동으로 FAIL 로 뜬다.

    python tools/check_truth.py          # P0/P1 있으면 종료코드 1
    python tools/check_truth.py --all    # PASS 항목까지 전부 출력

authoritative source (정본)
---------------------------
    firmware/node/config.h        하트비트·침묵·임계·K_CONFIRM·임종신호·브리지번호
    gateway/deploy_config.json    좌표·간격·radio_range·v_front_expected·residual_gate_s
    scripts/route_table.py        동선표(총 런)를 계산하는 주체

여기서 유도되는 값(dt_window·alert_horizon·총 런 등)은 **어디에도 손으로 적지 않는 것이
원칙**이고, 문서에 적힌 것은 「사람이 눈으로 대조하는 사본」이므로 여기서 검사한다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RESULTS: list[tuple[str, str, bool, str]] = []      # (P등급, 이름, ok, 상세)


def check(level, name, ok, detail=""):
    RESULTS.append((level, name, bool(ok), detail))


def read(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def grab(text, pattern, cast=float):
    """정규식 첫 그룹을 뽑아 cast. 못 찾으면 None."""
    if text is None:
        return None
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return cast(m.group(1))
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════
# 1) 정본 읽기
# ══════════════════════════════════════════════════════════════════════
cfg_h = read("firmware/node/config.h")
gw_py = read("gateway/gateway.py")
cue_py = read("scripts/run_cue.py")
route_py = read("scripts/route_table.py")
pre_py = read("tools/preflight.py")

HEARTBEAT_MS = grab(cfg_h, r"#define\s+HEARTBEAT_MS\s+(\d+)", int)
SILENCE_MS = grab(cfg_h, r"#define\s+SILENCE_TIMEOUT_MS\s+(\d+)", int)
K_CONFIRM = grab(cfg_h, r"#define\s+K_CONFIRM\s+(\d+)", int)
LG_REPEATS = grab(cfg_h, r"#define\s+LAST_GASP_REPEATS\s+(\d+)", int)
LG_GAP_MS = grab(cfg_h, r"#define\s+LAST_GASP_GAP_MS\s+(\d+)", int)
LG_DELAY_MS = grab(cfg_h, r"#define\s+LAST_GASP_DELAY_MS\s+(\d+)", int)
TEMP_THR = grab(cfg_h, r"#define\s+TEMP_THRESHOLD_C\s+([\d.]+)f")
BRIDGE_IDX_FW = grab(cfg_h, r"#define\s+BRIDGE_INDEX\s+(\d+)", int)

dep = None
p = os.path.join(ROOT, "gateway", "deploy_config.json")
if os.path.isfile(p):
    with open(p, encoding="utf-8") as f:
        dep = json.load(f)

V = RADIO = SPACING = RESID = None
if dep:
    c = dep["config"]
    V, RADIO, SPACING, RESID = (float(c["v_front_expected"]), float(c["radio_range_m"]),
                                float(c["spacing_m"]), c.get("residual_gate_s"))

# ── 유도값 (여기가 유일한 계산 지점이다) ──
DT_WINDOW = (RADIO / V) if (RADIO and V) else None
ALERT_HORIZON = (SPACING / V) if (SPACING and V) else None


# ══════════════════════════════════════════════════════════════════════
# 2) 불변식 — 정본 안에서 성립해야 하는 관계
# ══════════════════════════════════════════════════════════════════════
def invariants():
    if HEARTBEAT_MS and SILENCE_MS:
        check("P0", "침묵문턱 = 3 × 하트비트", SILENCE_MS == 3 * HEARTBEAT_MS,
              "SILENCE_TIMEOUT_MS=%d · 3×HEARTBEAT_MS=%d" % (SILENCE_MS, 3 * HEARTBEAT_MS))
    if TEMP_THR:
        check("P0", "임계 80℃ (헌장 §1 동결값)", abs(TEMP_THR - 80.0) < 1e-9,
              "TEMP_THRESHOLD_C=%.1f" % TEMP_THR)
    if dep:
        ids = sorted(n["id"] for n in dep["nodes"])
        check("P0", "노드 id 0..15 연속 · 16개", ids == list(range(16)),
              "노드 %d개" % len(ids))
        check("P0", "브리지번호가 노드 id 와 겹치지 않음",
              dep["bridge_index"] not in ids, "bridge_index=%s" % dep["bridge_index"])
        if BRIDGE_IDX_FW is not None:
            check("P0", "브리지번호 펌웨어 ↔ 설정 일치",
                  BRIDGE_IDX_FW == dep["bridge_index"],
                  "config.h=%d · deploy_config=%s" % (BRIDGE_IDX_FW, dep["bridge_index"]))
        d = dep["deployment"]
        check("P1", "격자 4×4", d["grid_rows"] == 4 and d["grid_cols"] == 4,
              "%d×%d" % (d["grid_rows"], d["grid_cols"]))
    if V:
        check("P0", "v_front_expected > 0", V > 0, "%.6g m/s" % V)
    if LG_REPEATS:
        check("P1", "임종신호 반복 ≥ 1", LG_REPEATS >= 1, "LAST_GASP_REPEATS=%d" % LG_REPEATS)


# ══════════════════════════════════════════════════════════════════════
# 3) 전파 검사 — 정본을 복제해 갖고 있는 곳들이 따라왔는가
# ══════════════════════════════════════════════════════════════════════
def propagation():
    # ── 하트비트: firmware → gateway 감시견 ──
    hb_s = (HEARTBEAT_MS / 1000.0) if HEARTBEAT_MS else None
    gw_hb = grab(gw_py, r"HEARTBEAT_S_EXPECTED\s*=\s*([\d.]+)")
    if hb_s and gw_hb is not None:
        check("P0", "하트비트 firmware → gateway.py", abs(gw_hb - hb_s) < 1e-9,
              "config.h %.1fs ↔ HEARTBEAT_S_EXPECTED %.1fs" % (hb_s, gw_hb))

    # ── 하트비트: firmware → preflight 도착률 계산 ──
    #   preflight 는 `exp = seconds / <주기>` 로 기대 개수를 만든다. 주기가 어긋나면
    #   **정상 메시를 불합격으로 판정**한다(도착률이 배수만큼 틀리게 나온다).
    pre_div = grab(pre_py, r"exp\s*=\s*seconds\s*/\s*([\d.]+)")
    if hb_s and pre_div is not None:
        check("P0", "하트비트 firmware → preflight 도착률", abs(pre_div - hb_s) < 1e-9,
              "config.h %.1fs ↔ preflight 나눗수 %.1fs%s"
              % (hb_s, pre_div,
                 "  ★정상 런을 %.0f배 낮은 도착률로 오판" % (hb_s / pre_div)
                 if abs(pre_div - hb_s) > 1e-9 and pre_div else ""))

    # ── v: preflight 가 v 를 **하드코딩하지 않는가** ──
    #   예전엔 `V_EXPECT = 0.000523` 과 비교하다가 v 가 바뀌자 맞는 설정을 불합격시켰다.
    #   이제 preflight 는 설정 파일을 정본으로 쓴다. 그러므로 검사는 "값이 같은가"가 아니라
    #   **"실행되는 코드에 v 가 다시 박히지 않았는가"** 여야 한다.
    #   ★ 주석 줄은 제외한다 — 위 사고를 설명하는 주석에 옛 값이 들어 있는 것은 정상이다.
    code_lines = [ln for ln in (pre_py or "").splitlines()
                  if not ln.lstrip().startswith("#")]
    m_hard = re.search(r"^\s*V_EXPECT\s*=\s*([\d.eE+-]+)", "\n".join(code_lines), re.M)
    check("P0", "preflight 가 v 를 하드코딩하지 않음", m_hard is None,
          "정본(deploy_config)에서 읽음" if m_hard is None
          else "V_EXPECT=%s 가 코드에 살아 있다" % m_hard.group(1))

    # ── 체류(dwell): run_cue ↔ route_table ↔ preflight ↔ heat_one ──
    #   ★ [2026-09-01] heat_one 은 전수 스캔(tools/scan_literals.py)이 찾아냈다.
    #     내가 아는 3곳만 검사하고 있었는데 실제 복제는 **4곳**이었다.
    cue_dwell = grab(cue_py, r"(?m)^DWELL\s*=\s*([\d.]+)")
    rt_dwell = grab(route_py, r'--dwell".*?default=([\d.]+)')
    pre_dwell = grab(pre_py, r"DWELL_EXPECT\s*=\s*([\d.]+)")
    heat_dwell = grab(read("scripts/heat_one.py"), r'--dwell".*?default=([\d.]+)')
    vals = {"run_cue": cue_dwell, "route_table": rt_dwell, "preflight": pre_dwell,
            "heat_one": heat_dwell}
    have = {k: v for k, v in vals.items() if v is not None}
    if len(have) >= 2:
        check("P1", "체류시간 3곳 일치", len(set(have.values())) == 1,
              " · ".join("%s=%.0f" % (k, v) for k, v in have.items()))

    # ── 점화점(ORIGIN): run_cue ↔ route_table ↔ night_robustness ──
    pat = r"(?m)^ORIGIN\s*=\s*\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)"
    origins = {}
    for name, rel in (("run_cue", "scripts/run_cue.py"),
                      ("route_table", "scripts/route_table.py"),
                      ("night_robustness", "scripts/night_robustness.py")):
        txt = read(rel)
        m = re.search(pat, txt) if txt else None
        if m:
            origins[name] = (float(m.group(1)), float(m.group(2)))
    if len(origins) >= 2:
        check("P1", "점화점 ORIGIN 일치", len(set(origins.values())) == 1,
              " · ".join("%s=%s" % (k, v) for k, v in origins.items()))

    # ── v: deploy_config → 분석 스크립트가 자체 하드코딩을 들고 있지 않은가 ──
    nr = read("scripts/night_robustness.py")
    nr_v = grab(nr, r"(?m)^V_FRONT\s*=\s*([\d.eE+-]+)")
    if V and nr_v is not None:
        check("P1", "v → night_robustness V_FRONT", abs(nr_v - V) < 1e-12,
              "설정 %.6g ↔ 스크립트 %.6g" % (V, nr_v))

    # ── check_values.py 의 「정본」이 진짜 정본과 같은가 (메타 검사) ──
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import check_values as CV                                      # noqa: E402
        canon = {name: cur for name, cur, _old in CV.RULES}
        if V is not None:
            got = canon.get("화선 속도 v_front_expected")
            check("P1", "check_values 정본 v", got == ("%.10g" % V),
                  "표=%s · 실제=%s" % (got, "%.10g" % V))
        if DT_WINDOW:
            check("P1", "check_values 정본 dt_window",
                  canon.get("dt_window") == "%.1f" % DT_WINDOW,
                  "표=%s · 유도=%.1f" % (canon.get("dt_window"), DT_WINDOW))
        if ALERT_HORIZON:
            check("P1", "check_values 정본 alert_horizon",
                  canon.get("alert_horizon") == "%.1f" % ALERT_HORIZON,
                  "표=%s · 유도=%.1f" % (canon.get("alert_horizon"), ALERT_HORIZON))
        if HEARTBEAT_MS:
            check("P1", "check_values 정본 하트비트",
                  canon.get("하트비트 주기") == "%d ms" % HEARTBEAT_MS,
                  "표=%s · config.h=%d ms" % (canon.get("하트비트 주기"), HEARTBEAT_MS))
    except Exception as e:                                             # noqa: BLE001
        check("P1", "check_values 메타 검사", False, "불러오지 못했다: %r" % e)

    # ── sim 기본값 ↔ 펌웨어 (실물 경로에서 덮어쓰는 것은 제외) ──
    try:
        sys.path.insert(0, ROOT)
        from sim.config import Config                                  # noqa: E402
        c0 = Config()
        if TEMP_THR:
            check("P0", "임계 firmware ↔ sim", abs(c0.temp_threshold - TEMP_THR) < 1e-9,
                  "firmware %.1f ↔ sim %.1f" % (TEMP_THR, c0.temp_threshold))
            check("P0", "경고온도 = 0.75 × 임계",
                  abs(c0.warn_temp - TEMP_THR * 0.75) < 1e-6,
                  "sim warn_temp %.1f ↔ 0.75×%.1f=%.1f"
                  % (c0.warn_temp, TEMP_THR, TEMP_THR * 0.75))
        if K_CONFIRM:
            check("P0", "K_CONFIRM firmware ↔ sim", c0.K_confirm == K_CONFIRM,
                  "firmware %d ↔ sim %d" % (K_CONFIRM, c0.K_confirm))
        if LG_DELAY_MS:
            check("P1", "임종신호 지연 firmware ↔ sim",
                  abs(c0.last_gasp_delay - LG_DELAY_MS / 1000.0) < 1e-9,
                  "firmware %.1fs ↔ sim %.1fs" % (LG_DELAY_MS / 1000.0, c0.last_gasp_delay))
        # ★ heartbeat_period · silence_timeout 은 **시뮬 규모 상수**다.
        #   실물 경로는 gateway._derive_scale() 이 dt_window/alert_horizon 만 덮어쓰고
        #   이 둘은 쓰지 않는다(verification 의 실물 진입점 confirm_external 은 death_t_est 를
        #   인자로 직접 받는다). 그래서 **불일치가 정상**이며 여기서 FAIL 로 세지 않는다.
        check("P2", "sim 하트비트는 시뮬 규모(실물 경로 미사용)",
              True, "sim %.1fs ↔ firmware %.1fs — 설계상 별개"
              % (c0.heartbeat_period, (HEARTBEAT_MS or 0) / 1000.0))
    except Exception as e:                                             # noqa: BLE001
        check("P1", "sim.config 대조", False, "불러오지 못했다: %r" % e)


# ══════════════════════════════════════════════════════════════════════
# 4) 문서 사본 검사 — 사람이 눈으로 대조하는 숫자가 유도값과 같은가
# ══════════════════════════════════════════════════════════════════════
RUNTIME_DOCS = ["docs/D1_리허설_절차서.md", "docs/실측값_대장.md"]


def docs_copy():
    if not (DT_WINDOW and ALERT_HORIZON and V):
        return
    want = {
        "dt_window": "%.1f" % DT_WINDOW,
        "alert_horizon": "%.1f" % ALERT_HORIZON,
        "v(m/s)": "%.10g" % V,
    }
    for rel in RUNTIME_DOCS:
        txt = read(rel)
        if txt is None:
            continue
        missing = [k for k, s in want.items() if s not in txt]
        check("P1", "문서 사본 %s" % os.path.basename(rel), not missing,
              ("유도값 전부 등장" if not missing
               else "빠진 값: " + ", ".join("%s=%s" % (k, want[k]) for k in missing)))


# ══════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="PASS 항목까지 전부 출력")
    args = ap.parse_args()

    print("=" * 74)
    print("  TRUTH CONSISTENCY AUDIT — 정본에서 유도해 대조한다")
    print("=" * 74)
    print("  정본: firmware/node/config.h · gateway/deploy_config.json")
    print("  하트비트 %s ms · 침묵 %s ms · K_CONFIRM %s · 임종신호 %s회"
          % (HEARTBEAT_MS, SILENCE_MS, K_CONFIRM, LG_REPEATS))
    print("  v %.6g m/s → dt_window %.1f s · alert_horizon %.1f s · residual_gate %s s"
          % (V or 0, DT_WINDOW or 0, ALERT_HORIZON or 0, RESID))
    print()

    invariants()
    propagation()
    docs_copy()

    fails = [r for r in RESULTS if not r[2]]
    for level in ("P0", "P1", "P2"):
        rows = [r for r in RESULTS if r[0] == level and (args.all or not r[2])]
        if not rows:
            continue
        print("  [%s]" % level)
        for _lv, name, ok, detail in rows:
            print("   %-4s %-38s %s" % ("PASS" if ok else "FAIL", name, detail))
        print()

    n0 = sum(1 for r in fails if r[0] == "P0")
    n1 = sum(1 for r in fails if r[0] == "P1")
    print("  검사 %d건 · 실패 %d건 (P0 %d · P1 %d)" % (len(RESULTS), len(fails), n0, n1))
    print()
    if n0 or n1:
        print("TRUTH AUDIT STATUS: FAIL")
        return 1
    print("TRUTH AUDIT STATUS: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
