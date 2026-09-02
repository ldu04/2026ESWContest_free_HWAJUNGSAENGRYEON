"""scan_literals.py — 실행 코드의 **숫자 상수를 전수로** 훑어 분류한다.

왜 (2026-09-01)
---------------
검사를 하나 만들 때마다 새 문제가 나와서 「언제 끝나는지」 알 수 없었다.
원인은 문제가 무한해서가 아니라, **값이 숨을 수 있는 자리를 전수로 열거한 적이 없어서**다.

    check_values  → 문서 문구만 봤다
    check_truth   → 내가 아는 모듈 상수만 봤다
    (둘 다)       → 함수 기본인자 · argparse default · PowerShell · JS · 테스트 기대값은 **한 번도 안 봤다**

이 도구는 그 자리를 **전부** 훑는다. 그리고 한 번 사람이 승인한 것은 baseline 에 적어 두고
**다음부터는 새로 생기거나 바뀐 것만** 보여준다. 불안을 「끝나지 않는 수색」에서
**「줄어드는 목록」**으로 바꾸는 것이 목적이다.

    python tools/scan_literals.py                  # 새/변경된 것만
    python tools/scan_literals.py --all            # 전부
    python tools/scan_literals.py --bless          # 현재 상태를 baseline 으로 승인

분류
----
    OLD_MATCH    옛 참값과 일치 → **위험**. 실행 경로면 즉시 확인
    CURRENT_DUP  현재 참값의 복제 → 정본에서 유도해야 할 후보(바뀌면 안 따라온다)
    UNKNOWN      정본과 무관한 숫자 → 사람이 한 번 보고 승인하면 끝

한계 (정직하게)
--------------
· 값은 맞는데 **의미가 틀린** 경우는 못 잡는다(같은 21.0 이 다른 개념일 수 있다)
· 숫자로 표현되지 않은 전제(「하트비트가 1Hz 라고 가정한 로직」)는 못 잡는다
· 파이 사본은 네트워크가 있어야 본다
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "tools", "literal_baseline.json")

# ── 훑을 자리 ──────────────────────────────────────────────────────────
#   ★ 「실행되는 것」만 본다. 문서는 check_values.py 가 따로 본다.
SCAN_DIRS = ["firmware", "gateway", "scripts", "sim", "tools", "tests", "dashboard"]
SCAN_EXT = (".py", ".ino", ".h", ".ps1", ".js")
SKIP_PARTS = ("__pycache__", "node_modules", ".venv", "/results/", "\\results\\",
              "data.js")          # data.js 는 24.5MB 생성물 — 코드가 아니다

# ── 무시해도 되는 숫자 ────────────────────────────────────────────────
#   0/1/2 같은 것과 배열 인덱스·색상·핀번호까지 잡으면 신호가 잡음에 묻힌다.
BENIGN = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100, 1000000, 255, 16, 24, 32, 64, 128, 512}


def _tokens(s):
    """검사에 쓸 만한 숫자 토큰만 뽑는다.

    ★ 왜 까다롭게 거르나 (2026-09-01 첫 실행에서 배운 것):
      「총 런 25:48」을 그냥 쪼개면 `25` 가 나오고, 그러면 `ambient=25.0` 이 전부
      "옛 참값"으로 잡힌다. 21건 중 20건이 그런 거짓 경보였다.
      **거짓 경보가 많은 도구는 무시당하고, 무시당하는 검사는 없는 것과 같다.**
      그래서 시:분 형식은 통째로만 쓰고, 3자리 미만 정수는 쓰지 않는다.
    """
    if ":" in s:                       # 25:48 · 12:12 → 쪼개지 않는다
        return set()
    out = set()
    for tok in re.findall(r"\d+\.\d+|\d+", s):
        if "." in tok or len(tok) >= 3:   # 0.000579 / 621.8 / 10000 은 쓰고, 21·18 은 안 쓴다
            out.add(tok)
    return out


def load_truth():
    """정본과 알려진 옛값. check_values.RULES 를 재사용해 **한 곳만** 관리한다."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import check_values as CV
    cur, old = {}, {}
    for name, c, olds in CV.RULES:
        for tok in _tokens(c):
            cur.setdefault(tok, name)
        for o in olds:
            for tok in _tokens(o):
                old.setdefault(tok, name)
    # 체류시간(21초)은 위 규칙에 걸려 빠지지만 **복제가 실재하는 값**이라 손으로 넣는다.
    cur.setdefault("21", "체류시간")
    return cur, old


