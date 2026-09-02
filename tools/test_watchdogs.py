"""test_watchdogs.py — 게이트웨이 안전장치 4종을 **합성 스트림으로** 실제로 발동시킨다.

왜 (2026-09-01)
---------------
이 4종은 전부 「리허설 1회차를 날린 침묵」에 대한 대책으로 어젯밤 급히 넣은 것이고,
**한 번도 발동시켜 본 적이 없다.** 안 울리는 경보는 없는 것과 같다.
실제 고장을 다시 일으킬 수는 없으므로(하드웨어를 건드리면 안 된다) 합성으로 민다.

  1) 줄 조립기   — 한 줄이 여러 번의 read 로 쪼개져 와도 잃지 않는가
  2) 침묵 감시견 — 데이터가 끊기면 20초 뒤 경고가 나오는가
  3) 폭주 감시견 — 쓰레기가 쏟아지면(정상의 3배 초과) 경고가 나오는가
  4) 중단 산출물 — 스트림 도중 KeyboardInterrupt 가 나도 산출물이 남는가

    python tools/test_watchdogs.py
"""
from __future__ import annotations

import io
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gateway"))
sys.path.insert(0, ROOT)

import importlib.util                                    # noqa: E402

import serial_source                                     # noqa: E402


def load_gateway():
    """`import gateway` 는 저장소의 **gateway/ 디렉터리**(네임스페이스 패키지)를 잡는다.
    파일을 직접 지정해 gateway/gateway.py 를 불러온다."""
    if "gw_mod" in sys.modules:
        return sys.modules["gw_mod"]
    spec = importlib.util.spec_from_file_location(
        "gw_mod", os.path.join(ROOT, "gateway", "gateway.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["gw_mod"] = m
    spec.loader.exec_module(m)
    return m

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print("  %-4s %-34s %s" % ("PASS" if ok else "FAIL", name, detail))


class Drained(Exception):
    """가짜 포트의 조각이 다 떨어졌다. StopIteration 을 쓰면 PEP 479 로 제너레이터
    안에서 RuntimeError 가 되므로 전용 예외를 쓴다."""


class FakeSerial:
    """read() 가 돌려줄 조각을 미리 정해 둔 가짜 포트. b"" 는 타임아웃(침묵)이다.

    ★ delay 가 필요한 이유: 감시견 두 종은 **벽시계**로 판정한다(침묵 20초, 폭주 10초 창).
      조각을 즉시 돌려주면 런 전체가 0초 만에 끝나 **경보가 영원히 안 울린다.**
      처음 이 지연 없이 시험했을 때 두 종 다 「경고 없음」이 나왔는데, 그건 코드가 아니라
      시험이 틀린 것이었다. 실제 포트의 timeout 처럼 시간을 흐르게 한다.
    """

    def __init__(self, chunks, delay=0.0):
        self.chunks = list(chunks)
        self.delay = delay
        self.in_waiting = 0

    def read(self, n):
        if not self.chunks:
            raise Drained
        if self.delay:
            time.sleep(self.delay)
        return self.chunks.pop(0)


# ── 1) 줄 조립기 ────────────────────────────────────────────────────────
def t_assembler():
    whole = b'{"type":"HB","id":3,"temp":25.5}'
    # 한 줄을 5조각으로 쪼개고, 그 사이에 타임아웃(b"")을 끼워 넣는다.
    chunks = [whole[:6], b"", whole[6:14], whole[14:22], b"", whole[22:] + b"\n"]
    got, nones = [], 0
    try:
        for x in serial_source._assemble(FakeSerial(chunks)):
            if x is None:
                nones += 1
            else:
                got.append(x)
    except Drained:
        pass
    ok = got == [whole.decode()] and nones == 2
    check("줄 조립기", ok, "조각 6개 → 완전한 줄 %d개 · 침묵신호 %d회" % (len(got), nones))


# ── 2)3) 침묵·폭주 감시견 ──────────────────────────────────────────────
def run_gateway(chunks, delay, label, fw=True):
    """가짜 포트를 물린 게이트웨이를 **같은 프로세스에서** 돌리고 stderr 를 가로챈다."""
    G = load_gateway()

    def fake_iter(spec, seed=42, baud=115200, port_reset=True):
        yield from serial_source._assemble(FakeSerial(chunks, delay))

    old_iter = G.iter_lines
    old_err = sys.stderr
    buf = io.StringIO()
    G.iter_lines = fake_iter
    sys.stderr = buf
    argv = sys.argv[:]
    sys.argv = ["gateway.py", "--port", "COMFAKE"] + (["--fw"] if fw else []) + [
                "--out-deaths", os.path.join(OUT, "%s_deaths.csv" % label),
                "--out-js", os.path.join(OUT, "%s.js" % label),
                "--out-json", os.path.join(OUT, "%s.json" % label)]
    try:
        G.main()
    except (Drained, SystemExit, RuntimeError):
        pass
    except Exception as e:
        buf.write("\n[테스트] 예외: %r\n" % e)
    finally:
        G.iter_lines = old_iter
        sys.stderr = old_err
        sys.argv = argv
    return buf.getvalue()


def t_silence():
    # 유효 프레임 하나를 준 뒤 계속 침묵(b"") → silence_warn_s 뒤 경고가 나와야 한다.
    #
    # ★★ [2026-09-01 파이에서 발견] 여기 하드코딩 30초가 gateway.py 의
    #   silence_warn_s 40초(결정 (가′) 로 20→40 변경)보다 짧아서, 통과했던 결과가
    #   사실 **그때(20초 기준) 우연히 맞은 것**이었다. 40초로 오른 뒤 재실행 안 하고
    #   방치해 파이에 최신 코드를 올렸을 때 FAIL 로 처음 드러났다.
    #   같은 값을 두 곳에 하드코딩하면 한쪽만 바뀌었을 때 못 잡는다는 것을 오늘 밤
    #   여러 번 겪었는데(HB 5초 착각, 절차서 옛 값 등) 여기 내 도구에도 있었다.
    #   gateway.py 에서 값을 읽어 오면 이런 어긋남이 구조적으로 불가능해진다.
    # silence_warn_s 는 main() 안의 지역 변수라 함수 밖에서 못 읽는다 — 소스를 직접 판다.
    # (지역 변수인 이유는 gateway.py 참조. 값 자체를 옮기는 대신 파싱하는 이유는,
    #  이 시험이 gateway.py 의 실제 문턱을 **뒤따라야** 다시 어긋나지 않기 때문이다.)
    import re
    src = open(os.path.join(ROOT, "gateway", "gateway.py"), encoding="utf-8").read()
    m2 = re.search(r"HEARTBEAT_S_EXPECTED\s*=\s*([\d.]+)", src)
    silence_warn_s = 4 * float(m2.group(1)) if m2 else 20.0
    hb = b'{"type":"HB","id":0,"x":0,"y":0,"temp":25,"t":1,"ms":1000,"st":"ALIVE","fake":0,"nt":1.0}\n'
    # 문턱보다 넉넉히(+50%, 최소 +10초) 침묵을 준다. 문턱에 딱 맞추면 타이밍 오차로
    # 또 거짓 실패가 난다 — 라즈베리파이는 노트북보다 프로세스 기동이 느리다.
    need_s = max(silence_warn_s * 1.5, silence_warn_s + 10)
    n_chunks = int(need_s / 0.1)
    chunks = [hb] + [b""] * n_chunks
    # ★ --fw 유무로 갈라 본다. 어댑터가 침묵 신호(None)를 삼키는지 여부를 분리하기 위한 것이다.
    for fw in (False, True):
        t0 = time.time()
        err = run_gateway(list(chunks), 0.1, "silence_fw%d" % fw, fw=fw)
        ok = "프레임이 없다" in err
        check("침묵 감시견 (--fw %s)" % ("있음" if fw else "없음"), ok,
              "%.0f초 경과 · 경고 %s" % (time.time() - t0, "발생" if ok else "없음"))


def t_flood():
    # 실제로 관측된 재생 고장과 같은 모양: 직전 줄의 꼬리가 무한 반복된다.
    junk = b't":752.627153}\n' * 200
    hb = b'{"type":"HB","id":0,"x":0,"y":0,"temp":25,"t":1,"ms":1000,"st":"ALIVE","fake":0,"nt":1.0}\n'
    # 0.5초마다 쓰레기 200줄 = 10초 창에 4000줄. 30회 = 15초 → 창이 두 번 닫힌다.
    chunks = [hb] + [junk] * 30
    for fw in (False, True):
        err = run_gateway(list(chunks), 0.5, "flood_fw%d" % fw, fw=fw)
        ok = "시리얼이 물렸다" in err
        check("폭주 감시견 (--fw %s)" % ("있음" if fw else "없음"), ok,
              "경고 %s" % ("발생" if ok else "없음"))


# ── 4) 중단 산출물 ─────────────────────────────────────────────────────
def t_interrupt():
    hb = (b'{"type":"HB","id":%d,"x":0,"y":0,"temp":25,"t":1,"ms":1000,'
          b'"st":"ALIVE","fake":0,"nt":1.0}\n')

    class Boom(FakeSerial):
        def __init__(self):
            super().__init__([hb % i for i in range(16)] * 3)
            self.n = 0

        def read(self, n):
            self.n += 1
            if self.n > 40:
                raise KeyboardInterrupt        # 사람이 Ctrl-C 를 누른 것과 같은 지점
            return super().read(n)

    G = load_gateway()

    def fake_iter(spec, seed=42, baud=115200, port_reset=True):
        yield from serial_source._assemble(Boom())

    js = os.path.join(OUT, "interrupt.js")
    for p in (js, os.path.join(OUT, "interrupt.json")):
        if os.path.exists(p):
            os.remove(p)
    old_iter, old_err = G.iter_lines, sys.stderr
    buf = io.StringIO()
    G.iter_lines = fake_iter
    sys.stderr = buf
    argv = sys.argv[:]
    sys.argv = ["gateway.py", "--port", "COMFAKE", "--fw", "--emit-dashboard",
                "--out-deaths", os.path.join(OUT, "interrupt_deaths.csv"),
                "--out-js", js, "--out-json", os.path.join(OUT, "interrupt.json")]
    try:
        G.main()
    except (Drained, SystemExit):
        pass
    except Exception as e:
        buf.write("\n[테스트] 예외: %r\n" % e)
    finally:
        G.iter_lines, sys.stderr, sys.argv = old_iter, old_err, argv
    err = buf.getvalue()
    saw = "중단(Ctrl-C)" in err
    wrote = os.path.exists(js) and os.path.getsize(js) > 0
    check("중단 산출물", saw and wrote,
          "중단 메시지 %s · data.js %s" % ("있음" if saw else "없음",
                                           "생성됨" if wrote else "★없음"))


OUT = os.path.join(ROOT, "results", "watchdog_test")

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    os.chdir(ROOT)
    print("게이트웨이 안전장치 4종 — 합성 스트림 시험")
    print()
    t_assembler()
    t_silence()
    t_flood()
    t_interrupt()
    print()
    nf = sum(1 for _, ok, _ in results if not ok)
    print("★ 감시견 시험 %s" % ("통과 — 4종 전부 발동" if nf == 0 else "실패 %d종" % nf))
    sys.exit(1 if nf else 0)
