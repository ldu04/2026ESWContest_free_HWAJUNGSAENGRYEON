# flash_queue.ps1 — 보드가 바뀌는 걸 스스로 감지해서 다음 인덱스로 굽는다.
#
#   .\flash_queue.ps1 -Indices 1,2,3 -Port COM3 -KnownMids 219922329
#
# 왜 필요한가:
#   데이터 경로가 COM3 하나뿐이라 보드를 하나씩 갈아 끼워야 하는데,
#   매번 사람에게 "다음 보드 꽂아주세요" 라고 물으면 진행이 멈춘다.
#   보드를 **painlessMesh nodeId(mid)** 로 식별해서, 새 보드가 보이면 자동으로 굽는다.
#
# 식별 원리:
#   mid 는 칩 MAC 에서 나오므로 **보드마다 고유**하다. CP2102 시리얼(전부 0001)과 달리 구분된다.
#   이미 구운 mid 가 보이면 = 아직 안 바꿨다 -> 기다린다.
#   MESHID 가 안 나오면 = 구 펌웨어 = 새 보드 -> 굽는다.

# ★ 배열 파라미터를 쓰지 않는다 — `powershell -File script.ps1 -Indices 1,2,3` 으로 넘기면
#   PowerShell 이 "1,2,3" 을 **하나의 값**으로 넘겨 [int[]] 캐스팅이 123 이 된다(실측: NODE_ID=123
#   으로 구울 뻔했다). 문자열로 받아 직접 쪼갠다.
param(
  [string]$Indices    = "1,2,3",
  [string]$Port       = "COM3",
  [string]$KnownMids  = "",
  [int]   $TimeoutMin = 40
)

$ErrorActionPreference = "Continue"
$idxList = @($Indices -split '\s*,\s*' | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ })
if ($idxList.Count -eq 0) { Write-Host "  -Indices 파싱 실패: '$Indices'" -ForegroundColor Red; exit 1 }
$known = New-Object System.Collections.Generic.HashSet[long]
foreach ($m in ($KnownMids -split '\s*,\s*')) { if ($m -match '^\d+$') { [void]$known.Add([long]$m) } }

# 보드를 리셋하고 MESHID 를 읽는다. 못 읽으면 $null (= 구 펌웨어 = 새 보드).
function Read-Mid([string]$p, [int]$sec = 10) {
  try {
    $sp = New-Object System.IO.Ports.SerialPort $p,115200,None,8,one
    $sp.ReadTimeout = 400
    $sp.DtrEnable = $false; $sp.RtsEnable = $false
    $sp.Open(); Start-Sleep -Milliseconds 250; $sp.DiscardInBuffer()
    $sp.RtsEnable = $true; Start-Sleep -Milliseconds 120; $sp.RtsEnable = $false
    $t0 = Get-Date; $mid = $null
    while (((Get-Date)-$t0).TotalSeconds -lt $sec) {
      try {
        $l = $sp.ReadLine().Trim()
        if ($l -match '"type"\s*:\s*"MESHID"' -and $l -match '"mid"\s*:\s*(\d+)') { $mid = [long]$matches[1]; break }
      } catch [TimeoutException] { }
    }
    $sp.Close(); $sp.Dispose()
    return $mid
  } catch { return $null }
}

Write-Host ""
Write-Host "  ===== 굽기 큐 시작 =====" -ForegroundColor Cyan
Write-Host "  대상 인덱스: $($idxList -join ', ')   이미 구운 mid: $($known -join ', ')"
Write-Host "  보드를 갈아 끼우면 자동으로 감지해서 굽습니다. (최대 ${TimeoutMin}분 대기)"
Write-Host ""

$deadline = (Get-Date).AddMinutes($TimeoutMin)
foreach ($idx in $idxList) {
  Write-Host "  --- NODE_ID=$idx 를 받을 보드를 기다리는 중 ---" -ForegroundColor Yellow
  $flashed = $false
  while (-not $flashed) {
    if ((Get-Date) -gt $deadline) { Write-Host "  시간 초과. 큐 중단." -ForegroundColor Red; exit 3 }

    $names = @([System.IO.Ports.SerialPort]::GetPortNames())
    if ($names -notcontains $Port) {
      Start-Sleep -Seconds 3
      continue                                  # 뽑혀 있음 -> 기다린다
    }

    $mid = Read-Mid $Port 10
    if ($mid -ne $null -and $known.Contains($mid)) {
      Start-Sleep -Seconds 4                    # 아직 같은 보드 -> 기다린다
      continue
    }

    # 새 보드다 (mid 가 새것이거나, MESHID 가 없는 구 펌웨어)
    if ($mid -eq $null) { Write-Host "    새 보드 감지 (MESHID 없음 = 구 펌웨어)" }
    else                { Write-Host "    새 보드 감지 (mid=$mid)" }

    & powershell -ExecutionPolicy Bypass -File "C:\Users\Public\esp32\flash_node.ps1" -Index $idx -Port $Port
    $rc = $LASTEXITCODE

    $newMid = Read-Mid $Port 10
    if ($rc -eq 0 -and $newMid -ne $null) {
      [void]$known.Add($newMid)
      Write-Host "  [완료] NODE_ID=$idx  mid=$newMid" -ForegroundColor Green
      $flashed = $true
    } else {
      Write-Host "  [실패] NODE_ID=$idx (rc=$rc). 5초 후 재시도." -ForegroundColor Red
      Start-Sleep -Seconds 5
    }
  }
}

Write-Host ""
Write-Host "  ===== 큐 완료 =====" -ForegroundColor Green
Write-Host "  대장: C:\Users\Public\esp32\build_log.csv"
Get-Content "C:\Users\Public\esp32\build_log.csv" | ForEach-Object { "    $_" }
