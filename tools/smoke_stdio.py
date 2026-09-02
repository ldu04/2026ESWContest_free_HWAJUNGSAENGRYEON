"""smoke_stdio.py — **cp949 환경에서 실제로 실행해** 인코딩으로 죽는 스크립트를 잡는다.

정적 감사(`encoding_audit.py`)만으로는 부족하다. f-string 으로 조립되는 문자,
서드파티가 뱉는 문자, 트레이스백 경로까지는 못 본다. **돌려 보는 게 유일한 증명**이다.

방법: `PYTHONIOENCODING=cp949` 를 걸고 `--help` 로 띄운다. argparse 는 도움말을
찍고 나가므로 하드웨어를 건드리지 않는다(모듈 최상위에 부작용이 없는지는 사전에 확인했다).

판정
  PASS   종료코드 0 또는 2(argparse 사용법 오류) — 둘 다 인터프리터가 살아서 나간 것
  FAIL   UnicodeEncodeError / UnicodeDecodeError 가 stderr 에 보이면 무조건 실패
  SKIP   타임아웃(장시간 실행형) — 죽지 않은 것은 확인됐다

    python tools/smoke_stdio.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOTS = ["scripts", "gateway", "tools", "firmware", "viz", "dashboard"]
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
TIMEOUT = 25
UNI = ("UnicodeEncodeError", "UnicodeDecodeError")


def entry_points():
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in SKIP_DIRS]
            for f in sorted(fn):
                if not f.endswith(".py") or f.startswith("_"):
                    continue
                p = os.path.join(dp, f)
                src = open(p, encoding="utf-8", errors="replace").read()
                if os.path.abspath(p) == os.path.abspath(__file__):
                    continue                      # 자기 자신은 건너뛴다(재귀)
                if "__main__" in src and "argparse" in src:
                    yield p


def main():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp949"          # ★ 사용자 콘솔과 같은 조건으로 강제
    env["PYTHONUTF8"] = "0"
    rows = []
    for p in entry_points():
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, p, "--help"], env=env,
                               capture_output=True, timeout=TIMEOUT)
            err = r.stderr.decode("utf-8", "replace")
            uni = [u for u in UNI if u in err]
            if uni:
                verdict, note = "FAIL", uni[0]
            elif r.returncode in (0, 2):
                verdict, note = "PASS", "rc=%d" % r.returncode
            else:
                verdict, note = "FAIL", "rc=%d · %s" % (r.returncode, err.strip().splitlines()[-1:] or "")
        except subprocess.TimeoutExpired:
            verdict, note = "SKIP", "타임아웃 %ds — 죽지는 않았다" % TIMEOUT
        rows.append((verdict, p.replace("\\", "/"), note, time.time() - t0))

    n_fail = sum(1 for v, *_ in rows if v == "FAIL")
    for v, p, note, dt in rows:
        if v != "PASS":
            print("  %-5s %-44s %s" % (v, p, note))
    print()
    print("진입점 %d개 · PASS %d · FAIL %d · SKIP %d"
          % (len(rows), sum(1 for v, *_ in rows if v == "PASS"), n_fail,
             sum(1 for v, *_ in rows if v == "SKIP")))
    print("★ cp949 스모크 %s" % ("통과" if n_fail == 0 else "실패 — 위 FAIL 을 고쳐라"))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
