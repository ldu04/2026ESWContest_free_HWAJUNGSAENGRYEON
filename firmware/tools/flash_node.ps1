# flash_node.ps1 — node.ino 를 지정 인덱스로 굽고, **배너로 검증하고, 대장에 기록**한다.
#
#   .\flash_node.ps1 -Index 0 -Port COM3       # 0 = 브리지(루트)
#   .\flash_node.ps1 -Index 1                  # 포트 자동
#
# 왜 이 스크립트가 있나:
#   16번 반복하면 눈으로는 반드시 틀린다. 요청한 인덱스와 **보드가 실제로 찍은 인덱스**를
#   대조해서 PASS/FAIL 을 내고, build_log.csv 에 한 줄씩 남긴다.
#
# ★ 함정: `--build-property build.extra_flags=...` 를 쓰면 **플랫폼 기본 플래그를 덮어써서**
#   AsyncTCP 가 깨진다(esp32 core 3.3.11 에서 실측: "'AsyncClient' does not name a type").
#   사용자 플래그는 반드시 **compiler.cpp.extra_flags** 로 준다.
#   (firmware/flash_all.py:42 가 아직 build.extra_flags 를 쓰고 있다 — 고쳐야 한다)

param(
  [Parameter(Mandatory=$true)][int]$Index,
  [string]$Port    = "",
  [string]$Sketch  = "C:\Users\Public\esp32\sketchbook\node",
  [string]$Fqbn    = "esp32:esp32:esp32",
  [string]$LogCsv  = "C:\Users\Public\esp32\build_log.csv",
  [string]$ExpectMid = "",     # ★ 굽기 대상을 mid 로 강제한다. COM 번호로 정하지 않는다.
  [double]$Threshold = 0,      # >0 이면 -DTEMP_THRESHOLD_C 로 주입(시험용). 0 = 소스 기본값(80)
  # ★ [2026-08-30] WARN 도 주입·검증한다. 이 상수 때문에 사망확정이 구조적으로 불가능했다
  #   (임계 40 / WARN 60 -> 죽은 노드는 40℃ 이상을 방송 못 하므로 투표가 영원히 성립 안 함).
  #   0 = 주입 안 함(config.h 의 유도식 TEMP_THRESHOLD_C*0.75 를 쓴다).
  [double]$Warn = 0,
  [string]$ExtraFlags = "",   # ★ [2026-08-31] 보드별 추가 빌드 플래그(예: -DPIN_NEOPIXEL=18). 기본은 없음.
  [int]   $VerifySeconds = 12
)

$ErrorActionPreference = "Continue"

