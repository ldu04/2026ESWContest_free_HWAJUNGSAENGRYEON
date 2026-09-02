# death_watch.ps1 — (d) 실물 사망 시험.
#   -Mode identify : 어느 보드를 손으로 잡았는지 온도 상승으로 특정하고 즉시 끝낸다
#   -Mode death    : 사망 경로(ST/LG/DV/DC)를 시각과 함께 기록한다
#
# 폴링을 따로 돌리지 않는다. 시리얼 ReadLine(120ms 타임아웃)이 그대로 페이싱이 된다.
#
# ─────────────────────────────────────────────────────────────────────────────
# ★ [2026-08-30] 사망 시험은 **단독으로 하지 않는다. t80 교정 3발에 합친다.**
#
#   왜: 손으로 센서를 쥐어 임계까지 올리는 방식은 두 가지가 틀렸다.
#     (1) 보드를 쥐면 USB 케이블이 당겨져 접점이 순간 끊기고 브라운아웃이 난다.
#         실측 — mesh_d_ident3_20260830_050015.log 에서 175초 동안 BOD 5회,
#         브리지 4회 재부팅. 보드를 아무도 안 만진 90초 구간(baseline_pd65)은 BOD 0건.
#     (2) 데모의 실제 사망 조건은 열풍기다. 손 온도로 만든 사망은 데모 조건이 아니다.
#
#   그래서 t80 을 재는 그 3발에서, 열풍기가 노드를 실제 임계까지 올리는 동안
#   이 스크립트를 **같이** 돌려 사망 전파 시각을 한 로그에 남긴다.
#
#   t80 측정과 같이 돌리는 법:
#       # 창 1 — t80 (센서 온도 상승 곡선)
#       .\log_tau.ps1 -Label tau_hotgun_d30_T200_s3_n01_r1
#       # 창 2 — 사망 전파 (브리지에서 본 ST/LG/DV/DC)
#       .\death_watch.ps1 -Port <브리지> -Mode death -Label d_r1 -MaxSec 600
#
#   두 로그는 벽시계가 아니라 **노드 자기 각인 시각(nt)** 으로 맞춘다(제약③).
#   뽑아야 할 값: ST(ALIVE→DYING) / LG / DV 3표 / DC, 그리고 LG→DC 전파 시간.
#   ★ 굽기 임계는 데모값(80℃)으로 되돌린 뒤 측정할 것. 34℃/40℃ 는 손 시험용 임시값이었다.
# ─────────────────────────────────────────────────────────────────────────────

param(
  [string]$Port      = "COM3",
  [ValidateSet("identify","death")][string]$Mode = "identify",
  [string]$Label     = "d",
  [double]$RiseC     = 2.0,     # identify: 기준선 대비 이만큼 오르면 그 보드로 판정
  [int]   $BaseSec   = 5,
  [int]   $MaxSec    = 240,
  [int]   $AfterDcSec= 15,      # death: DC 를 본 뒤 이만큼만 더 보고 끝낸다
  [string]$OutDir    = "$env:USERPROFILE\Desktop\자소서\임베디드SW경진대회\failsafe-mesh\results\hw"
)

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out   = Join-Path $OutDir ("mesh_{0}_{1}.log" -f $Label, $stamp)

$sp = New-Object System.IO.Ports.SerialPort $Port,115200,None,8,one
$sp.ReadTimeout = 120
$sp.DtrEnable = $false; $sp.RtsEnable = $false
$sp.Open(); Start-Sleep -Milliseconds 250; $sp.DiscardInBuffer()
$sw = New-Object System.IO.StreamWriter($out, $false, [System.Text.UTF8Encoding]::new($false))

$t0 = Get-Date
$baseT = @{}      # id -> 기준선 온도
$curT  = @{}      # id -> 최근 온도
$peakT = @{}      # id -> 최고 온도
$marks = New-Object System.Collections.ArrayList
$announced = $false
$dcAt = $null
$lgAt = $null
$stSeq = New-Object System.Collections.ArrayList
$dvSeq = New-Object System.Collections.ArrayList
$dcLine = ""
$lgLine = ""

