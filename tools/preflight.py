"""preflight.py — 런 전 점검을 **한 줄로** 끝낸다.

왜 (2026-09-01)
---------------
지금은 사람이 절차서·조립카드·체크리스트를 오가며 눈으로 점검한다. 마감 직전 새벽에
그 방식은 반드시 한 칸을 빠뜨린다. 리허설 1회차는 「16대가 붙어 있다」를 런 시작 전에
증명하지 않아서 23분을 날렸다.

각 항목은 **FAIL 이면 무엇을 어떻게 고치는지 한 줄을 같이 찍는다.** 판정만 찍고
방법을 안 적으면 새벽에 다시 문서를 뒤지게 된다.

    python tools/preflight.py --no-hw          # 소프트웨어 항목만
    python tools/preflight.py --port COM4      # 브리지 포트까지 검사
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

CFG = os.path.join(ROOT, "gateway", "deploy_config.json")
DWELL_EXPECT = 21.0

# ★★ [2026-09-01 TRUTH AUDIT] 여기 있던 `V_EXPECT = 0.000523` 과 아래 하트비트 주기 1.0초는
#   **정본을 따라오지 못한 옛 값**이었다(정본: v 0.000579 D-075 · HEARTBEAT_MS 10000 결정 가′).
#   그대로 두면 이 도구가 **정상 설정·정상 메시를 불합격으로 판정**한다:
#     · v 비교      → 맞는 설정인데 "기대 0.000523" 으로 FAIL
#     · 도착률 계산 → 기대 개수가 10배 과다 → 도착률이 10배 낮게 나와 60% 문턱에 걸림
#   그래서 **숫자를 갱신하지 않고 정본에서 읽는다.** 다시 어긋날 수 없게 만드는 것이 요점이다.
def _read_firmware_heartbeat_s(default=10.0):
    """firmware/node/config.h 의 HEARTBEAT_MS 를 초로 돌려준다. 못 읽으면 default."""
    import re as _re
    p = os.path.join(ROOT, "firmware", "node", "config.h")
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            m = _re.search(r"#define\s+HEARTBEAT_MS\s+(\d+)", f.read())
        return int(m.group(1)) / 1000.0 if m else default
    except OSError:
        return default


HEARTBEAT_S = _read_firmware_heartbeat_s()        # 정본: firmware/node/config.h
UPTIME_LIMIT_S = 40 * 60          # 71.58분 랩어라운드 전에 여유를 둔다
# ⚠ 이 40분은 **랩어라운드 근거**다. 별개로 브리지 크래시가 **24.5분에 실측**된 적이 있다
#   (docs/실측값_대장.md:90, 「40분 규칙만으로는 부족하다」). 다만 그 관측은 구 펌웨어
#   (1 Hz · 15 msg/s) 기준이고 현재는 1.5 msg/s 라 **같은 문턱이 유효한지 미검증**이다.
#   추측으로 값을 바꾸지 않는다 — 재측정 뒤에 정한다.

rows = []          # (판정, 이름, 상세, 고치는 법)


def add(ok, name, detail, fix=""):
    rows.append((ok, name, detail, fix))


def skip(name, detail, fix=""):
    rows.append((None, name, detail, fix))


# ── 1. 좌표 ────────────────────────────────────────────────────────────
def c_coords():
    try:
        d = json.load(open(CFG, encoding="utf-8"))
    except Exception as e:
        add(False, "좌표 파일", "읽기 실패 %s" % e,
            "gateway/deploy_config.json 이 있는지 확인")
        return None
    m = d["deployment"].get("measured")
    s = ";".join("%d:%.4f,%.4f" % (n["id"], n["x"], n["y"])
                 for n in sorted(d["nodes"], key=lambda z: z["id"]))
    fp = hashlib.sha256(s.encode()).hexdigest()[:16]
    add(bool(m), "좌표 measured=true",
        "measured=%s · 노드 %d개 · 지문 %s" % (m, len(d["nodes"]), fp),
        "실측 좌표를 넣고 measured 를 true 로 (scripts/apply_measured_coords.py)")
    return d


# ── 2. 동선표 ↔ 설정 ───────────────────────────────────────────────────
def c_schedule(d):
    # ★ [2026-09-01] 옛날엔 여기서 하드코딩 상수(V_EXPECT)와 비교했다가, v 가 D-075 로
    #   바뀌자 **맞는 설정을 틀렸다고 판정**했다. 설정 파일이 정본이므로 값 자체를 검사하는
    #   대신 **유도값이 실제로 계산되는지**와 대본과의 정합만 본다.
    v = float(d["config"]["v_front_expected"])
    add(v > 0, "설정 v_front_expected",
        "%.6f m/s → dt_window %.1fs · alert_horizon %.1fs"
        % (v, float(d["config"]["radio_range_m"]) / v, float(d["config"]["spacing_m"]) / v),
        "0 이거나 음수면 dt_window 가 무한이 된다")
    try:
        import run_cue
        add(abs(run_cue.DWELL - DWELL_EXPECT) < 1e-9, "음성 큐 체류시간",
            "%.0f초 (기대 %.0f초)" % (run_cue.DWELL, DWELL_EXPECT),
            "scripts/run_cue.py 의 DWELL 과 절차서 1-B 를 함께 고칠 것")
    except Exception as e:
        add(False, "음성 큐 체류시간", "run_cue 임포트 실패: %s" % e, "")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "verify_cue_table.py")],
                       capture_output=True, cwd=ROOT)
    out = r.stdout.decode("utf-8", "replace").strip()
    add(r.returncode == 0, "음성 큐 - 동선표 16행",
        out.splitlines()[-1] if out else "출력 없음",
        "python scripts/route_table.py --dwell 21 로 절차서 1-B 를 다시 뽑을 것")
    # ★ 런 검산 문서에 옛 값이 되살아났는지. 여기가 틀리면 검산이 반대로 작동한다 —
    #   맞는 런을 틀렸다고 판정한다(2026-09-01 에 실제로 그 상태였다).
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_values.py")],
                       capture_output=True, cwd=ROOT)
    out = r.stdout.decode("utf-8", "replace").strip()
    line = [x for x in out.splitlines() if "런 검산 문서" in x]
    add(r.returncode == 0, "런 검산표 옛 값 없음",
        line[-1].strip() if line else "출력 없음",
        "python tools/check_values.py 로 위치를 보고 docs/실측값_대장.md 기준으로 고칠 것")


# ── 3. 도구 임포트/실행 ────────────────────────────────────────────────
TOOLS = ["voice", "run_cue", "temp_voice", "heat_one", "rollcall",
         "sensor_probe", "soak_watch", "t80_calibrate"]


def c_tools():
    bad = []
    env = dict(os.environ, PYTHONIOENCODING="cp949", PYTHONUTF8="0")
    for m in TOOLS:
        p = os.path.join(ROOT, "scripts", m + ".py")
        if not os.path.exists(p):
            bad.append("%s(없음)" % m)
            continue
        r = subprocess.run([sys.executable, p, "--help"],
                           capture_output=True, cwd=ROOT, env=env)
        if r.returncode not in (0, 2):
            bad.append("%s(rc=%d)" % (m, r.returncode))
    add(not bad, "도구 %d종 실행" % len(TOOLS),
        "전부 정상" if not bad else "실패: " + ", ".join(bad),
        "python tools/smoke_stdio.py 로 인코딩 문제를 먼저 볼 것")


# ── 4. 시간대 ──────────────────────────────────────────────────────────
def c_tz():
    off = -time.timezone if not time.daylight else -time.altzone
    add(off == 9 * 3600, "시간대 KST(UTC+9)",
        "UTC%+d (%s)" % (off / 3600, time.tzname[0]),
        "파이: sudo timedatectl set-timezone Asia/Seoul")


# ── 5. 디스크 ──────────────────────────────────────────────────────────
def c_disk():
    free = shutil.disk_usage(ROOT).free / (1024 ** 3)
    add(free >= 5.0, "디스크 여유", "%.1f GB" % free,
        "런 하나가 원문로그·스냅샷으로 수백 MB 를 쓴다. 5 GB 이상 비울 것")


# ── 6. 대시보드 ────────────────────────────────────────────────────────
def c_dashboard(url):
    idx = os.path.join(ROOT, "dashboard", "index.html")
    dat = os.path.join(ROOT, "dashboard", "data.js")
    add(os.path.exists(idx) and os.path.exists(dat), "대시보드 파일",
        "index.html %s · data.js %s"
        % ("있음" if os.path.exists(idx) else "없음",
           ("%.1f MB" % (os.path.getsize(dat) / 1e6)) if os.path.exists(dat) else "없음"),
        "게이트웨이를 --emit-dashboard 로 돌려 data.js 를 만들 것")
    if not url:
        skip("대시보드 서버", "URL 미지정 - 검사 안 함",
             "python -m http.server 8000 --directory dashboard 후 --dash-url 로 지정")
        return
    import urllib.request
    try:
        t0 = time.time()
        with urllib.request.urlopen(url, timeout=4) as r:
            code, ms = r.status, (time.time() - t0) * 1000
        add(code == 200, "대시보드 서버", "%s -> %d (%.0f ms)" % (url, code, ms),
            "python -m http.server 8000 --directory dashboard")
    except Exception as e:
        add(False, "대시보드 서버", "%s -> %s" % (url, e),
            "python -m http.server 8000 --directory dashboard")


# ── 7~9. 하드웨어 ──────────────────────────────────────────────────────
def c_hw(port, seconds):
    try:
        from serial.tools import list_ports
    except Exception as e:
        skip("하드웨어", "pyserial 없음: %s" % e, "pip install pyserial")
        return
    devs = [p.device for p in list_ports.comports()
            if "VID_10C4" in (p.hwid or "") or "CP210" in (p.description or "")]
    add(bool(devs), "CP210x 포트", "%d개 %s" % (len(devs), devs),
        "USB 허브·케이블을 확인할 것")
    if not port:
        skip("점호", "--port 미지정", "--port COM4 처럼 브리지 포트를 줄 것")
        return

    # ★ 포트 단독 점유: 누가 이미 잡고 있으면 게이트웨이가 못 연다.
    #   흔한 범인은 소크 감시기·temp_voice·앞 회차의 게이트웨이다.
    from open_noreset import open_serial
    try:
        s = open_serial(port, 115200, timeout=0.5)
    except Exception as e:
        add(False, "브리지 포트 단독 점유", "%s 열기 실패: %s" % (port, e),
            "그 포트를 잡고 있는 프로세스를 끌 것 (게이트웨이·temp_voice·소크가 흔한 범인)")
        return
    add(True, "브리지 포트 단독 점유", "%s 를 단독으로 열었다" % port, "")

    buf = b""
    seen = {}
    root_ms = None
    good = bad = 0
    t0 = time.time()
    while time.time() - t0 < seconds:
        c = s.read(4096)
        if not c:
            continue
        buf += c
        if b"\n" not in buf:
            continue
        parts = buf.split(b"\n")
        buf = parts.pop()
        for chunk in parts:
            ln = chunk.decode("utf-8", "ignore").strip()
            if not (ln.startswith("{") and ln.endswith("}")):
                bad += 1
                continue
            try:
                m = json.loads(ln)
            except Exception:
                bad += 1
                continue
            good += 1
            i = m.get("id")
            if m.get("type") == "HB" and isinstance(i, int):
                seen[i] = seen.get(i, 0) + 1
                if i == 99 and "ms" in m:
                    root_ms = m["ms"]
    s.close()

    missing = [i for i in range(16) if i not in seen]
    add(not missing, "점호 16 + 브리지",
        "응답 %d/16 · 브리지 %s · 무응답 %s"
        % (len([i for i in seen if i != 99]), "있음" if 99 in seen else "없음",
           ", ".join("n%02d" % (i + 1) for i in missing) or "없음"),
        "무응답 노드는 전원·합류를 볼 것. DEAD 인 노드는 HB 를 아예 안 보낸다(node.ino:121)")

    tot = good + bad
    add(bad <= good, "시리얼 품질",
        "정상 %d · 깨진 %d (%.0f%%)" % (good, bad, 100.0 * bad / max(1, tot)),
        "깨진 줄이 많으면 재생 고장이다. USB 케이블 교체 -> 포트 변경 -> 재삽입 순으로")

    # ★★ 하트비트 주기는 **firmware/node/config.h 에서 읽는다**(HEARTBEAT_S).
    #   이 자리에서 두 번 틀렸다:
    #     · 5초로 잘못 알고 도착률을 5배 부풀렸다 (2026-09-01 새벽)
    #     · 그 수정이 1.0초를 하드코딩해, 결정 (가′)로 10초가 된 뒤 **10배 낮게** 계산했다
    #       → 도착률 100% 인 완벽한 메시가 10% 로 찍혀 불합격이 된다
    #   상수를 복제하는 한 같은 사고가 반복된다. 정본에서 읽는 것이 유일한 해법이다.
    exp = seconds / HEARTBEAT_S
    ys = {i: 100.0 * n / max(1e-9, exp) for i, n in seen.items() if i != 99}
    if ys:
        lo = min(ys.values())
        mid = sorted(ys.values())[len(ys) // 2]
        # 임종신호(LG)는 이제 **LAST_GASP_REPEATS 회** 나간다(결정 가′, 기본 3회).
        #   한 발의 도달확률이 p 면 최소 한 발이라도 닿을 확률은 1-(1-p)^N 이다.
        #   즉 이 값은 「p」이고, 실제 사망 포착 확률은 그보다 높다. 그래도 p 가 낮으면
        #   투표(DV)·확정(DC)까지 같이 새므로 문턱은 유지한다.
        #   2026-09-01 n07 실사망 시험이 p=7.3% 에서 정확히 실패했다.
        _lg_n = 3
        try:
            import re as _re2
            with open(os.path.join(ROOT, "firmware", "node", "config.h"),
                      encoding="utf-8", errors="replace") as _f:
                _m = _re2.search(r"#define\s+LAST_GASP_REPEATS\s+(\d+)", _f.read())
            _lg_n = int(_m.group(1)) if _m else 3
        except OSError:
            pass
        _atleast1 = 100.0 * (1.0 - (1.0 - lo / 100.0) ** _lg_n)
        add(lo >= 60.0, "하트비트 도착률(%.0f초 주기)" % HEARTBEAT_S,
            "최저 %.1f%% · 중앙 %.1f%% · 임종신호 %d회 → 최소1발 도달 %.1f%%"
            % (lo, mid, _lg_n, _atleast1),
            "브리지 시리얼 재생 고장부터 볼 것 "
            "(위 「시리얼 품질」 항목) — docs/n07_사망시험_판정_20260901.md")

    if root_ms is not None:
        up = root_ms / 1000.0
        add(up < UPTIME_LIMIT_S, "브리지 uptime 40분 미만", "%.1f분" % (up / 60),
            "런 전에 전 노드·브리지 전원을 재인가할 것 (71.6분에 메시 시각이 되감긴다)")
    else:
        skip("브리지 uptime", "브리지 HB 를 못 봤다", "브리지가 붙어 있는지 확인")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None, help="브리지 시리얼 포트")
    ap.add_argument("--seconds", type=float, default=60.0, help="점호 관측 시간")
    ap.add_argument("--dash-url", default=None, help="예: http://127.0.0.1:8000/")
    ap.add_argument("--no-hw", action="store_true", help="하드웨어 항목을 건너뛴다")
    args = ap.parse_args()

    os.chdir(ROOT)
    print("=" * 74)
    print("  런 전 점검 - %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 74)
    d = c_coords()
    if d:
        c_schedule(d)
    c_tools()
    c_tz()
    c_disk()
    c_dashboard(args.dash_url)
    if args.no_hw:
        skip("하드웨어 전체", "--no-hw 로 건너뜀", "")
    else:
        c_hw(args.port, args.seconds)

    print()
    nfail = sum(1 for r in rows if r[0] is False)
    nskip = sum(1 for r in rows if r[0] is None)
    for ok, name, detail, fix in rows:
        tag = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
        print("  %-4s %-26s %s" % (tag, name, detail))
        if ok is False and fix:
            print("       고치는 법: %s" % fix)
    print()
    print("  PASS %d · FAIL %d · SKIP %d" % (len(rows) - nfail - nskip, nfail, nskip))
    print("  런 전 점검 %s" % ("통과 - 시작해도 된다" if nfail == 0
                               else "실패 %d항목 - 위 「고치는 법」부터" % nfail))
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
