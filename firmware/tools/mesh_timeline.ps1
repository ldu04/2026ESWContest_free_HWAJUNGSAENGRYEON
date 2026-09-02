# mesh_timeline.ps1 — 브리지 로그를 받아 **노드별 HB 타임라인**을 분석한다.
#
#   .\mesh_timeline.ps1 -Port COM14 -Seconds 90 -Label baseline
#
# 왜 필요한가:
#   "HB 가 몇 줄"만 세면 **언제 끊겼는지**를 못 본다.
#   TOPO 에는 남아 있는데 HB 만 끊기는 경우가 실제로 관측됐고,
#   그게 전원 문제인지 앱 패킷만 끊긴 건지 갈라야 한다.
#   노드별로 마지막 수신 시각과 최대 공백을 낸다.

param(
  [string]$Port    = "COM14",
  [int]   $Seconds = 90,
  [string]$Label   = "run",
  [string]$OutDir  = "$env:USERPROFILE\Desktop\자소서\임베디드SW경진대회\failsafe-mesh\results\hw",
  [switch]$WatchPull        # 포트가 사라지는 순간을 같이 기록
)

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out   = Join-Path $OutDir ("mesh_{0}_{1}.log" -f $Label, $stamp)

$sp = New-Object System.IO.Ports.SerialPort $Port,115200,None,8,one
$sp.ReadTimeout = 300
$sp.DtrEnable = $false; $sp.RtsEnable = $false
$sp.Open(); Start-Sleep -Milliseconds 300; $sp.DiscardInBuffer()
$sw = New-Object System.IO.StreamWriter($out, $false, [System.Text.UTF8Encoding]::new($false))

$t0 = Get-Date
$hbT   = @{}      # id -> 수신 시각(초) 목록
$topoT = New-Object System.Collections.ArrayList
$evt   = New-Object System.Collections.ArrayList
$portsBefore = @([System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object)
$pullAt = $null
$lastPortCheck = Get-Date

while (((Get-Date) - $t0).TotalSeconds -lt $Seconds) {
  if ($WatchPull -and ((Get-Date) - $lastPortCheck).TotalMilliseconds -ge 700) {
    $lastPortCheck = Get-Date
    $now = @([System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object)
    $gone = @($portsBefore | Where-Object { $now -notcontains $_ })
    if ($gone.Count -and -not $pullAt) {
      $pullAt = ((Get-Date) - $t0).TotalSeconds
      [void]$evt.Add(("{0:N1}s  ★ 포트 사라짐: {1}" -f $pullAt, ($gone -join ',')))
      $portsBefore = $now
    }
  }
  try {
    $ln = $sp.ReadLine().TrimEnd()
    if (-not $ln) { continue }
    $el = ((Get-Date) - $t0).TotalSeconds
    $sw.WriteLine(("{0:N1}s | {1}" -f $el, $ln)); $sw.Flush()
    if ($ln -match '"type":"HB","id":(\d+)') {
      $k = $matches[1]
      if (-not $hbT.ContainsKey($k)) { $hbT[$k] = New-Object System.Collections.ArrayList }
      [void]$hbT[$k].Add($el)
    }
    elseif ($ln -match '"type":"TOPO"') { [void]$topoT.Add(("{0:N1}s {1}" -f $el, $ln)) }
    elseif ($ln -match '"type":"(ST|LG|DC)"') { [void]$evt.Add(("{0:N1}s  {1}" -f $el, $ln)) }
    elseif ($ln -match 'BOD|Brownout|rst:0x|PARSE_FAIL') { [void]$evt.Add(("{0:N1}s  ! {1}" -f $el, $ln)) }
  } catch [TimeoutException] { }
}
$sw.Close(); $sp.Close(); $sp.Dispose()

Write-Host ""
Write-Host ("  [{0}] {1}초  ->  {2}" -f $Label, $Seconds, $out)
if ($pullAt) { Write-Host ("  포트 이탈 시각: {0:N1}s" -f $pullAt) -ForegroundColor Yellow }
Write-Host ""
Write-Host "  === 노드별 HB 타임라인 ==="
Write-Host ("    {0,-5} {1,6} {2,8} {3,8} {4,8}  {5}" -f "id","건수","첫수신","마지막","최대공백","판정")
foreach ($k in ($hbT.Keys | Sort-Object { [int]$_ })) {
  $a = @($hbT[$k])
  $gapMax = 0.0
  for ($i = 1; $i -lt $a.Count; $i++) { $g = $a[$i] - $a[$i-1]; if ($g -gt $gapMax) { $gapMax = $g } }
  $tail = $Seconds - $a[$a.Count-1]      # 마지막 수신 이후 침묵
  if ($tail -gt $gapMax) { $gapMax = $tail }
  $v = if ($tail -gt 5) { "★끊김(마지막 이후 {0:N0}s 침묵)" -f $tail } elseif ($gapMax -gt 5) { "중간 공백 있음" } else { "연속" }
  Write-Host ("    {0,-5} {1,6} {2,8:N1} {3,8:N1} {4,8:N1}  {5}" -f $k, $a.Count, $a[0], $a[$a.Count-1], $gapMax, $v)
}
Write-Host ""
Write-Host "  === TOPO (처음/마지막) ==="
if ($topoT.Count) { Write-Host ("    " + $topoT[0]); if ($topoT.Count -gt 1) { Write-Host ("    " + $topoT[$topoT.Count-1]) } }
if ($evt.Count) {
  Write-Host ""
  Write-Host "  === 이벤트 ==="
  foreach ($e in $evt) { Write-Host ("    " + $e) }
}
