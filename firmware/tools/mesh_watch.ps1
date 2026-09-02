# mesh_watch.ps1 — 브리지 시리얼을 받아 원문 + 요약을 남긴다 (자가치유 시험용).
#
#   .\mesh_watch.ps1 -Port COM14 -Seconds 35 -Label c1_stable
#
# 원문은 파일로 그대로 남기고(보고서 근거), 화면에는 TOPO 와 요약만 낸다.

param(
  [string]$Port    = "COM14",
  [int]   $Seconds = 35,
  [string]$Label   = "run",
  [string]$OutDir  = "$env:USERPROFILE\Desktop\자소서\임베디드SW경진대회\failsafe-mesh\results\hw"
)

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out   = Join-Path $OutDir ("mesh_{0}_{1}.log" -f $Label, $stamp)

$sp = New-Object System.IO.Ports.SerialPort $Port,115200,None,8,one
$sp.ReadTimeout = 500
$sp.DtrEnable = $false; $sp.RtsEnable = $false     # ★ 건드리면 다운로드 모드로 빠진다
$sp.Open(); Start-Sleep -Milliseconds 300; $sp.DiscardInBuffer()

$sw = New-Object System.IO.StreamWriter($out, $false, [System.Text.UTF8Encoding]::new($false))
$t0 = Get-Date
$topo = New-Object System.Collections.ArrayList
$hb   = @{}
$parseFail = 0; $reboot = 0; $lines = 0
$st = New-Object System.Collections.ArrayList
$lg = New-Object System.Collections.ArrayList
$dc = New-Object System.Collections.ArrayList

while (((Get-Date) - $t0).TotalSeconds -lt $Seconds) {
  try {
    $ln = $sp.ReadLine().TrimEnd()
    if (-not $ln) { continue }
    $el = ((Get-Date) - $t0).TotalSeconds
    $tag = ("{0:N1}" -f $el).PadLeft(6)
    $sw.WriteLine(($tag + "s | " + $ln)); $sw.Flush()
    $lines++
    if ($ln -match 'TOPO')       { [void]$topo.Add(($tag + "s " + $ln)) }
    if ($ln -match 'PARSE_FAIL') { $parseFail++ }
    if ($ln -match 'BOD|Brownout|rst:0x') { $reboot++ }
    if ($ln -match '"type":"HB","id":(\d+)') { $k = $matches[1]; $hb[$k] = [int]$hb[$k] + 1 }
    if ($ln -match '"type":"ST"') { [void]$st.Add(($tag + "s " + $ln)) }
    if ($ln -match '"type":"LG"') { [void]$lg.Add(($tag + "s " + $ln)) }
    if ($ln -match '"type":"DC"') { [void]$dc.Add(($tag + "s " + $ln)) }
  } catch [TimeoutException] { }
}
$sw.Close(); $sp.Close(); $sp.Dispose()

Write-Host ""
Write-Host ("  [{0}] {1}초 · {2}줄  ->  {3}" -f $Label, $Seconds, $lines, $out)
Write-Host ""
Write-Host "  === TOPO ==="
foreach ($t in $topo) { Write-Host ("    " + $t) }
Write-Host ""
Write-Host "  === HB 발신자 ==="
foreach ($k in ($hb.Keys | Sort-Object { [int]$_ })) { Write-Host ("    id={0,-4} {1}줄" -f $k, $hb[$k]) }
if ($st.Count) { Write-Host ""; Write-Host "  === ST ==="; foreach ($x in $st) { Write-Host ("    " + $x) } }
if ($lg.Count) { Write-Host ""; Write-Host "  === LG (임종신호) ==="; foreach ($x in $lg) { Write-Host ("    " + $x) } }
if ($dc.Count) { Write-Host ""; Write-Host "  === DC (사망확정) ==="; foreach ($x in $dc) { Write-Host ("    " + $x) } }
Write-Host ""
Write-Host ("  PARSE_FAIL {0} · 재부팅 {1}" -f $parseFail, $reboot)
