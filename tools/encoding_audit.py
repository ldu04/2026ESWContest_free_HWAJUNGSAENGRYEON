"""encoding_audit.py — cp949 콘솔에서 죽는 출력 문자를 전수로 찾는다. **읽기 전용.**

왜 필요한가 (2026-09-01)
------------------------
`rollcall.py` 는 첫 print 의 em dash(`—`, U+2014)를 cp949 로 인코딩하지 못해
`UnicodeEncodeError` 로 **즉사한다.** 표준출력이 UTF-8 콘솔이 아니면 항상 그렇다.
런 도중 도구가 이렇게 죽으면 「떼세요」 음성 큐가 울리지 않는다 — 실제로 났다.

한글은 문제가 아니다. cp949 에 있다. 문제는 **cp949 에 없는 문자**다:
  —(U+2014) ★은 있다 ↔ 화살표 → ← ↑ ↓ 일부 · 이모지 · ⚠ ⏱ ‼️ 🔊 √ ∇ ̂(결합문자)

    python tools/encoding_audit.py            # 감사만
    python tools/encoding_audit.py --json     # 기계 판독용
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import os
import sys
import tokenize

sys.stdout.reconfigure(encoding="utf-8")

ROOTS = ["scripts", "gateway", "firmware", "sim", "tests", "viz", "dashboard", "tools"]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}

# 진입점 판정: 이게 있으면 사람이 직접 실행할 수 있는 파일이다
ENTRY_MARK = 'if __name__ == "__main__"'
RECONF = "stdout.reconfigure"


# BOM(U+FEFF)은 파일 선두 표식이지 출력 문자가 아니다. PowerShell 은 오히려 이걸 보고
# 파일이 UTF-8 임을 안다 — 없애면 안 된다. 감사에서 제외한다.
IGNORE = {"﻿"}


def bad_chars(text: str) -> set:
    out = set()
    for ch in set(text):
        if ord(ch) < 128 or ch in IGNORE:
            continue
        try:
            ch.encode("cp949")
        except Exception:
            out.add(ch)
    return out


def py_string_literals(path: str):
    """문자열 리터럴만 뽑는다 — 주석·독스트링의 문자는 콘솔에 안 나가므로 제외한다."""
    lits = []
    try:
        src = open(path, encoding="utf-8").read()
    except Exception:
        return lits, None
    try:
        tree = ast.parse(src)
    except Exception as e:
        return lits, "파싱 실패: %s" % e
    # 독스트링 노드를 집합으로 모아 제외한다
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = getattr(node, "body", None)
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
               and isinstance(b[0].value.value, str):
                docs.add(id(b[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            lits.append((getattr(node, "lineno", 0), node.value))
    return lits, None


def audit_py(path: str):
    src = open(path, encoding="utf-8").read()
    lits, err = py_string_literals(path)
    hits = {}
    for lineno, s in lits:
        b = bad_chars(s)
        if b:
            hits.setdefault(lineno, set()).update(b)
    return {
        "path": path.replace("\\", "/"),
        "kind": "py",
        "entry": ENTRY_MARK in src or "argparse" in src,
        "reconfigured": RECONF in src,
        "hits": {str(k): "".join(sorted(v)) for k, v in sorted(hits.items())},
        "n_bad": sum(len(v) for v in hits.values()),
        "parse_error": err,
    }


def audit_ps1(path: str):
    src = open(path, encoding="utf-8", errors="replace").read()
    hits = {}
    for i, line in enumerate(src.splitlines(), 1):
        b = bad_chars(line)
        if b:
            hits[i] = b
    # PowerShell 은 $OutputEncoding / [Console]::OutputEncoding 으로 잡는다
    ok = ("OutputEncoding" in src) or ("chcp 65001" in src)
    return {
        "path": path.replace("\\", "/"),
        "kind": "ps1",
        "entry": True,
        "reconfigured": ok,
        "hits": {str(k): "".join(sorted(v)) for k, v in sorted(hits.items())},
        "n_bad": sum(len(v) for v in hits.values()),
        "parse_error": None,
    }


def walk():
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in sorted(filenames):
                p = os.path.join(dirpath, fn)
                if fn.endswith(".py"):
                    yield audit_py(p)
                elif fn.endswith(".ps1"):
                    yield audit_ps1(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = list(walk())
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0

    # ★ 치명(파이썬)과 미관(파워셸)을 가른다.
    #   실측(2026-09-01): PowerShell 은 cp949 콘솔에서 인코딩 불가 문자를 `?` 로 **대체**하고
    #   종료코드 0 으로 살아남는다. 파이썬만 UnicodeEncodeError 로 **즉사**한다.
    danger = [r for r in rows
              if r["kind"] == "py" and r["entry"] and r["n_bad"] and not r["reconfigured"]]
    cosmetic = [r for r in rows
                if r["kind"] == "ps1" and r["n_bad"] and not r["reconfigured"]]
    latent = [r for r in rows
              if r["kind"] == "py" and r["entry"] and not r["reconfigured"] and not r["n_bad"]]
    safe_ok = [r for r in rows if r["reconfigured"]]

    print("감사 대상 %d개 (py %d · ps1 %d)"
          % (len(rows), sum(1 for r in rows if r["kind"] == "py"),
             sum(1 for r in rows if r["kind"] == "ps1")))
    print()
    print("★★ 치명 — 파이썬 진입점 · cp949 불가 문자 · UTF-8 강제 없음 → **즉사**: %d개" % len(danger))
    for r in danger:
        print("   %-42s 문자 %s" % (r["path"], "".join(sorted(set("".join(r["hits"].values()))))))
        for ln, ch in list(r["hits"].items())[:3]:
            print("        %s행: %s" % (ln, ch))
    print()
    print("★ 잠재 — 진입점인데 UTF-8 강제 없음(지금은 문자가 없어 안 죽는다): %d개" % len(latent))
    for r in latent:
        print("   %s" % r["path"])
    print()
    print("· 미관(파워셸) — `?` 로 대체될 뿐 죽지 않는다: %d개" % len(cosmetic))
    for r in cosmetic:
        print("   %s" % r["path"])
    print()
    print("정상 — UTF-8 강제 있음: %d개" % len(safe_ok))
    bad_parse = [r for r in rows if r["parse_error"]]
    if bad_parse:
        print()
        print("파싱 실패 %d개:" % len(bad_parse))
        for r in bad_parse:
            print("   %s — %s" % (r["path"], r["parse_error"]))
    return 1 if danger else 0


if __name__ == "__main__":
    sys.exit(main())
