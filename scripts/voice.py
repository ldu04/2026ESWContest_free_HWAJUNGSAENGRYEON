"""voice.py — 손이 바쁠 때 유일하게 전달되는 채널. run_cue / temp_voice 가 함께 쓴다.

설계 이유 (2026-08-31 사고)
--------------------------
1) **매번 powershell.exe 를 새로 띄우면 안 된다.** 기동에만 1초 넘게 걸려서
   「떼세요」가 늦는다. 늦은 경고는 안전장치가 아니다. → 한 번만 띄우고 stdin 으로 민다.
2) **무조건 취소(최신만 말하기)도 안 된다.** 카운트다운이 서로를 끊어서 「삼… 일…」이
   토막나 들린다. → 우선순위를 둔다:
     - 보통(NORMAL): **큐에 세운다.** 앞 문장이 끝날 만큼 기다렸다가 민다.
     - 중요(CRITICAL): 말하는 중이어도 **끊고 들어간다**. 「떼세요」·「위험」이 여기다.
       이때 밀려 있던 보통 문장은 버린다 — 「떼세요」 뒤에 옛 카운트다운이 따라 나오면 안 된다.

3) **버리는 판단을 합성기 쪽에 두지 않는다** (2026-09-01 수정).
   처음에는 PowerShell 에서 「말하는 중이면 버린다」로 했는데, Rate 를 2에서 0으로
   낮추자 한 마디가 길어져 **카운트다운 「3 2 1」에서 2가 통째로 사라졌다**(사용자 확인).
   합성기가 버리면 무엇이 사라졌는지 아무도 모른다. 간격은 파이썬이 큐로 벌린다.
"""
from __future__ import annotations

import base64
import collections
import subprocess
import sys
import threading
import time

# ★ 표준출력/표준오류 고정 — cp949 콘솔에서 문자 하나로 죽지 않게, 튕겨도 줄이 남게.
#   근거: docs/n07_사망시험_판정_20260901.md §7
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

PS = (
    "Add-Type -AssemblyName System.Speech;"
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    # ★ [2026-09-01] Rate 2 -> 0. 사용자가 「너무 빨라 뭐라는지 안 들린다」고 했다.
    #   빠른 말은 반응 시간을 줄여 주는 대신 **전달이 안 되면 아무 값도 없다.**
    #   0 이 기본 속도다(-10~10). 「떼세요」 한 마디가 늦는 것보다 안 들리는 게 나쁘다.
    "$s.Rate=0;"
    "$s.Volume=100;"
    # ★ [2026-09-01] 한국어 음성을 명시적으로 고른다. 영어 음성이 한글을 읽으면
    #   무슨 말인지 알 수 없다. 없으면 기본값 그대로 둔다.
    "$ko=$s.GetInstalledVoices()|Where-Object{$_.VoiceInfo.Culture.Name -like 'ko*'}|Select-Object -First 1;"
    "if($ko){$s.SelectVoice($ko.VoiceInfo.Name)};"
    # ★★ [2026-09-01] 문장을 **base64 로** 받는다.
    #   한글을 그대로 stdin 에 넣으면 PowerShell 이 자기 InputEncoding(기본 cp949)으로
    #   읽어 **글자가 깨진 채 합성기에 들어간다.** 그러면 한국어 음성이 깨진 글자를 읽어
    #   「한국어가 맞나」 싶은 소리가 난다 — 사용자가 실제로 그렇게 지적했다.
    #   이건 런 중 「떼세요」가 나가는 바로 그 경로다. base64 는 ASCII 라 안 깨진다.
    #   앞의 '!'(CRITICAL 표시)는 ASCII 라 그대로 둔다.
    "while(($l=[Console]::In.ReadLine()) -ne $null){"
    "  $c=$l.StartsWith('!');"
    "  $b=if($c){$l.Substring(1)}else{$l};"
    "  $t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b));"
    "  if($c){"                          # CRITICAL — 끊고 말한다
    "    $s.SpeakAsyncCancelAll();[Console]::Beep(1200,150);"
    "    $s.SpeakAsync($t)|Out-Null }"
    # ★★ [2026-09-01] 예전에는 여기에 `elseif($s.State -eq 'Ready')` 가 있어서
    #   **말하는 중이면 버렸다.** Rate 를 2에서 0으로 낮추자 한 마디가 길어져
    #   카운트다운 「3 2 1」에서 **2가 통째로 사라졌다**(사용자 확인).
    #   버리는 판단을 여기서 하지 않는다 — **간격은 파이썬 쪽이 큐로 벌린다**(아래 Voice).
    #   여기서 버리면 무엇이 사라졌는지 아무도 모른다.
    "  else{ $s.SpeakAsync($t)|Out-Null }"
    "}"
)


