# burn_one.ps1 — 보드 한 대를 굽는다. **8/30 오굽기 사고를 구조로 막는다.**
#
#   1) 굽기 전 포트 목록을 찍는다
#   2) 사용자가 보드 **한 대만** 꽂는다
#   3) 새로 생긴 포트를 찾는다 → 그게 방금 꽂은 보드다 (COM 번호로 추측하지 않는다)
#   4) 굽는다
#   5) 배너로 NODE_ID·role·임계를 대조한다. 통과해야 끝난다.
#
#   .\burn_one.ps1 -Index 5
#   .\burn_one.ps1 -Index 99            # 브리지
#   .\burn_one.ps1 -Index 5 -IdentifyOnly   # 굽지 않고 정체만 확인
param(
  [Parameter(Mandatory=$true)][int]$Index,
  [int]$WaitSec = 90,
  [switch]$IdentifyOnly,
  [double]$Threshold = 0,     # 0 = 소스 기본값 80.0f (데모값). 시험용으로만 지정할 것
  [double]$Warn = 0
)
$ESPTOOL = "$env:LOCALAPPDATA\Arduino15\packages\esp32\tools\esptool_py\5.3.1\esptool.exe"

# ★ 블루투스 가상 시리얼(BTHENUM)은 보드가 아니다. 항상 떠 있어서 기준선을 오염시킨다.
#   실제로 COM16·COM17 이 그것이었다(2026-08-31). USB 시리얼만 센다.
function Ports {
  $usb = @(Get-PnpDevice -Class Ports -PresentOnly -EA SilentlyContinue |
           Where-Object { $_.InstanceId -like 'USB\*' } |
           ForEach-Object { if ($_.FriendlyName -match '\((COM\d+)\)') { $matches[1] } })
  ,@([System.IO.Ports.SerialPort]::GetPortNames() | Where-Object { $usb -contains $_ } | Sort-Object)
}
# 그 포트가 **지금도 살아 있는지** 확인한다. 잠깐 떴다 사라지는 보드가 있다
#   (2026-08-31: 새로 꽂은 보드가 COM3 로 떴다가 CM_PROB_PHANTOM 으로 사라져 업로드가 실패했다).
function PortAlive([string]$p) {
  $d = Get-PnpDevice -Class Ports -EA SilentlyContinue |
       Where-Object { $_.FriendlyName -match [regex]::Escape("($p)") }
  return ($d -and $d.Present -and $d.Problem -eq 'CM_PROB_NONE')
}

Write-Host ""
Write-Host ("=== NODE_ID {0} 굽기 ===" -f $Index) -ForegroundColor Cyan
$before = Ports
Write-Host ("  굽기 전 포트: {0}" -f $(if ($before.Count) { $before -join ', ' } else { "(없음)" }))
Write-Host ""
Write-Host "  >>> 지금 보드를 **한 대만** 노트북에 직결하세요 (허브 금지). 최대 $WaitSec 초 대기." -ForegroundColor Yellow

$t0 = Get-Date; $new = @()
while (((Get-Date) - $t0).TotalSeconds -lt $WaitSec) {
  Start-Sleep -Milliseconds 300
  $now = Ports
  $new = @($now | Where-Object { $before -notcontains $_ })
  $gone = @($before | Where-Object { $now -notcontains $_ })
  if ($gone.Count) { Write-Host ("  ! 포트가 사라졌다: {0} — 다른 보드를 뽑았습니까?" -f ($gone -join ',')) -ForegroundColor Red; $before = $now }
  if ($new.Count -ge 1) { break }
}
if ($new.Count -eq 0) {
  Write-Host "  [중단] 새 포트가 안 잡혔다." -ForegroundColor Red
  Write-Host "         케이블이 충전 전용일 수 있다. 다른 케이블/다른 USB 구멍으로 바꿔 다시 시도할 것." -ForegroundColor Yellow
  exit 1
}
if ($new.Count -gt 1) {
  Write-Host ("  [중단] 새 포트가 {0}개 잡혔다: {1}" -f $new.Count, ($new -join ',')) -ForegroundColor Red
  Write-Host "         **한 대만** 꽂아야 한다. 전부 뽑고 다시 시작할 것." -ForegroundColor Yellow
  exit 1
}
$port = $new[0]
Write-Host ("  새 포트 = {0}  ← 방금 꽂은 그 보드다" -f $port) -ForegroundColor Green

# 정체 확인 — 굽기 전 상태를 기록한다(공장 AT / 옛 스케치 / node.ino)
Write-Host "  현재 이 보드가 무엇인지 확인 중..."
$mac = "-"
try {
  $out = & $ESPTOOL --port $port --before default-reset --after hard-reset read-mac 2>&1 | Out-String
  if ($out -match 'MAC:\s*([0-9a-fA-F:]{17})') { $mac = $matches[1] }
} catch { }
Write-Host ("  칩 MAC = {0}   (보드 고유. 굽기 전후가 같아야 같은 보드다)" -f $mac)

# ── 굽기 직전 재확인 — 여기서 막지 않으면 "포트가 사라진 보드"에 업로드를 시도한다 ──
Start-Sleep -Milliseconds 800
if (-not (PortAlive $port)) {
  Write-Host ("  [중단] {0} 이 사라졌다(CM_PROB_PHANTOM). 보드가 USB 버스에서 떨어졌다." -f $port) -ForegroundColor Red
  Write-Host "         케이블을 바꾸거나 다른 USB 구멍에 꽂고 다시 실행할 것. 굽지 않았다." -ForegroundColor Yellow
  exit 4
}
if ($mac -eq "-") {
  Write-Host "  [중단] 칩 MAC 을 읽지 못했다 — 부트로더가 응답하지 않는다." -ForegroundColor Red
  Write-Host "         이 상태로 업로드하면 실패한다. 케이블/USB 구멍을 바꿔 다시 실행할 것. 굽지 않았다." -ForegroundColor Yellow
  exit 5
}

if ($IdentifyOnly) {
  Write-Host "  -IdentifyOnly — 굽지 않고 끝낸다." -ForegroundColor Yellow
  Write-Host ("  기록: NODE_ID {0} 예정 / {1} / MAC {2}" -f $Index, $port, $mac)
  exit 0
}

# 굽기 — flash_node.ps1 이 배너로 index·role·임계를 대조한다(통과 못 하면 FAIL)
$args = @("-Index", $Index, "-Port", $port)
if ($Threshold -gt 0) { $args += @("-Threshold", $Threshold) }
if ($Warn -gt 0)      { $args += @("-Warn", $Warn) }
Write-Host ""
& powershell -ExecutionPolicy Bypass -File "C:\Users\Public\esp32\flash_node.ps1" @args
$rc = $LASTEXITCODE

Write-Host ""
if ($rc -eq 0) {
  Write-Host ("  [OK] NODE_ID {0} · {1} · MAC {2}" -f $Index, $port, $mac) -ForegroundColor Green
  Write-Host "  이 보드를 판의 해당 자리에 놓고, **뽑은 뒤** 다음 보드로 넘어가세요."
} else {
  Write-Host ("  [실패] 종료코드 {0} — 다음 보드로 넘어가지 마세요." -f $rc) -ForegroundColor Red
}
exit $rc
