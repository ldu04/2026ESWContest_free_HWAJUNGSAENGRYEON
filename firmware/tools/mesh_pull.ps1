# mesh_pull.ps1 — 물리 이탈/복귀 시험 (c-2 / c-3 / d).
#
#   .\mesh_pull.ps1 -Label c2_pull -Mode remove  -TargetId 1
#   .\mesh_pull.ps1 -Label c3_plug -Mode restore -TargetId 1
#
# 절차:
#   1) 기준선 BaselineSec 초 — 살아있는 id 목록과 트리를 잡는다
#   2) 사건을 기다린다 (COM 포트 증감 또는 id 별 HB 침묵/재개)
#   3) 사건 후 AfterSec 초를 더 관찰하고 끝낸다
#   4) TOPO 변천을 시각과 함께 낸다  <- 자가치유의 직접 증거
#
# 브리지가 뽑히면 시리얼이 통째로 죽는다. 그건 예외로 잡아 BRIDGE 로 판정한다.

param(
  [string]$Port        = "COM14",
  [string]$Label       = "pull",
  [ValidateSet("remove","restore")][string]$Mode = "remove",
  [string]$TargetId    = "",
  [int]   $BaselineSec = 5,
  [int]   $MaxWaitSec  = 240,
  [int]   $AfterSec    = 60,
  [double]$SilenceSec  = 2.5,
  [int]   $MinAfterSec = 12,      # 사건 후 최소 관찰. 복구가 보이면 이 뒤로는 바로 끝낸다
  [int]   $PollMs      = 200,     # 포트 증감 확인 간격
  [string]$OutDir      = "$env:USERPROFILE\Desktop\자소서\임베디드SW경진대회\failsafe-mesh\results\hw"
)

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out   = Join-Path $OutDir ("mesh_{0}_{1}.log" -f $Label, $stamp)

$sp = New-Object System.IO.Ports.SerialPort $Port,115200,None,8,one
$sp.ReadTimeout = 120
$sp.DtrEnable = $false; $sp.RtsEnable = $false
$sp.Open(); Start-Sleep -Milliseconds 300; $sp.DiscardInBuffer()
$sw = New-Object System.IO.StreamWriter($out, $false, [System.Text.UTF8Encoding]::new($false))

