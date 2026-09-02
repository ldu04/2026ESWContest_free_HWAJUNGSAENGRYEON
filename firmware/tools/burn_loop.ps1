# burn_loop.ps1 — 보드를 한 대씩 꽂으면 자동으로 굽는 루프.
#
#   .\burn_loop.ps1                    # n01..n16 순서 (n16 은 마지막이라 그대로 두면 된다)
#   .\burn_loop.ps1 -Labels "1,2,3"
#
# ★ 라벨(nXX)로 받고 내부에서 NODE_ID = XX-1 로 바꾼다. (gateway/deploy_config.json 규약)
#   화면에는 "n01 -> NODE_ID 0" 처럼 둘 다 찍는다. 사람이 COM 번호를 넣는 자리는 없다.
#   브리지는 이 루프를 쓰지 않는다 — NODE_ID 99 이고 라벨 변환을 거치지 않는다.
#
# 사람의 개입은 파일 신호로 받는다(이 창은 키보드 입력을 못 받는다):
#   go.flag / skip.flag / stop.flag
param(
  [string]$Labels = "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16",
  [int]$ConfirmFirst = 3,
  [int]$WaitSec = 600,
  [string]$FlagDir = "C:\Users\Public\esp32\burnflags",
  [string]$MapCsv  = "C:\Users\Public\esp32\burn_map.csv"
)
$ESPTOOL = "$env:LOCALAPPDATA\Arduino15\packages\esp32\tools\esptool_py\5.3.1\esptool.exe"
$ALERT   = "C:\Users\Public\esp32\alert.ps1"
New-Item -ItemType Directory -Force -Path $FlagDir | Out-Null
Get-ChildItem $FlagDir -Filter *.flag -EA SilentlyContinue | Remove-Item -Force
if (-not (Test-Path $MapCsv)) { "label,node_id,mac,port,mid,thr,warn,result,ts" | Out-File $MapCsv -Encoding utf8 }

function Say([string]$t) { try { & powershell -ExecutionPolicy Bypass -File $ALERT -Say $t -Repeat 1 | Out-Null } catch {} }

# 블루투스 가상 시리얼(BTHENUM)은 보드가 아니다 — 제외 목록을 **시작할 때 한 번만** 만든다.
#   Get-PnpDevice 는 1회 5.3초가 걸린다(실측). 그걸 폴링마다 부르면 감지가 6초씩 늦는다.
#   블루투스 포트는 보드를 꽂고 빼도 안 바뀌므로 한 번만 구하면 된다.
#   GetPortNames() 는 0 ms 라 이후 폴링은 사실상 즉시다.
$script:BTPORTS = @(Get-PnpDevice -Class Ports -PresentOnly -EA SilentlyContinue |
                    Where-Object { $_.InstanceId -notlike 'USB\*' } |
                    ForEach-Object { if ($_.FriendlyName -match '\((COM\d+)\)') { $matches[1] } })
Write-Host ("보드가 아닌 포트(제외): " + $(if ($script:BTPORTS.Count) { $script:BTPORTS -join ', ' } else { "(없음)" }))
function Ports {
  ,@([System.IO.Ports.SerialPort]::GetPortNames() | Where-Object { $script:BTPORTS -notcontains $_ } | Sort-Object)
}
# 잠깐 떴다 사라지는 보드가 있다(2026-08-31 CM_PROB_PHANTOM). 굽기 직전에 다시 본다.
function PortAlive([string]$p) {
  $d = Get-PnpDevice -Class Ports -EA SilentlyContinue |
       Where-Object { $_.FriendlyName -match [regex]::Escape("($p)") }
  return ($d -and $d.Present -and $d.Problem -eq 'CM_PROB_NONE')
}
# ★★ [2026-09-01] 보드별 추가 빌드 플래그.
#   D-072 로 n04 만 LED 데이터 핀이 GPIO18 인데, 이 루프는 flash_node.ps1 을 부를 때
#   -ExtraFlags 를 **안 넘기고 있었다.** 그대로 돌리면 n04 가 다시 GPIO5 로 구워져
#   LED 가 또 안 켜진다 — D-072 가 「플래그 없이 다시 구우면 또 안 켜진다」고 경고한 그 실수다.
#   사람이 기억하는 대신 표로 남긴다.
$script:EXTRA_FLAGS = @{ 4 = "-DPIN_NEOPIXEL=18" }   # 키는 **라벨**(nXX 의 XX)
function ExtraFor([int]$label) { if ($script:EXTRA_FLAGS.ContainsKey($label)) { $script:EXTRA_FLAGS[$label] } else { "" } }

