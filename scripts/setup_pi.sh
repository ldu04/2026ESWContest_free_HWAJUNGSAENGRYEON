#!/usr/bin/env bash
#
# setup_pi.sh — 라즈베리파이 게이트웨이 1줄 준비 스크립트
#
# 쓰는 법 (파이에 SSH 로 들어간 뒤, 저장소가 이미 파이에 있는 상태에서):
#
#     bash ~/failsafe-mesh/scripts/setup_pi.sh
#
# 저장소를 파이로 옮기는 방법은 docs/파이_준비_절차.md §2 를 볼 것.
# 이 스크립트는 **코드를 가져오지 않는다** — 자기 자신이 저장소 안에 있어야 실행되기 때문이다.
#
# ─────────────────────────────────────────────────────────────────────────────
# ★ 설계 결정 1 — PEP 668: venv 를 쓴다. `--break-system-packages` 는 쓰지 않는다.
#
#   Bookworm 부터 시스템 파이썬은 externally-managed 로 표시돼 전역 pip 설치를 막는다.
#   탈출구가 둘 있는데 **venv 를 고른다.**
#
#   왜 --break-system-packages 가 아닌가:
#     · Raspberry Pi OS 의 apt numpy(1.24 대)는 다른 시스템 패키지들의 의존성이다.
#       거기에 pip 으로 numpy 2.4.4 를 덮어쓰면 dist-packages 안에서 버전이 뒤섞인다.
#       그리고 그 고장은 조용하다 — 무엇이 언제 깨졌는지 알 방법이 없고, 촬영 전날 밤에
#       되돌리려면 OS 를 다시 굽는 것 말고 확실한 수단이 없다.
#     · venv 는 되돌리기가 `rm -rf <저장소>/.venv` 한 줄이고 시스템은 한 글자도 안 건드린다.
#     · 이 프로젝트는 numpy 를 버전 고정해서 쓴다(수치 재현성). 시스템 numpy 와 섞이면
#       어느 쪽이 로드됐는지 모르게 된다. venv 는 그 질문 자체를 없앤다.
#
#   대가: 실행할 때 `python` 이 아니라 `.venv/bin/python` 을 써야 한다.
#         이 스크립트가 마지막에 그 절대경로를 박아서 그대로 붙여넣을 명령을 찍어준다.
#
# ★ 설계 결정 2 — 멱등. 몇 번을 돌려도 안전하다.
#   설치된 것은 건너뛰고, 이미 dialout 이면 usermod 를 안 부르고, .venv 가 있으면 다시 안 만든다.
#   파괴적 동작(rm, 덮어쓰기)은 하나도 없다.
#   ※ 유일하게 시스템 상태를 바꾸는 곳은 ModemManager 비활성화(§6)인데, 되돌리는 명령을 찍는다.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLD=$'\033[1m'; RST=$'\033[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s[OK]%s   %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%s[경고]%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '%s[실패]%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }
step() { printf '\n%s── %s%s\n' "$BLD" "$*" "$RST"; }

trap 'die "중단됐다 (line $LINENO). 바로 위 명령이 실패했다. 고치고 다시 돌리면 된다 — 멱등이다."' ERR

NEED_RELOGIN=0
WARNINGS=0
note_warn() { warn "$*"; WARNINGS=$((WARNINGS+1)); }

# ── 0. 저장소 위치 확인 ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
cd "$REPO"

[ -f gateway/requirements.txt ] || die "여기가 저장소 루트가 아니다: $REPO (gateway/requirements.txt 가 없다)"
[ -f gateway/gateway.py ]       || die "gateway/gateway.py 가 없다. 전송이 덜 됐다 — docs/파이_준비_절차.md §2 를 다시 볼 것"
[ -f sim/estimator.py ]         || die "sim/ 이 없다. 게이트웨이는 sim/estimator.py 를 재사용하므로 sim/ 없이는 못 돈다"

say "${BLD}=== 불사 게이트웨이 · 라즈베리파이 준비 ===${RST}"
say "저장소 : $REPO"
say "사용자 : $(id -un)   호스트: $(hostname)"

# ── 1. 이 기계가 맞는지 ──────────────────────────────────────────────────────
step "1. 환경 확인"

