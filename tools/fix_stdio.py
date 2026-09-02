"""fix_stdio.py — 진입점 스크립트의 표준출력/표준오류를 **UTF-8 · 줄버퍼 · 무손실 대체**로 고정한다.

왜 (2026-09-01)
---------------
1) **죽지 않게**: cp949 콘솔에서 `—` 하나로 `UnicodeEncodeError` 가 나 도구가 즉사했다
   (`rollcall.py`). 런 중에 죽으면 「떼세요」가 안 울린다. `errors="replace"` 까지 걸어
   **어떤 문자가 와도 죽지 않게** 한다. 인코딩만 바꾸면 새 이모지 하나에 또 죽는다.
2) **남게**: 리다이렉트하면 stdout 이 블록 버퍼라 튕길 때 마지막 수 KB 가 통째로 사라진다.
   `line_buffering=True` 로 **줄마다 flush** 한다.
3) **표준오류도**: 트레이스백은 stderr 로 나간다. 여기가 cp949 면 죽은 이유조차 못 남긴다.

원본 줄바꿈(CRLF/LF)은 그대로 둔다. 되돌리려면 git 또는 백업본을 쓴다.

    python tools/fix_stdio.py <파일...>            # 무엇을 고칠지만 본다(쓰지 않는다)
    python tools/fix_stdio.py <파일...> --apply
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BLOCK = (
    '# ★ 표준출력/표준오류 고정 '
    '— cp949 콘솔에서 문자 하나로 죽지 '
    '않게, 튕겨도 줄이 남게.\n'
    '#   근거: docs/n07_사망시험_판정_20260901.md §7\n'
    'sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)\n'
    'sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)\n'
)
MARK = 'sys.stderr.reconfigure(encoding="utf-8", errors="replace"'

# 기존 형태 두 가지를 모두 잡는다:
#   (a) 맨 앞 한 줄        sys.stdout.reconfigure(encoding="utf-8")
#   (b) try/except 로 감싼 형태 (gateway.py)
OLD_PLAIN = re.compile(r'^sys\.stdout\.reconfigure\([^\n]*\)\r?\n', re.M)
OLD_TRY = re.compile(
    r'^try:\r?\n[ \t]+sys\.stdout\.reconfigure\([^\n]*\)\r?\n'
    r'except Exception:\r?\n[ \t]+pass\r?\n', re.M)
# ★ 최상위(들여쓰기 없는) import 만 본다. 함수 안의 `    import serial` 을 삽입 지점으로
#   잡으면 블록이 함수 몸통 한가운데 들어가 IndentationError 가 난다.
#   2026-09-01 에 실제로 6개 파일을 그렇게 깨뜨렸다 — 백업에서 되돌리고 규칙을 좁혔다.
IMPORT_LINE = re.compile(r'^(import|from)\s')
IMPORT_SYS = re.compile(r'^import sys\b')
# 모듈 본문이 시작되면 멈춘다 — 뒤쪽에 최상위 import 가 또 있어도 따라가지 않는다
BODY_START = re.compile(r'^(def\s|class\s|@|if\s|try:|with\s|for\s|while\s)')


def _nl(src: str) -> str:
    """원본 줄바꿈을 유지한다 — CRLF 파일을 LF 로 바꾸면 전 줄이 diff 로 뜬다."""
    return "\r\n" if "\r\n" in src else "\n"


def fix(path: str, apply: bool):
    src = open(path, encoding="utf-8", newline="").read()
    if MARK in src:
        return "이미 됨", False
    nl = _nl(src)
    block = BLOCK.replace("\n", nl)

    # 1) 기존 reconfigure 가 있으면 그 자리를 통째로 바꾼다
    for rx, what in ((OLD_TRY, "교체(try)"), (OLD_PLAIN, "교체")):
        if rx.search(src):
            new = rx.sub(lambda m: block, src, count=1)
            if apply:
                open(path, "w", encoding="utf-8", newline="").write(new)
            return what, True

    # 2) 없으면 마지막 import 뒤에 넣는다(`import sys` 가 없으면 함께 넣는다)
    lines = src.split(nl)
    has_sys = any(IMPORT_SYS.match(l) for l in lines)
    ins = None
    for i, l in enumerate(lines):
        if IMPORT_LINE.match(l):
            ins = i + 1
        elif BODY_START.match(l):
            break
    if ins is None:
        return "삽입 지점 없음 — 건너뜀", False
    # ★ 괄호로 여러 줄에 걸친 import 는 닫는 괄호까지 끌고 간다. 중간에 끼워 넣으면
    #   문장이 두 동강 나 SyntaxError 가 된다(run_night_experiments.py 에서 실제로 났다).
    depth = lines[ins - 1].count("(") - lines[ins - 1].count(")")
    while depth > 0 and ins < len(lines):
        depth += lines[ins].count("(") - lines[ins].count(")")
        ins += 1
    body = block if has_sys else ("import sys" + nl + block)
    new = nl.join(lines[:ins]) + nl + nl + body + nl.join(lines[ins:])
    if apply:
        open(path, "w", encoding="utf-8", newline="").write(new)
    return ("삽입" + ("" if has_sys else " (+import sys)")), True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    n = 0
    for p in args.files:
        if not os.path.isfile(p):
            print("  없음   %s" % p)
            continue
        what, changed = fix(p, args.apply)
        n += changed
        print("  %-22s %s" % (what, p))
    print()
    print("%s %d개" % ("고침" if args.apply else "고칠 것", n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