if (-not $Port) {
  $names = @([System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object)
  if ($names.Count -eq 0) { Write-Host "  COM 포트 없음. 보드를 노트북에 직결할 것." -ForegroundColor Red; exit 1 }
  if ($names.Count -gt 1) { Write-Host "  포트 여러 개: $($names -join ', ') -> -Port 지정" -ForegroundColor Red; exit 1 }
  $Port = $names[0]
}

# ★ [2026-08-30] 굽기 대상은 **mid 로 확인하고 굽는다.** COM 번호로 정하지 않는다.
#   COM 번호는 재부팅·재연결 때마다 바뀐다. 2026-08-30 사고의 직접 원인이 이것이다:
#   "COM3 를 99 로 굽는다" 고 했는데 그 사이 COM3 가 다른 보드가 되어 있었고,
#   결과적으로 브리지가 두 대가 되고 NODE_ID 1 이 중복됐다.
#   mid(painlessMesh nodeId)는 칩 MAC 에서 나와 보드마다 고유하고 재연결에도 안 바뀐다.
function Read-MidNow([string]$p, [int]$sec = 12) {
  try {
    $s = New-Object System.IO.Ports.SerialPort $p,115200,None,8,one
    $s.ReadTimeout = 400; $s.DtrEnable = $false; $s.RtsEnable = $false
    $s.Open(); Start-Sleep -Milliseconds 250; $s.DiscardInBuffer()
    $s.RtsEnable = $true; Start-Sleep -Milliseconds 120; $s.RtsEnable = $false
    $t = Get-Date; $m = $null
    while (((Get-Date)-$t).TotalSeconds -lt $sec) {
      try { $l = $s.ReadLine().Trim()
        if ($l -match '"type"\s*:\s*"MESHID"' -and $l -match '"mid"\s*:\s*(\d+)') { $m = $matches[1]; break }
      } catch [TimeoutException] {}
    }
    $s.Close(); $s.Dispose(); return $m
  } catch { return $null }
}

Write-Host ""
Write-Host "  === NODE_ID=$Index 굽기 ($Port) ===" -ForegroundColor Cyan

if ($ExpectMid) {
  $midNow = Read-MidNow $Port 12
  if ($midNow -ne $ExpectMid) {
    Write-Host ("  [FAIL] MID_MISMATCH — 기대 {0} / 실제 {1}" -f $ExpectMid, $(if($midNow){$midNow}else{"(읽기 실패)"})) -ForegroundColor Red
    Write-Host "         이 포트에 꽂힌 보드는 대상이 아니다. 굽지 않는다." -ForegroundColor Yellow
    if (-not (Test-Path $LogCsv)) {
      "date,requested_index,banner_index,is_root,role,port,usb_serial,usb_path,death_threshold_c,mesh_id,result,note" | Out-File -FilePath $LogCsv -Encoding utf8
    }
    Add-Content -Path $LogCsv -Encoding utf8 -Value ("{0},{1},,,,{2},,,,{3},FAIL,mid_mismatch_expected_{4}" -f `
      (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Index, $Port, $midNow, $ExpectMid)
    exit 3
  }
  Write-Host "  대상 확인: mid=$midNow" -ForegroundColor Green
}

# ── 컴파일 + 업로드 ────────────────────────────────────────────
# ★ [2026-08-31] NODE_ID 를 extra_flags 에서 뺀다 — 그 플래그는 모든 컴파일 단위에 붙어
#   라이브러리까지 매번 재컴파일시킨다(n03 실측 616.8초). 대신 스케치 폴더에 헤더를 만든다.
#   나머지 플래그는 보드마다 동일하므로 빌드 캐시가 유지된다.
$idh = Join-Path $Sketch "node_id.h"
$hdr = "// 자동 생성 — flash_node.ps1. 손으로 고치지 말 것.`r`n#pragma once`r`n#define NODE_ID $Index`r`n"
Set-Content -Path $idh -Value $hdr -Encoding ascii -NoNewline
$chk = (Get-Content $idh -Raw)
if ($chk -notmatch "#define NODE_ID\s+$Index($|\D)") {
  Write-Host "  [중단] node_id.h 생성 실패 — 굽지 않는다." -ForegroundColor Red; exit 6
}
Write-Host ("  node_id.h 생성: #define NODE_ID {0}" -f $Index)
$flags = "-DFAKE_TEMP_RAMP=0"
if ($ExtraFlags) { $flags += (" " + $ExtraFlags); Write-Host ("  추가 플래그: " + $ExtraFlags) -ForegroundColor Yellow }
# ★ 소수점을 강제한다. [double]40 은 "40" 으로 렌더링되어 `-DTEMP_THRESHOLD_C=40f` 가 되는데,
#   `40f` 는 C++ 에서 유효한 리터럴이 아니다(실측: unable to find numeric literal operator 'operator""f').
#   반드시 40.0f 형태여야 한다.
if ($Threshold -gt 0) { $flags += (" -DTEMP_THRESHOLD_C={0:0.0#####}f" -f $Threshold) }
if ($Warn -gt 0)      { $flags += (" -DWARN_TEMP_C={0:0.0#####}f" -f $Warn) }
$swC = [Diagnostics.Stopwatch]::StartNew()
# --build-path 를 고정해 라이브러리 오브젝트를 회차 간에 남긴다(임시경로면 매번 날아간다).
$BuildPath = "C:\esp32build\node"
New-Item -ItemType Directory -Force -Path $BuildPath | Out-Null
& arduino-cli compile --upload -p $Port -b $Fqbn --build-path $BuildPath --build-property "compiler.cpp.extra_flags=$flags" $Sketch 2>&1 |
  Select-Object -Last 3 | ForEach-Object { "    $_" }
$uploadOk = ($LASTEXITCODE -eq 0)
$swC.Stop(); Write-Host ("[TIME] compile_upload={0:N1}s" -f $swC.Elapsed.TotalSeconds)
if (-not $uploadOk) { Write-Host "  업로드 실패" -ForegroundColor Red }

# ── 검증: 포트를 열고 리셋해서 부팅 배너를 잡는다 ────────────────
$swV = [Diagnostics.Stopwatch]::StartNew()
$seenIdx = $null; $mid = $null; $rst = $null; $isRoot = $null; $bidx = $null; $role = $null; $thr = $null; $warn = $null

# ★ [2026-08-27] USB 시리얼을 대장에 남긴다 — 16보드 날의 시한폭탄 사전 파악용.
#   CP210x 개체 중 일부는 시리얼을 "0001" 로 그대로 출고한다. **같은 시리얼 둘이 동시에 꽂히면
#   Windows 가 충돌로 하나를 안 잡는다**(COM 포트가 안 생긴다).
#   시리얼이 없는 개체는 USB 경로로 식별되어 서로 충돌하지 않는다(대신 포트를 옮기면 COM 번호가 바뀐다).
#   16개 중 0001 이 몇 개인지 **그날 전에** 알아야 한다. 굽을 때마다 여기 쌓인다.
$usbSerial = ""
$usbLoc = ""
try {
  $pnp = Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match "\($Port\)" } | Select-Object -First 1
  if ($pnp -and $pnp.DeviceID -match 'VID_10C4[^\\]*\\(.+)$') {
    $tail = $matches[1]
    # 시리얼이 있으면 짧은 토큰, 없으면 '7&xxxx&0&N' 같은 USB 경로가 온다.
    if ($tail -match '^[0-9A-Za-z]+$' -and $tail -notmatch '^\d+&') { $usbSerial = $tail } else { $usbLoc = $tail }
  }
} catch { }
if ($uploadOk) {
  Start-Sleep -Milliseconds 800
  try {
    $sp = New-Object System.IO.Ports.SerialPort $Port,115200,None,8,one
    $sp.ReadTimeout = 400
    $sp.DtrEnable = $false; $sp.RtsEnable = $false
    $sp.Open(); Start-Sleep -Milliseconds 250; $sp.DiscardInBuffer()
    # DTR 은 건드리지 않는다(IO0 HIGH 유지 = 정상 부팅). RTS 로 EN 만 눌렀다 뗀다.
    $sp.RtsEnable = $true; Start-Sleep -Milliseconds 120; $sp.RtsEnable = $false

    $t0 = Get-Date
    while (((Get-Date)-$t0).TotalSeconds -lt $VerifySeconds) {
      try {
        $l = $sp.ReadLine().Trim()
        if (-not $l) { continue }
        if ($l -match '"type"\s*:\s*"MESHID"') {
          # ★ 그룹을 즉시 꺼낸다 — 다음 -match 가 성공하면 $matches 가 덮어써진다(PS 5.1).
          $line = $l
          if ($line -match '"id"\s*:\s*(\d+)')            { $seenIdx = [int]$matches[1] }
          if ($line -match '"mid"\s*:\s*(\d+)')           { $mid     = $matches[1] }
          if ($line -match '"is_root"\s*:\s*(\d+)')       { $isRoot  = [int]$matches[1] }
          if ($line -match '"bridge_index"\s*:\s*(\d+)')  { $bidx    = [int]$matches[1] }
          if ($line -match '"role"\s*:\s*"([^"]+)"')      { $role    = $matches[1] }
          if ($line -match '"death_threshold_c"\s*:\s*([\d\.]+)') { $thr = [double]$matches[1] }
          if ($line -match '"warn_temp_c"\s*:\s*([\d\.]+)') { $warn = [double]$matches[1] }
          Write-Host "    $line" -ForegroundColor DarkGray
          break
        }
        if ($l -match 'rst:0x') { $rst = $l }
      } catch [TimeoutException] { }
    }
    $sp.Close(); $sp.Dispose()
  } catch { Write-Host "  시리얼 검증 실패: $($_.Exception.Message)" -ForegroundColor Yellow }
}

# ── 판정 ──────────────────────────────────────────────────────
# ★ 역할까지 대조한다. index 만 보면 "브리지인데 루트가 아닌" 침묵 실패를 못 잡는다.
#   브리지 번호로 구웠는데 is_root=0 이면 NODE_IS_ROOT 매크로가 안 따라온 것이고,
#   그 보드는 시리얼 중계를 안 한다 = 게이트웨이 입력이 통째로 0줄이 된다.
$expectRoot = ($bidx -ne $null -and $Index -eq $bidx)
$result = "FAIL"
$swV.Stop(); Write-Host ("[TIME] verify_banner={0:N1}s" -f $swV.Elapsed.TotalSeconds)
if     (-not $uploadOk)                        { $why = "upload_failed" }
elseif ($seenIdx -eq $null)                    { $why = "no_MESHID_banner" }
elseif ($seenIdx -ne $Index)                   { $why = "index_mismatch" }
elseif ($isRoot -eq $null)                     { $why = "no_is_root_field(구 펌웨어)" }
elseif ($expectRoot -and $isRoot -ne 1)        { $why = "BRIDGE_NOT_ROOT" }
elseif ((-not $expectRoot) -and $isRoot -eq 1) { $why = "NODE_IS_ROOT(격자노드가 루트)" }
elseif ($thr -eq $null)                        { $why = "no_death_threshold_field(구 펌웨어)" }
elseif ($Threshold -le 0 -and [math]::Abs($thr - 80.0) -gt 0.05) { $why = "THRESHOLD_NOT_80(임시값이 남았다: $thr)" }
elseif ($Threshold -gt 0 -and [math]::Abs($thr - $Threshold) -gt 0.05) { $why = "THRESHOLD_MISMATCH(요청 $Threshold / 배너 $thr)" }
elseif ($warn -eq $null)                       { $why = "no_warn_temp_field(구 펌웨어 — 배너에 warn_temp_c 가 없다)" }
elseif ($Warn -gt 0 -and [math]::Abs($warn - $Warn) -gt 0.05) { $why = "WARN_MISMATCH(요청 $Warn / 배너 $warn)" }
elseif ($warn -ge $thr)                        { $why = "WARN_GE_THRESHOLD(warn $warn >= thr $thr — 사망 투표가 영원히 성립하지 않는다)" }
else                                           { $result = "PASS"; $why = "" }

Write-Host ""
if ($result -eq "PASS") {
  Write-Host ("  [PASS] index {0} / role {1} / is_root={2} / thr={3}C / warn={4}C / meshId={5}" -f `
              $seenIdx, $role, $isRoot, $thr, $warn, $mid) -ForegroundColor Green
} else {
  Write-Host ("  [FAIL] {0}" -f $why) -ForegroundColor Red
  Write-Host ("         요청 index={0}  배너 index={1}  is_root={2}  bridge_index={3}  role={4}" -f `
              $Index, $seenIdx, $isRoot, $bidx, $role) -ForegroundColor Red
  if ($why -like "THRESHOLD_NOT_80*") {
    Write-Host "         -> config.h 에 시험용 임시 임계가 박혀 있다. 소스 기본값은 80.0f 여야 한다." -ForegroundColor Yellow
    Write-Host "            시험은 -Threshold 40 (빌드 플래그)으로만 할 것." -ForegroundColor Yellow
  }
  if ($why -eq "BRIDGE_NOT_ROOT") {
    Write-Host "         -> config.h 의 NODE_IS_ROOT 가 BRIDGE_INDEX 를 따라가지 않는다." -ForegroundColor Yellow
    Write-Host "            이 보드는 시리얼 중계를 안 한다. 게이트웨이 입력이 0줄이 된다." -ForegroundColor Yellow
  }
}

# ── 대장 기록 ─────────────────────────────────────────────────
if (-not (Test-Path $LogCsv)) {
  "date,requested_index,banner_index,is_root,role,port,usb_serial,usb_path,death_threshold_c,mesh_id,result,note" | Out-File -FilePath $LogCsv -Encoding utf8
}
$row = "{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Index,
       $(if ($seenIdx -ne $null) { $seenIdx } else { "" }),
       $(if ($isRoot -ne $null) { $isRoot } else { "" }),
       $(if ($role) { $role } else { "" }), $Port,
       $(if ($usbSerial) { $usbSerial } else { "" }),
       $(if ($usbLoc) { $usbLoc } else { "" }),
       $(if ($thr -ne $null) { $thr } else { "" }),
       $(if ($mid) { $mid } else { "" }), $result, $why
Add-Content -Path $LogCsv -Value $row -Encoding utf8
Write-Host "  대장: $LogCsv"
Write-Host ""
if ($result -eq "PASS") { exit 0 } else { exit 2 }