[ "$(uname -s)" = "Linux" ] || die "리눅스가 아니다($(uname -s)). 이 스크립트는 라즈베리파이용이다."
[ "$(id -u)" -ne 0 ] || die "root 로 돌리지 마라. 일반 사용자로 실행해야 dialout 그룹이 그 사용자에게 붙는다. (sudo 가 필요한 곳은 스크립트가 알아서 부른다)"
command -v sudo >/dev/null || die "sudo 가 없다."

ARCH="$(uname -m)"
say "아키텍처 : $ARCH"
if [ -r /etc/os-release ]; then . /etc/os-release; say "OS       : ${PRETTY_NAME:-불명}"; fi
say "python3  : $(python3 -V 2>&1)"

# ★ 32비트(armv7l/armhf)면 numpy 2.4.4 의 미리 빌드된 휠이 없다 → pip 이 소스 빌드로 넘어가고
#   파이에서 수십 분 걸리다 대개 실패한다. 조용히 기다리게 두지 않고 여기서 미리 말한다.
if [ "$ARCH" != "aarch64" ]; then
  note_warn "아키텍처가 aarch64 가 아니다($ARCH). numpy==2.4.4 는 64비트 휠만 있어서 pip 이 소스 컴파일로 넘어간다(수십 분, 대개 실패). 64비트 Raspberry Pi OS 로 다시 굽거나, docs/파이_준비_절차.md §6 의 노트북 폴백으로 간다."
fi

# ── 2. apt 패키지 ────────────────────────────────────────────────────────────
step "2. apt 패키지 (필요한 것만)"

# python3      : Pi OS 기본 탑재 (여기서 설치하지 않는다)
# python3-venv : venv 를 만들려면 필요하다. Lite 이미지에는 없는 경우가 있다.
# python3-pip  : venv 안의 pip 부트스트랩 보조
# git          : 파이에서 코드 상태 확인·되돌리기용. 전송에는 안 쓴다(원격 저장소가 없다).
PKGS=(python3-venv python3-pip git)
MISSING=()
for p in "${PKGS[@]}"; do
  dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "ok installed" || MISSING+=("$p")
done

