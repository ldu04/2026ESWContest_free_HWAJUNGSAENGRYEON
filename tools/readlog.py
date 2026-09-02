"""readlog.py — cp949 로 쓰인 PowerShell 로그를 UTF-8 로 읽어 준다.

굽기 루프는 -NoProfile 로 띄우므로 UTF-8 프로필이 안 걸리고, 출력이 cp949 로 떨어진다.
로그를 고치는 대신 읽을 때 되돌린다(원본은 그대로 둔다).
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
path = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
data = open(path, "rb").read()
for enc in ("cp949", "utf-8"):
    try:
        text = data.decode(enc)
        break
    except UnicodeDecodeError:
        continue
else:
    text = data.decode("cp949", "replace")
lines = text.splitlines()
for l in lines[-n:]:
    print(l)