while ($true) {
  $el = ((Get-Date) - $t0).TotalSeconds
  if ($el -ge $MaxSec) { break }
  if (-not $announced -and $el -ge $BaseSec) {
    $announced = $true
    Write-Host ("BASELINE_DONE " + (($baseT.Keys | Sort-Object {[int]$_} | ForEach-Object { "id$_=$($baseT[$_])" }) -join ' '))
  }
  if ($dcAt -ne $null -and $el -ge ($dcAt + $AfterDcSec)) { break }

  try { $ln = $sp.ReadLine().TrimEnd() } catch [TimeoutException] { continue } catch { break }
  if (-not $ln) { continue }
  $el = ((Get-Date) - $t0).TotalSeconds
  $sw.WriteLine(("{0:N2}s | {1}" -f $el, $ln)); $sw.Flush()

  if ($ln -match '"type"\s*:\s*"HB"') {
    $idv = $null; $tp = $null
    if ($ln -match '"id"\s*:\s*(\d+)')            { $idv = $matches[1] }
    if ($ln -match '"temp"\s*:\s*(-?[0-9.]+)')    { $tp  = [double]$matches[1] }
    if ($idv -ne $null -and $tp -ne $null) {
      $curT[$idv] = $tp
      if (-not $peakT.ContainsKey($idv) -or $tp -gt $peakT[$idv]) { $peakT[$idv] = $tp }
      if (-not $baseT.ContainsKey($idv) -and $el -lt $BaseSec) { $baseT[$idv] = $tp }
      if ($Mode -eq "identify" -and $announced -and $baseT.ContainsKey($idv)) {
        if (($tp - $baseT[$idv]) -ge $RiseC) {
          Write-Host ("WARM {0} base={1} now={2} rise={3:N1}" -f $idv, $baseT[$idv], $tp, ($tp - $baseT[$idv]))
          break
        }
      }
    }
  }
  elseif ($ln -match '"type"\s*:\s*"ST"') { [void]$stSeq.Add(("{0:N2}s {1}" -f $el, $ln)) }
  elseif ($ln -match '"type"\s*:\s*"LG"') { if ($lgAt -eq $null) { $lgAt = $el; $lgLine = $ln }; [void]$marks.Add(("{0:N2}s LG" -f $el)) }
  elseif ($ln -match '"type"\s*:\s*"DV"') { [void]$dvSeq.Add(("{0:N2}s {1}" -f $el, $ln)) }
  elseif ($ln -match '"type"\s*:\s*"DC"') { if ($dcAt -eq $null) { $dcAt = $el; $dcLine = $ln }; [void]$marks.Add(("{0:N2}s DC" -f $el)) }
  elseif ($ln -match 'BOD|Brownout|rst:0x|PARSE_FAIL') { [void]$marks.Add(("{0:N2}s ! {1}" -f $el, $ln)) }
}
$endAt = ((Get-Date) - $t0).TotalSeconds
$sw.Close(); try { $sp.Close() } catch {}; try { $sp.Dispose() } catch {}

Write-Host ""
Write-Host ("RESULT_LOG  {0}" -f $out)
Write-Host ("RESULT_END  {0:N1}s" -f $endAt)
Write-Host "=== 온도 (기준선 / 현재 / 최고) ==="
foreach ($k in ($peakT.Keys | Sort-Object {[int]$_})) {
  Write-Host ("  id={0,-4} base={1,6} now={2,6} peak={3,6}" -f $k, $(if($baseT.ContainsKey($k)){$baseT[$k]}else{"-"}), $curT[$k], $peakT[$k])
}
if ($Mode -eq "death") {
  Write-Host ""
  Write-Host "=== ST (상태 전이) ==="
  if ($stSeq.Count) { foreach ($x in $stSeq) { Write-Host ("  " + $x) } } else { Write-Host "  (없음)" }
  Write-Host "=== DV (사망 투표) ==="
  if ($dvSeq.Count) { foreach ($x in $dvSeq) { Write-Host ("  " + $x) } } else { Write-Host "  (없음)" }
  Write-Host "=== LG ==="
  if ($lgAt -ne $null) { Write-Host ("  {0:N2}s  {1}" -f $lgAt, $lgLine) } else { Write-Host "  (없음)" }
  Write-Host "=== DC ==="
  if ($dcAt -ne $null) {
    Write-Host ("  {0:N2}s  {1}" -f $dcAt, $dcLine)
    Write-Host ("  LG -> DC 전파 {0:N2}s" -f ($dcAt - $lgAt))
  } else { Write-Host "  ★ DC 없음 — 사망확정 실패" }
}
if ($marks.Count) { Write-Host ""; Write-Host "=== 표시 ==="; foreach ($m in $marks) { Write-Host ("  " + $m) } }
