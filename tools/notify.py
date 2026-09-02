"""notify.py — **사람이 할 일이 생겼을 때** 소리로 부른다.

왜: 사용자는 화면을 계속 보고 있지 않다. 굽기 대기·열풍기 준비처럼
    사람이 움직여야 진행되는 지점에서 조용히 기다리면 시간이 그냥 흐른다.

왜 voice.py 를 쓰지 않나 (2026-09-01)
-------------------------------------
`voice.py` 는 **런 중**에 쓰는 물건이다 — 합성기를 하나 띄워 두고 우선순위로 밀어 넣는다
(카운트다운이 「떼세요」에 끊기지 않게 하려고). 알림은 성격이 다르다:

  · 알림은 **드물고, 끝까지 들려야** 한다. 중간에 잘리면 무슨 말인지 모른다.
  · notify.py 를 두 번 부르면 그 방식으로는 **합성기가 두 개 떠서 겹쳐 말한다.**
    실제로 「겹치는 건지 뭐라는지 안 들린다」는 지적을 받았다.

그래서 여기서는 **동기 `Speak()`** 를 쓴다. 다 말할 때까지 프로세스가 안 끝나므로
겹칠 수가 없고 잘릴 수도 없다. 속도도 기본 0(보통)이다.

    python tools/notify.py "굽기 준비됐습니다. 보드를 꽂으세요"
    python tools/notify.py --beep "n04 차례입니다. 확인이 필요합니다"
    python tools/notify.py --rate -2 "더 천천히"
"""
from __future__ import annotations

import argparse
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# ★★ [2026-09-01] 문장을 **base64 로** 넘긴다. stdin 이나 명령줄로 한글을 그대로 주면
#   PowerShell 이 자기 InputEncoding(기본 cp949)으로 읽어 **글자가 깨진 채 합성기에 들어간다.**
#   그러면 한국어 음성(Heami)이 깨진 글자를 읽어 「한국어가 맞나?」 싶은 소리가 난다.
#   실제로 그 지적을 받았다. base64 는 순수 ASCII 라 경계에서 깨질 수가 없다.
#
#   동기 Speak() 를 쓴다 — 다 말할 때까지 돌아오지 않으므로 겹치거나 잘리지 않는다.
PS_TEMPLATE = (
    "Add-Type -AssemblyName System.Speech;"
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$s.Rate={rate};"
    "$s.Volume=100;"
    # 한국어 음성이 있으면 명시적으로 고른다. 영어 음성이 한글을 읽으면 알아들을 수 없다.
    "$ko=$s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'ko*' }} | Select-Object -First 1;"
    "if($ko){{ $s.SelectVoice($ko.VoiceInfo.Name) }};"
    "{beep}"
    "$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}'));"
    "foreach($line in ($t -split \"`n\")){{"
    "  if($line.Trim()){{ $s.Speak($line.Trim()); Start-Sleep -Milliseconds 250 }}"
    "}}"
)


def say(msg: str, rate: int = 0, beep: bool = False, repeat: int = 1) -> int:
    import base64
    text = "\n".join([msg] * max(1, repeat))
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    cmd = PS_TEMPLATE.format(rate=rate, b64=b64,
                             beep="[Console]::Beep(880,220);" if beep else "")
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180)
        if p.returncode != 0:
            print("  [경고] 음성 실패: %s"
                  % p.stderr.decode("utf-8", "replace").strip()[:200])
        return p.returncode
    except Exception as e:
        print("  [경고] 음성 준비 실패: %s" % e)
        return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("message", nargs="+")
    ap.add_argument("--rate", type=int, default=0, help="-10(느림) ~ 10(빠름). 기본 0")
    ap.add_argument("--beep", action="store_true", help="말하기 전에 삐 소리")
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()
    msg = " ".join(args.message)
    print("  [알림] %s" % msg)
    return say(msg, rate=args.rate, beep=args.beep, repeat=args.repeat)


if __name__ == "__main__":
    sys.exit(main())