$t0        = Get-Date
$lastHb    = @{}      # id -> 마지막 수신 시각(초)
$firstHb   = @{}
$countHb   = @{}
$topoSeq   = New-Object System.Collections.ArrayList   # "시각|sub문자열"
$lastTopo  = ""
$evt       = New-Object System.Collections.ArrayList
$portsPrev = @([System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object)
$portsBase = $portsPrev -join ','

$eventAt   = $null
$verdict   = ""
$detail    = ""
$bridgeDied= $false
$lastPortChk = Get-Date
$deadline  = $BaselineSec + $MaxWaitSec

function Now { return ((Get-Date) - $script:t0).TotalSeconds }

$baseAnnounced = $false

while ($true) {
  $el = Now
  if (-not $baseAnnounced -and $el -ge $BaselineSec) {
    $baseAnnounced = $true
    Write-Host "BASELINE_DONE"          # <- 이 줄이 뜨면 물리 동작을 요청해도 된다
  }
  if ($eventAt -eq $null) { if ($el -ge $deadline) { break } }
  else {
    if ($el -ge ($eventAt + $AfterSec)) { break }
    if ($el -ge ($eventAt + $MinAfterSec)) {
      # 복구 판정: (a) 사건 후 트리가 새 모양으로 바뀌었고 (b) 침묵하지 않은 노드가 모두 최근 2초 안에 HB
      $topoChanged = $false
      foreach ($ts in $topoSeq) { $tv = ($ts -split '\|')[0].TrimEnd('s'); if (([double]$tv) -gt $eventAt) { $topoChanged = $true } }
      if ($topoChanged) {
        $allFresh = $true
        foreach ($k in @($lastHb.Keys)) {
          $q = $el - $lastHb[$k]
          if ($q -gt 2.0 -and $q -lt $SilenceSec) { $allFresh = $false }   # 애매한 상태면 더 본다
        }
        if ($allFresh) { [void]$evt.Add(("{0:N1}s  복구 확인 -> 조기 종료" -f $el)); break }
      }
    }
  }

  # --- 포트 증감 감시 ---
  if (((Get-Date) - $lastPortChk).TotalMilliseconds -ge $PollMs) {
    $lastPortChk = Get-Date
    $now = @([System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object)
    $gone = @($portsPrev | Where-Object { $now -notcontains $_ })
    $new  = @($now | Where-Object { $portsPrev -notcontains $_ })
    if ($gone.Count) {
      [void]$evt.Add(("{0:N1}s  포트 사라짐: {1}" -f $el, ($gone -join ',')))
      if ($gone -contains $Port) { $bridgeDied = $true; break }
      if ($Mode -eq "remove" -and $eventAt -eq $null) { $eventAt = $el; $detail = "포트 이탈 " + ($gone -join ',') }
    }
    if ($new.Count) {
      [void]$evt.Add(("{0:N1}s  포트 생김: {1}" -f $el, ($new -join ',')))
      if ($Mode -eq "restore" -and $eventAt -eq $null) { $eventAt = $el; $detail = "포트 복귀 " + ($new -join ',') }
    }
    $portsPrev = $now
  }

  # --- HB 침묵 감시 (기준선 이후) ---
  if ($Mode -eq "remove" -and $eventAt -eq $null -and $el -gt $BaselineSec) {
    foreach ($k in @($lastHb.Keys)) {
      if (($el - $lastHb[$k]) -ge $SilenceSec) {
        $eventAt = $el
        $detail  = "id=$k HB 침묵 {0:N1}s" -f ($el - $lastHb[$k])
        [void]$evt.Add(("{0:N1}s  ★ id={1} HB 침묵 시작 (마지막 {2:N1}s)" -f $el, $k, $lastHb[$k]))
        break
      }
    }
  }

  # --- 시리얼 ---
  try {
    $ln = $sp.ReadLine().TrimEnd()
  } catch [TimeoutException] { continue }
  catch { $bridgeDied = $true; break }
  if (-not $ln) { continue }
  $el = Now
  $sw.WriteLine(("{0:N1}s | {1}" -f $el, $ln)); $sw.Flush()

  if ($ln -match '"type":"HB","id":(\d+)') {
    $k = $matches[1]
    if (-not $firstHb.ContainsKey($k)) { $firstHb[$k] = $el; $countHb[$k] = 0 }
    $lastHb[$k]  = $el
    $countHb[$k] = [int]$countHb[$k] + 1
  }
  elseif ($ln -match '"type":"TOPO"') {
    $sub = ""
    if ($ln -match '"sub":(\{.*\})\}\s*$') { $sub = $matches[1] }
    if ($sub -ne $lastTopo) { [void]$topoSeq.Add(("{0:N1}s|{1}" -f $el, $sub)); $lastTopo = $sub }
  }
  elseif ($ln -match '"type":"(ST|LG|DC)"') { [void]$evt.Add(("{0:N1}s  {1}" -f $el, $ln)) }
  elseif ($ln -match 'BOD|Brownout|rst:0x|PARSE_FAIL') { [void]$evt.Add(("{0:N1}s  ! {1}" -f $el, $ln)) }
}
$endAt = Now
$sw.Close()
try { $sp.Close() } catch {}
try { $sp.Dispose() } catch {}

# ---------- 판정 ----------
if ($bridgeDied) {
  $verdict = "BRIDGE"
} elseif ($eventAt -eq $null) {
  $verdict = "NONE"
} else {
  # 사건 후 침묵한 id 를 찾는다
  $silent = @()
  foreach ($k in @($lastHb.Keys)) { if (($endAt - $lastHb[$k]) -gt $SilenceSec) { $silent += $k } }
  if ($Mode -eq "remove") {
    if ($silent.Count -eq 1) { $verdict = "GONE:" + $silent[0] }
    elseif ($silent.Count -eq 0) { $verdict = "NO_HB_LOSS" }
    else { $verdict = "GONE_MULTI:" + (($silent | Sort-Object { [int]$_ }) -join ',') }
  } else {
    $back = @(); foreach ($k in @($lastHb.Keys)) { if ($firstHb[$k] -gt $eventAt) { $back += $k } }
    if ($back.Count) { $verdict = "BACK:" + (($back | Sort-Object { [int]$_ }) -join ',') } else { $verdict = "NO_RETURN" }
  }
}

Write-Host ""
Write-Host ("RESULT_LABEL   {0}" -f $Label)
Write-Host ("RESULT_LOG     {0}" -f $out)
Write-Host ("RESULT_VERDICT {0}" -f $verdict)
Write-Host ("RESULT_DETAIL  {0}" -f $detail)
if ($eventAt -ne $null) { Write-Host ("RESULT_EVENT_AT {0:N1}s" -f $eventAt) }
Write-Host ("RESULT_END_AT  {0:N1}s" -f $endAt)
Write-Host ("RESULT_PORTS_BASE {0}" -f $portsBase)
Write-Host ("RESULT_PORTS_NOW  {0}" -f (@([System.IO.Ports.SerialPort]::GetPortNames()|Sort-Object) -join ','))
Write-Host ""
Write-Host "=== HB ==="
foreach ($k in ($lastHb.Keys | Sort-Object { [int]$_ })) {
  $tail = $endAt - $lastHb[$k]
  $st = if ($tail -gt $SilenceSec) { "침묵" } else { "생존" }
  Write-Host ("  id={0,-4} {1,4}건  첫 {2,6:N1}s  마지막 {3,6:N1}s  이후침묵 {4,5:N1}s  {5}" -f $k,$countHb[$k],$firstHb[$k],$lastHb[$k],$tail,$st)
}
Write-Host ""
Write-Host "=== TOPO 변천 ==="
foreach ($t in $topoSeq) { Write-Host ("  " + $t) }
Write-Host ""
Write-Host "=== 이벤트 ==="
if ($evt.Count) { foreach ($e in $evt) { Write-Host ("  " + $e) } } else { Write-Host "  (없음)" }