def iter_files():
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        for dirpath, _dn, files in os.walk(base):
            for fn in files:
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, ROOT).replace("\\", "/")
                if not fn.endswith(SCAN_EXT):
                    continue
                if any(s.strip("/\\") in rel for s in SKIP_PARTS):
                    continue
                yield rel, p


def py_sites(path):
    """파이썬은 AST 로 본다 — **모듈 상수 · 함수 기본인자 · argparse default** 를
    구분해서 잡는다. 정규식만 쓰면 기본인자를 통째로 놓친다(실제 사각지대였다)."""
    out = []
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        # 모듈/클래스 레벨 대문자 상수
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and isinstance(node.value, ast.Constant) \
                        and isinstance(node.value.value, (int, float)):
                    kind = "CONST" if t.id.isupper() else "assign"
                    out.append((node.lineno, kind, t.id, node.value.value))
        # 함수 기본인자 ← 지금까지 한 번도 안 본 자리
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for a, d in zip(args.args[len(args.args) - len(args.defaults):], args.defaults):
                if isinstance(d, ast.Constant) and isinstance(d.value, (int, float)):
                    out.append((node.lineno, "default_arg",
                                "%s(%s=)" % (node.name, a.arg), d.value))
            for a, d in zip(args.kwonlyargs, args.kw_defaults):
                if isinstance(d, ast.Constant) and isinstance(d.value, (int, float)):
                    out.append((node.lineno, "default_arg",
                                "%s(%s=)" % (node.name, a.arg), d.value))
        # argparse add_argument(..., default=N)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "add_argument":
            flag = ""
            if node.args and isinstance(node.args[0], ast.Constant):
                flag = str(node.args[0].value)
            for kw in node.keywords:
                if kw.arg == "default" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, (int, float)):
                    out.append((node.lineno, "argparse", flag or "?", kw.value.value))
    return out


NUM = re.compile(r"(?<![\w.])(\d+\.\d+|\d{2,})(?![\w.])")


DEFINE = re.compile(r"^#define\s+(\w+)")
ASSIGN = re.compile(r"(?:^|\s)(?:\[\w+\]\s*)?(\$?\w+)\s*=\s*[-\d.]")


def text_sites(path):
    """파이썬이 아닌 것(.ino/.h/.ps1/.js)은 줄 단위로 본다. 주석은 건너뛴다.

    ★ 자리의 성격을 구분한다. `#define`·대입은 **설정 자리**이고, 식 한복판의 숫자는
      대개 계산이다(`millis()/1000.0`). 둘을 같이 취급하면 거짓 경보가 폭발한다.
    """
    out = []
    for i, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
        s = line.strip()
        if s.startswith(("//", "*", "/*")) or (s.startswith("#") and not s.startswith("#define")):
            continue
        code = re.split(r"//|#(?!define)", s)[0]
        md, ma = DEFINE.search(code), ASSIGN.search(code)
        kind = "define" if md else ("assign" if ma else "literal")
        name = (md.group(1) if md else (ma.group(1) if ma else s[:40]))
        for m in NUM.finditer(code):
            tok = m.group(1)
            try:
                v = float(tok) if "." in tok else int(tok)
            except ValueError:
                continue
            out.append((i, kind, name, v))
    return out