function Flag([string]$n) { Test-Path (Join-Path $FlagDir $n) }
function ClearFlags { Get-ChildItem $FlagDir -Filter *.flag -EA SilentlyContinue | Remove-Item -Force }
function WaitFlag([string[]]$names, [int]$sec = 3600) {
  $t = Get-Date
  while (((Get-Date) - $t).TotalSeconds -lt $sec) {
    foreach ($n in $names) { if (Flag $n) { ClearFlags; return $n } }
    Start-Sleep -Milliseconds 400
  }
  return $null
}

$order = @($Labels -split ',' | ForEach-Object { [int]$_.Trim() } | Where-Object { $_ -ge 1 -and $_ -le 16 })
$done = @(); $failed = @(); $skipped = @()
Write-Host ""
Write-Host ("굽기 순서(라벨): " + (($order | ForEach-Object { "n{0:D2}" -f $_ }) -join ' ')) -ForegroundColor Cyan
Write-Host ("처음 $ConfirmFirst 대는 LED 자리 확인을 위해 멈춘다. 그 뒤는 연속 진행.")

foreach ($lab in $order) {
  $id  = $lab - 1
  $tag = "n{0:D2}" -f $lab
  $seq = $done.Count + $failed.Count + $skipped.Count + 1
  Write-Host ""
  Write-Host ("[$seq/" + $order.Count + "] $tag -> NODE_ID $id   (완료 " + $done.Count + " / 실패 " + $failed.Count + " / 건너뜀 " + $skipped.Count + ")") -ForegroundColor Cyan

  if ((Ports).Count -gt 0) {
    Write-Host ("  현재 꽂힌 포트: " + ((Ports) -join ', ') + " - 전부 뽑아주세요.") -ForegroundColor Yellow
    Say "이전 보드를 빼주세요"
    $t = Get-Date
    while ((Ports).Count -gt 0 -and ((Get-Date) - $t).TotalSeconds -lt 300) { Start-Sleep -Milliseconds 150 }
  }
  $before = Ports

  Write-Host ("  >>> $tag 보드를 노트북에 직결하세요 (허브 금지).") -ForegroundColor Yellow
  Say "$tag 보드를 꽂아주세요"

  $swA = [Diagnostics.Stopwatch]::StartNew()
  $t0 = Get-Date; $new = @(); $abort = $false
  while (((Get-Date) - $t0).TotalSeconds -lt $WaitSec) {
    Start-Sleep -Milliseconds 150
    if (Flag "stop.flag") { ClearFlags; $abort = $true; break }
    if (Flag "skip.flag") { ClearFlags; $new = @("__SKIP__"); break }
    $now = Ports
    $new = @($now | Where-Object { $before -notcontains $_ })
    if ($new.Count -ge 1) { break }
  }
  if ($abort) { Write-Host "  중단 신호. 루프 종료." -ForegroundColor Yellow; break }
  if ($new.Count -eq 1 -and $new[0] -eq "__SKIP__") { Write-Host "  건너뜀." -ForegroundColor Yellow; $skipped += $tag; continue }
  if ($new.Count -eq 0) {
    Write-Host "  [중단] 새 포트가 안 잡혔다 - 케이블이 충전 전용이거나 보드가 안 잡힌다." -ForegroundColor Red
    Say "$tag 포트가 안 잡힙니다"; $failed += $tag
    if ((WaitFlag @("go.flag","skip.flag","stop.flag")) -eq "stop.flag") { break }
    continue
  }
  if ($new.Count -gt 1) {
    Write-Host ("  [중단] 새 포트가 " + $new.Count + "개다: " + ($new -join ',') + ". 한 대만 꽂아야 한다.") -ForegroundColor Red
    Say "여러 대가 꽂혔습니다"; $failed += $tag
    if ((WaitFlag @("go.flag","skip.flag","stop.flag")) -eq "stop.flag") { break }
    continue
  }
  $swA.Stop()
  $port = $new[0]
  Write-Host ("  새 포트 = $port  <- 방금 꽂은 그 보드") -ForegroundColor Green

  Start-Sleep -Milliseconds 900
  if (-not (PortAlive $port)) {
    Write-Host ("  [중단] $port 이 사라졌다(PHANTOM). 케이블/USB 구멍을 바꿔 다시.") -ForegroundColor Red
    Say "$tag 보드가 유에스비에서 떨어졌습니다"; $failed += $tag
    "$lab,$id,-,$port,-,-,-,port_phantom,$(Get-Date -f s)" | Out-File $MapCsv -Append -Encoding utf8
    if ((WaitFlag @("go.flag","skip.flag","stop.flag")) -eq "stop.flag") { break }
    continue
  }

  $swB = [Diagnostics.Stopwatch]::StartNew()
  $mac = "-"
  try {
    $o = & $ESPTOOL --port $port --before default-reset --after hard-reset read-mac 2>&1 | Out-String
    if ($o -match 'MAC:\s*([0-9a-fA-F:]{17})') { $mac = $matches[1] }
  } catch {}
  if ($mac -eq "-") {
    Write-Host "  [중단] 칩 MAC 을 못 읽었다 - 부트로더 무응답. 굽지 않는다." -ForegroundColor Red
    Say "$tag 부트로더가 응답하지 않습니다"; $failed += $tag
    "$lab,$id,-,$port,-,-,-,mac_read_fail,$(Get-Date -f s)" | Out-File $MapCsv -Append -Encoding utf8
    if ((WaitFlag @("go.flag","skip.flag","stop.flag")) -eq "stop.flag") { break }
    continue
  }
  $swB.Stop()
  Write-Host ("  칩 MAC = $mac")

  # ★ [2026-09-01] -File 로 넘길 때 **빈 문자열 인자는 사라진다.** 그러면 -ExtraFlags 가
  #   값 없이 남아 파라미터 바인딩이 실패한다(n01 1차 시도에서 실제로 났다).
  #   그래서 플래그가 있을 때만 인자를 붙인다.
  $xf = ExtraFor $lab
  $fn = "C:\Users\Public\esp32\flash_node.ps1"
  if ($xf) {
    Write-Host ("  ★ 보드별 추가 플래그: " + $xf) -ForegroundColor Yellow
    $out = & powershell -ExecutionPolicy Bypass -File $fn -Index $id -Port $port -ExtraFlags $xf 2>&1 | Out-String
  } else {
    $out = & powershell -ExecutionPolicy Bypass -File $fn -Index $id -Port $port 2>&1 | Out-String
  }
  $rc = $LASTEXITCODE
  $mid = "-"; $thr = "-"; $warn = "-"
  if ($out -match '"mid"\s*:\s*(\d+)')                  { $mid  = $matches[1] }
  if ($out -match '"death_threshold_c"\s*:\s*([\d.]+)') { $thr  = $matches[1] }
  if ($out -match '"warn_temp_c"\s*:\s*([\d.]+)')       { $warn = $matches[1] }
  $ok = ($rc -eq 0) -and ($out -match 'PASS')
  foreach ($ln in ($out -split "`r?`n")) { if ($ln -match 'PASS|FAIL|MESHID|error:') { Write-Host ("    " + $ln.Trim()) } }

  $tc = "-"; $tv = "-"
  if ($out -match 'compile_upload=([\d.]+)s') { $tc = $matches[1] }
  if ($out -match 'verify_banner=([\d.]+)s')  { $tv = $matches[1] }
  Write-Host ("  [TIME] (a)포트대기 {0:N1}s  (b)read-mac {1:N1}s  (c)compile+upload {2}s  (d)배너검증 {3}s" -f `
              $swA.Elapsed.TotalSeconds, $swB.Elapsed.TotalSeconds, $tc, $tv) -ForegroundColor DarkCyan
  if ($ok) {
    Write-Host ("  [OK] $tag -> NODE_ID $id · mid $mid · thr $thr · warn $warn") -ForegroundColor Green
    "$lab,$id,$mac,$port,$mid,$thr,$warn,PASS,$(Get-Date -f s)" | Out-File $MapCsv -Append -Encoding utf8
    $done += $tag
  } else {
    Write-Host ("  [실패] 종료코드 $rc") -ForegroundColor Red
    "$lab,$id,$mac,$port,$mid,$thr,$warn,FAIL,$(Get-Date -f s)" | Out-File $MapCsv -Append -Encoding utf8
    Say "$tag 굽기 실패"; $failed += $tag
    if ((WaitFlag @("go.flag","skip.flag","stop.flag")) -eq "stop.flag") { break }
    continue
  }

  $leftLabels = @()
  foreach ($x in $order) {
    $xt = "n{0:D2}" -f $x
    if (($done -notcontains $xt) -and ($failed -notcontains $xt) -and ($skipped -notcontains $xt)) { $leftLabels += $xt }
  }
  Write-Host ("  진행: 완료 " + $done.Count + " / 남은 번호 " + ($leftLabels -join ' '))

  if ($done.Count -le $ConfirmFirst) {
    Write-Host ("  ★ 판 위 $tag 자리 LED 가 초록인지 확인해주세요. 확인되면 계속합니다.") -ForegroundColor Magenta
    Say "$tag 완료. 판 위 자리 엘이디가 초록인지 확인해주세요"
    if ((WaitFlag @("go.flag","stop.flag")) -eq "stop.flag") { break }
  } else {
    Say "$tag 완료. 보드를 빼고 다음을 꽂아주세요"
  }
}

Write-Host ""
Write-Host "========== 결과 ==========" -ForegroundColor Cyan
Write-Host ("  완료   " + $done.Count + ": " + ($done -join ' '))
Write-Host ("  실패   " + $failed.Count + ": " + ($failed -join ' '))
Write-Host ("  건너뜀 " + $skipped.Count + ": " + ($skipped -join ' '))
Write-Host ("  표: " + $MapCsv)
Say "굽기 루프가 끝났습니다"
