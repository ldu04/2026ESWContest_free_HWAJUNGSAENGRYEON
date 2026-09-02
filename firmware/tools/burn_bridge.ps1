# burn_bridge.ps1 — 브리지 1대를 NODE_ID 99 로 굽는다.
#   ★ 브리지는 라벨 변환(nXX -> XX-1)을 거치지 않는다. Index 는 99 그대로다.
#   ★ 굽기 대상은 COM 번호로 정하지 않는다 — 전부 뽑은 뒤 "새로 생긴 포트" 하나로만 잠근다.
$ErrorActionPreference = "Continue"
$ROOT   = "C:\Users\Public\esp32"
$MAP    = Join-Path $ROOT "burn_map.csv"
$ALERT  = Join-Path $ROOT "alert.ps1"
$INDEX  = 99

# 블루투스 가상 COM 은 보드가 아니다. 한 번만 조회한다(Get-PnpDevice 는 호출당 5초).
$script:BTPORTS = @(Get-PnpDevice -Class Ports -PresentOnly -EA SilentlyContinue |
                    Where-Object { $_.InstanceId -notlike 'USB\*' } |
                    ForEach-Object { if ($_.Name -match '\((COM\d+)\)') { $matches[1] } })
if ($script:BTPORTS.Count) { Write-Host ("보드가 아닌 포트(제외): " + ($script:BTPORTS -join ', ')) }

function Ports { ,@([System.IO.Ports.SerialPort]::GetPortNames() |
                    Where-Object { $script:BTPORTS -notcontains $_ } | Sort-Object) }
function Say([string]$m) { & powershell -ExecutionPolicy Bypass -File $ALERT -Say $m | Out-Null }

# --- 1) 전부 뽑히기를 기다린다 ---
$cur = Ports
if ($cur.Count -gt 0) {
  Write-Host ("  현재 꽂힌 포트: " + ($cur -join ',') + " - 전부 뽑아주세요.")
  Say "보드를 전부 빼주세요"
  $t0 = [Diagnostics.Stopwatch]::StartNew()
  while ((Ports).Count -gt 0 -and $t0.Elapsed.TotalSeconds -lt 900) { Start-Sleep -Milliseconds 300 }
  if ((Ports).Count -gt 0) { Write-Host "  [중단] 포트가 남아 있다." -ForegroundColor Red; exit 2 }
}
$before = Ports

# --- 2) 브리지 한 대만 꽂히기를 기다린다 ---
Write-Host "  >>> 브리지 보드를 노트북에 직결하세요 (허브 금지)."
Say "브리지 보드를 꽂아주세요"
$swA = [Diagnostics.Stopwatch]::StartNew()
$new = @()
while ($swA.Elapsed.TotalSeconds -lt 900) {
  $new = @((Ports) | Where-Object { $before -notcontains $_ })
  if ($new.Count -ge 1) { break }
  Start-Sleep -Milliseconds 300
}
$swA.Stop()
if ($new.Count -eq 0) { Write-Host "  [중단] 새 포트가 안 잡혔다." -ForegroundColor Red; exit 3 }
if ($new.Count -ge 2) { Write-Host ("  [중단] 새 포트가 " + $new.Count + "개다: " + ($new -join ',') + " — 한 대만 꽂아라.") -ForegroundColor Red; exit 4 }
$port = $new[0]
Write-Host ("  새 포트 = {0}  <- 방금 꽂은 그 보드   (a)포트대기 {1:N1}s" -f $port, $swA.Elapsed.TotalSeconds)

# --- 3) 칩 MAC (포트가 살아있는지, 부트로더가 응답하는지 확인) ---
$swB = [Diagnostics.Stopwatch]::StartNew()
$ESPTOOL = "$env:LOCALAPPDATA\Arduino15\packages\esp32\tools\esptool_py\5.3.1\esptool.exe"
$macOut = & $ESPTOOL --port $port --before default-reset --after hard-reset read-mac 2>&1 | Out-String
$swB.Stop()
$mac = ""
if ($macOut -match 'MAC:\s*([0-9a-fA-F:]{17})') { $mac = $matches[1].ToLower() }
if (-not $mac) {
  Write-Host "  [중단] MAC 을 못 읽었다 — 굽지 않는다." -ForegroundColor Red
  Write-Host ($macOut.Trim())
  Say "브리지 굽기 실패. 확인이 필요합니다"
  exit 5
}
Write-Host ("  칩 MAC = {0}   (b)read-mac {1:N1}s" -f $mac, $swB.Elapsed.TotalSeconds)

# --- 4) 굽는다 (flash_node.ps1 이 node_id.h 생성·검증·배너대조까지 한다) ---
& powershell -ExecutionPolicy Bypass -File (Join-Path $ROOT "flash_node.ps1") -Index $INDEX -Port $port
$ok = ($LASTEXITCODE -eq 0)

# --- 5) 표에 남긴다 ---
$ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
$res = if ($ok) { "PASS" } else { "FAIL" }
Add-Content -Path $MAP -Encoding UTF8 -Value ("bridge,{0},{1},{2},-,-,-,{3},{4}" -f $INDEX, $mac, $port, $res, $ts)

if ($ok) { Write-Host "[OK] 브리지 -> NODE_ID 99" -ForegroundColor Green; Say "브리지 굽기 성공. 전부 끝났습니다" }
else     { Write-Host "[실패] 브리지" -ForegroundColor Red;              Say "브리지 굽기 실패. 확인이 필요합니다" }
exit $(if ($ok) { 0 } else { 1 })