if [ ${#MISSING[@]} -eq 0 ]; then
  ok "이미 다 깔려 있다: ${PKGS[*]}  (apt update 건너뜀)"
else
  say "설치할 것: ${MISSING[*]}"
  sudo apt-get update
  sudo apt-get install -y "${MISSING[@]}"
  ok "설치 완료: ${MISSING[*]}"
fi

# ── 3. venv ──────────────────────────────────────────────────────────────────
step "3. venv (PEP 668 회피 — 위 '설계 결정 1' 참조)"

VENV="$REPO/.venv"           # .gitignore 에 이미 .venv/ 가 있다 — 저장소를 더럽히지 않는다
PY="$VENV/bin/python"

if [ -x "$PY" ]; then
  ok "venv 가 이미 있다: $VENV  ($("$PY" -V 2>&1))"
else
  python3 -m venv "$VENV"
  ok "venv 생성: $VENV"
fi

# ── 4. 파이썬 의존성 ─────────────────────────────────────────────────────────
step "4. gateway/requirements.txt 설치"

say "요구 사항:"
grep -vE '^\s*(#|$)' gateway/requirements.txt | sed 's/^/    /'

# pip 자체를 먼저 올린다. 번들 pip 이 오래되면 최신 휠 태그를 못 알아볼 때가 있다.
"$PY" -m pip install --quiet --upgrade pip
# --no-input : 파이에서 대화형 프롬프트로 멈추지 않게. 이미 만족된 핀은 pip 이 건너뛴다(멱등).
"$PY" -m pip install --no-input -r gateway/requirements.txt

# 깔렸다고 믿지 말고 import 해서 확인한다. 휠은 있는데 못 불러오는 경우가 실제로 있다.
"$PY" -c '
import sys
bad = []
try:
    import numpy;  print("    numpy    " + numpy.__version__)
except Exception as e: bad.append("numpy: %s" % e)
try:
    import serial; print("    pyserial " + serial.__version__)
except Exception as e: bad.append("pyserial: %s" % e)
if bad:
    sys.stderr.write("!! import 실패: " + "; ".join(bad) + "\n"); sys.exit(1)
'
ok "numpy · pyserial import 확인"

# ── 5. 시리얼 포트 권한 (dialout) ────────────────────────────────────────────
step "5. 시리얼 포트 권한 — dialout 그룹"

# 이걸 안 하면 /dev/ttyUSB0 를 열 때 Permission denied 가 난다.
# ★ 그룹 변경은 지금 이 SSH 세션에는 적용되지 않는다. 새 로그인부터 적용된다.
if id -nG "$(id -un)" | tr ' ' '\n' | grep -qx dialout; then
  ok "$(id -un) 은 이미 dialout 그룹이다"
else
  sudo usermod -aG dialout "$(id -un)"
  NEED_RELOGIN=1
  ok "dialout 그룹에 추가했다 — ${BLD}로그아웃 후 다시 SSH 접속해야 적용된다${RST}"
fi

# ── 6. ModemManager — 시리얼을 조용히 오염시키는 범인 ────────────────────────
step "6. ModemManager 확인"

# 왜 보는가: ModemManager 는 새로 뜬 /dev/ttyUSB* 를 모뎀으로 의심하고 AT 명령을 밀어 넣는다.
#   ESP32 브리지에 그게 들어가면 우리가 읽어야 할 JSON 라인 사이에 쓰레기가 섞이거나
#   포트를 몇 초간 붙잡는다. 증상은 "가끔 프레임이 빈다" 뿐이라 현장에서 절대 못 잡는다.
if systemctl list-unit-files 2>/dev/null | grep -q '^ModemManager\.service'; then
  if systemctl is-enabled --quiet ModemManager 2>/dev/null || systemctl is-active --quiet ModemManager 2>/dev/null; then
    sudo systemctl disable --now ModemManager
    ok "ModemManager 를 껐다."
    say "    되돌리기: ${BLD}sudo systemctl enable --now ModemManager${RST}"
  else
    ok "ModemManager 가 설치돼 있지만 이미 꺼져 있다"
  fi
else
  ok "ModemManager 없음 (Lite 이미지 — 문제 없다)"
fi

# ── 7. 브리지 ESP32 가 보이는가 ──────────────────────────────────────────────
step "7. 브리지 ESP32 인식 확인"

# 파이에서 CP210x(Silicon Labs, 10c4:ea60)는 커널 내장 드라이버로 /dev/ttyUSB* 에 잡힌다.
# CH340(1a86:7523)도 같은 자리에 뜬다. 어느 쪽이든 이름은 /dev/ttyUSB* 다.
# ※ Windows 의 COMx 와 달리 파이에서는 이 이름을 쓴다. --port auto 를 쓰면 이름을 몰라도 된다.
TTYS=$(ls -1 /dev/ttyUSB* 2>/dev/null || true)
if [ -n "$TTYS" ]; then
  ok "USB 시리얼 포트를 찾았다:"
  for t in $TTYS; do say "    $t   ($(stat -c '%U:%G %a' "$t"))"; done
else
  note_warn "/dev/ttyUSB* 가 없다. 브리지를 아직 안 꽂았으면 정상이다. 꽂았는데도 안 보이면: lsusb 로 장치가 뜨는지 → dmesg | tail -30 으로 드라이버가 붙었는지 확인. (충전 전용 USB 케이블이면 전원만 들어오고 데이터선이 없어서 아무것도 안 뜬다)"
fi

if command -v lsusb >/dev/null; then
  USBHIT=$(lsusb | grep -iE '10c4:ea60|1a86:7523|0403:6001' || true)
  if [ -n "$USBHIT" ]; then say "  lsusb:"; printf '    %s\n' "$USBHIT"; fi
fi

# ★ 여기서 브리지를 자동 탐색하지 않는다.
#   find_bridge_port() 는 포트를 열면서 RTS 로 보드를 리셋한다. 준비 단계에서 보드를 건드리면
#   촬영 직전 메시가 재수렴하는 시간을 낭비한다. 탐색은 런 직전 한 번만 한다.
say "  ※ 브리지 자동 탐색(--port auto)은 보드를 리셋하므로 여기서 돌리지 않는다. 런 직전에 한 번만."

# ── 8. 스모크 테스트 — 보드 없이 파이프라인 전체를 태운다 ────────────────────
step "8. 스모크 테스트 (합성 스트림 · 보드 불필요)"

# 왜 하는가: numpy 가 깔린 것과 estimator 가 파이에서 도는 것은 다른 문제다.
#   여기서 실패하면 촬영 전날 밤에 알 수 있고, 통과하면 남은 변수가 '보드' 하나로 줄어든다.
SMOKE_DIR="${TMPDIR:-/tmp}/bulsa_pi_smoke"   # ★ 저장소 밖. 합성 산출물이 results/ 의 실측 산출물과 절대 섞이지 않게
mkdir -p "$SMOKE_DIR"
SMOKE_LOG="$SMOKE_DIR/smoke.log"

"$PY" gateway/mock_fw_serial.py --fake 1 --out "$SMOKE_DIR/mock_fw_stream.jsonl" >/dev/null
"$PY" gateway/gateway.py \
      --in "$SMOKE_DIR/mock_fw_stream.jsonl" --fw \
      --emit-dashboard \
      --out-js     "$SMOKE_DIR/gateway_data.js" \
      --out-json   "$SMOKE_DIR/gateway_snapshots.json" \
      --out-deaths "$SMOKE_DIR/gateway_deaths.csv" 2>&1 | tee "$SMOKE_LOG"

# 통과 판정 — '조용히 프레임 0개' 가 이 프로젝트의 대표적 침묵실패다. 숫자로 못 박는다.
FRAMES=$(sed -n 's/.*재구성 프레임 \([0-9][0-9]*\).*/\1/p' "$SMOKE_LOG" | tail -1)
if [ -z "${FRAMES:-}" ] || [ "$FRAMES" -le 0 ]; then
  die "스모크 테스트 실패 — 재구성 프레임이 0개다. 로그: $SMOKE_LOG"
fi
grep -q '배치검산 ③' "$SMOKE_LOG" || die "스모크 테스트 실패 — 배치검산 3줄이 안 나왔다. 로그: $SMOKE_LOG"
ok "파이프라인 정상 — 재구성 프레임 ${FRAMES}개"
say "  ※ 이 산출물은 ${BLD}fake=1 합성 데이터${RST}다. $SMOKE_DIR 에만 있고 실측 경로와 섞이지 않는다."

# ── 9. 마무리 ────────────────────────────────────────────────────────────────
step "준비 완료"

if [ "$NEED_RELOGIN" -eq 1 ]; then
  say ""
  printf '%s★ 먼저 로그아웃하고 다시 접속해야 한다 (dialout 그룹 적용).%s\n' "$RED$BLD" "$RST"
  say "     exit  후  ssh $(id -un)@$(hostname).local"
  say "  확인:  id -nG | tr ' ' '\\n' | grep -x dialout"
fi

if [ "$WARNINGS" -gt 0 ]; then
  say ""
  warn "경고 ${WARNINGS}건이 위에 있다. 넘어가기 전에 읽을 것."
fi

say ""
say "${BLD}실보드 런 (촬영 당일)${RST} — 저장소 루트에서:"
say ""
say "    cd $REPO"
say "    $PY gateway/gateway.py --fw --port auto --emit-dashboard \\"
say "        --out-deaths results/hw/d1_deaths.csv"
say ""
say "  ★ --fw 는 필수다. 빼면 펌웨어 방언을 못 읽어 ${BLD}프레임 0개${RST}로 조용히 끝난다."
say "  ★ 시작 로그 통과 기준은 docs/파이_준비_절차.md §4:"
say "      · 규모 상수 유도 4줄 (dt_window / alert_horizon / speed_true / residual_gate_s)"
say "      · 좌표 경고        (촬영 회차에는 ${BLD}안 떠야${RST} 한다 → 먼저 apply_measured_coords.py)"
say "      · 배치검산 3줄     (최근접거리 중앙값 · 이웃수 분포 · 라벨 규약)"
say ""
say "  ★ Ctrl-C 로 끝낸다 — 읽은 데까지로 산출물이 나오고, 요약에 ${BLD}중단=1${RST} · CSV 에 interrupted 열이 박힌다(§4-3)."
say ""
say "${BLD}좌표 실측 반영${RST} (런 전에 반드시 — 안 하면 그 회차를 실측으로 보고할 수 없다):"
say ""
say "    $PY scripts/apply_measured_coords.py coords.txt --dry-run"
say "    $PY scripts/apply_measured_coords.py coords.txt"
say ""
say "${BLD}이 스크립트를 되돌리려면${RST}"
say "    rm -rf $VENV                              # venv (시스템은 안 건드렸다)"
say "    sudo gpasswd -d $(id -un) dialout          # dialout 그룹에서 빼기"
say "    sudo systemctl enable --now ModemManager  # 껐다면 되살리기"
say "    rm -rf $SMOKE_DIR                # 스모크 산출물 (/tmp — 재부팅하면 알아서 사라진다)"
say ""
ok "setup_pi.sh 끝"
