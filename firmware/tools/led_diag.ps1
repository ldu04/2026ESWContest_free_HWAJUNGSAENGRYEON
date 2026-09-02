# led_diag.ps1 — 노드별 진단 수집. **읽기만 한다. 굽지 않는다.**
#   1단계 수동 관찰 30초 : 손대지 않은 상태에서 무엇이 나오는지, 리셋이 반복되는지
#   2단계 RTS 1회 리셋   : 부팅 로그(ROM rst:0x / MODE / MESHID)를 받아낸다
param([int]$Passive = 30, [string]$OutDir = "C:\Users\Public\esp32\diag")
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ports = @([System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object)
Write-Host ("포트 {0}개: {1}" -f $ports.Count, ($ports -join ', '))
$rows = @()
foreach ($p in $ports) {
  $raw = Join-Path $OutDir ("{0}_{1}.log" -f $p, $stamp)
  $sw = New-Object System.IO.StreamWriter($raw, $false, [System.Text.UTF8Encoding]::new($false))
  $res = [pscustomobject]@{ COM=$p; NodeId="-"; Mid="-"; Thr="-"; Warn="-"; Boot="없음"
                            Resets=0; Reason="-"; Lines=0; Passive=0; Note="" }
  try {
    $s = New-Object System.IO.Ports.SerialPort $p,115200,None,8,one
    $s.ReadTimeout = 250; $s.DtrEnable = $false; $s.RtsEnable = $false
    $s.Open(); Start-Sleep -Milliseconds 200; $s.DiscardInBuffer()
    # ── 1단계: 수동 관찰 ──
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $Passive) {
      try { $l = $s.ReadLine().TrimEnd() } catch [TimeoutException] { continue }
      if (-not $l) { continue }
      $sw.WriteLine("[passive] " + $l); $res.Lines++; $res.Passive++
      if ($l -match 'rst:0x([0-9a-fA-F]+)\s*\(([^)]+)\)') { $res.Resets++; $res.Reason = $matches[2] }
      if ($l -match 'Brownout')      { $res.Reason = "BROWNOUT"; }
      if ($l -match '"type"\s*:\s*"MESHID"') { $res.Boot = "있음(수동)" }
    }
    # ── 2단계: RTS 1회 리셋 후 부팅 로그 ──
    $s.DiscardInBuffer()
    $s.RtsEnable = $true; Start-Sleep -Milliseconds 150; $s.RtsEnable = $false
    $t1 = Get-Date
    while (((Get-Date) - $t1).TotalSeconds -lt 10) {
      try { $l = $s.ReadLine().TrimEnd() } catch [TimeoutException] { continue }
      if (-not $l) { continue }
      $sw.WriteLine("[reset] " + $l); $res.Lines++
      if ($l -match 'rst:0x([0-9a-fA-F]+)\s*\(([^)]+)\)') { $res.Reason = $matches[2] }
      if ($l -match 'Brownout') { $res.Reason = "BROWNOUT" }
      if ($l -match '"type"\s*:\s*"MESHID"') {
        $res.Boot = "있음"
        if ($l -match '"id"\s*:\s*(\d+)')  { $res.NodeId = $matches[1] }
        if ($l -match '"mid"\s*:\s*(\d+)') { $res.Mid    = $matches[1] }
        if ($l -match '"death_threshold_c"\s*:\s*([0-9.]+)') { $res.Thr  = $matches[1] }
        if ($l -match '"warn_temp_c"\s*:\s*([0-9.]+)')       { $res.Warn = $matches[1] }
        break
      }
    }
    $s.Close(); $s.Dispose()
  } catch { $res.Note = "포트 오류: " + $_.Exception.Message }
  $sw.Close()
  $rows += $res
  Write-Host ("  {0,-6} id={1,-4} boot={2,-9} 리셋 {3,-2} reason={4,-14} 줄 {5}" -f `
              $res.COM,$res.NodeId,$res.Boot,$res.Resets,$res.Reason,$res.Lines)
}
Write-Host ""
Write-Host "=== 표 ==="
$rows | Format-Table COM,NodeId,Mid,Boot,Resets,Reason,Thr,Warn,Passive -AutoSize | Out-String -Width 200
Write-Host ("원문 로그: {0}" -f $OutDir)