def _speak_secs(msg: str) -> float:
    """이 문장을 말하는 데 걸릴 시간의 어림값(초).

    정확할 필요는 없다. **다음 문장을 언제 밀어 넣을지**만 정하면 된다.
    한국어 음성 Heami 기준으로 한 글자 약 0.16초 + 시작·끝 여유 0.35초로 잡았다.
    짧게 잡으면 겹치고, 길게 잡으면 큐가 밀린다. 겹치는 쪽이 더 나쁘므로 넉넉히 준다.
    """
    return 0.35 + 0.16 * len(msg)


class Voice:
    """말하기 채널.

    ★ [2026-09-01] 정책 변경 — **버리지 않고 줄 세운다.**
      예전에는 PowerShell 쪽에서 「말하는 중이면 버린다」로 처리했는데, Rate 를 0으로
      낮추자 한 마디가 길어져 카운트다운 「3 2 1」의 **2가 통째로 사라졌다**(사용자 확인).
      버리는 판단을 합성기 쪽에 두면 **무엇이 사라졌는지 아무도 모른다.**

      이제 파이썬이 큐를 들고 있고, 앞 문장이 끝날 만큼 기다렸다가 다음을 민다.
      CRITICAL(「떼세요」·「위험」)은 **큐를 건너뛰고 즉시** 나가며, 밀려 있던 보통 문장은
      버린다 — 「떼세요」가 나온 뒤에 옛 카운트다운이 따라 나오면 안 되기 때문이다.
    """

    MAX_PENDING = 3          # 이보다 쌓이면 가장 오래된 것을 버린다(밀린 큐는 이미 늦은 정보다)

    def __init__(self, quiet=False, echo=True):
        self.quiet = quiet
        self.echo = echo
        self.p = None
        self._q = collections.deque()
        self._lock = threading.Lock()
        self._alive = True
        if quiet:
            return
        try:
            self.p = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PS],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        except Exception as e:
            print("  [경고] 음성 준비 실패: %s" % e)

        # 큐 펌프. 데몬이라 프로그램이 끝나면 같이 죽는다.
        threading.Thread(target=self._pump, daemon=True).start()

    def _write(self, msg, critical):
        try:
            # ★ base64 로 보낸다 — 위 PS 주석 참조. 한글을 그대로 넘기면 깨진다.
            b64 = base64.b64encode(msg.replace("\n", " ").encode("utf-8")).decode("ascii")
            self.p.stdin.write(("!" if critical else "") + b64 + "\n")
            self.p.stdin.flush()
        except Exception:
            pass

    def _pump(self):
        """보통 문장을 앞 문장이 끝날 만큼 기다렸다가 하나씩 민다."""
        while self._alive:
            msg = None
            with self._lock:
                if self._q:
                    msg = self._q.popleft()
            if msg is None:
                time.sleep(0.05)
                continue
            self._write(msg, False)
            time.sleep(_speak_secs(msg))

    def say(self, msg, critical=False):
        if self.echo:
            print("      %s %s" % ("!!" if critical else "*", msg))
            sys.stdout.flush()
        if self.p is None or self.p.poll() is not None:
            return
        if critical:
            # 큐를 비운다 — 「떼세요」 뒤에 옛 카운트다운이 따라 나오면 안 된다.
            with self._lock:
                self._q.clear()
            self._write(msg, True)
            return
        with self._lock:
            self._q.append(msg)
            while len(self._q) > self.MAX_PENDING:
                self._q.popleft()          # 밀린 것은 이미 늦은 정보다

    def close(self):
        self._alive = False
        try:
            if self.p:
                self.p.stdin.close()
        except Exception:
            pass