# 「참값이 숨는 자리」 — 여기서만 옛값/복제 판정을 한다.
#   식 한복판의 숫자(literal)는 대개 계산이므로 UNKNOWN 으로만 둔다.
CONFIG_SITES = {"CONST", "assign", "default_arg", "argparse", "define"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--bless", action="store_true", help="현재 상태를 baseline 으로 승인")
    args = ap.parse_args()

    cur_truth, old_truth = load_truth()
    base = {}
    if os.path.isfile(BASELINE):
        with open(BASELINE, encoding="utf-8") as f:
            base = json.load(f)

    found, rows = {}, []
    for rel, path in iter_files():
        sites = py_sites(path) if rel.endswith(".py") else text_sites(path)
        for lineno, kind, name, val in sites:
            if val in BENIGN or (isinstance(val, float) and val in {0.0, 1.0, 0.5}):
                continue
            tok = ("%g" % val)
            toks = {tok, ("%.6f" % val).rstrip("0") if isinstance(val, float) else tok}
            cls, why = "UNKNOWN", ""
            # 정본 파일 자신은 「복제」가 아니라 **원본**이다 — 여기서 값이 나오는 게 정상이다.
            if rel in ("firmware/node/config.h", "gateway/deploy_config.json"):
                pass
            elif kind in CONFIG_SITES:          # 설정 자리에서만 판정한다
                for t in toks:
                    if t in old_truth:
                        cls, why = "OLD_MATCH", old_truth[t]; break
                    if t in cur_truth:
                        cls, why = "CURRENT_DUP", cur_truth[t]
            key = "%s:%s:%s" % (rel, kind, tok)
            found[key] = cls
            if args.all or base.get(key) != cls:
                rows.append((cls, rel, lineno, kind, name, tok, why))

    if args.bless:
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(found, f, ensure_ascii=False, indent=0, sort_keys=True)
        print("baseline 승인 — 항목 %d개 → %s" % (len(found), os.path.relpath(BASELINE, ROOT)))
        print("다음부터는 **새로 생기거나 분류가 바뀐 것만** 뜬다.")
        return 0

    order = {"OLD_MATCH": 0, "CURRENT_DUP": 1, "UNKNOWN": 2}
    rows.sort(key=lambda r: (order[r[0]], r[1], r[2]))

    print("=" * 78)
    print("  숫자 상수 전수 스캔 — 실행 코드 %d파일" % len(list(iter_files())))
    print("=" * 78)
    n_new = len(rows)
    if not base:
        print("  baseline 없음 — **첫 실행이라 전부 나온다.** 훑어본 뒤 --bless 로 승인할 것.")
    print("  총 발견 %d · 이번에 보고 %d" % (len(found), n_new))
    print()

    for cls in ("OLD_MATCH", "CURRENT_DUP", "UNKNOWN"):
        sel = [r for r in rows if r[0] == cls]
        if not sel:
            continue
        print("  [%s]  %d건%s" % (cls, len(sel),
              "  ★ 옛 참값과 일치 — 실행 경로면 즉시 확인" if cls == "OLD_MATCH" else
              "  (정본에서 유도해야 할 후보)" if cls == "CURRENT_DUP" else ""))
        for _c, rel, ln, kind, name, tok, why in sel[:60 if cls != "UNKNOWN" else 25]:
            print("   %-42s:%-5d %-12s %-26s %s%s"
                  % (rel, ln, kind, str(name)[:26], tok, ("  ← " + why) if why else ""))
        if len(sel) > (60 if cls != "UNKNOWN" else 25):
            print("   ... 외 %d건" % (len(sel) - (60 if cls != "UNKNOWN" else 25)))
        print()

    n_old = sum(1 for r in rows if r[0] == "OLD_MATCH")
    print("  OLD_MATCH %d건" % n_old)
    return 1 if n_old else 0


if __name__ == "__main__":
    sys.exit(main())
