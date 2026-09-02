# flash_by_mid.ps1 — 포트를 스캔해 mid 로 대상을 정하고 굽는다.
#   COM 번호는 리셋·재연결마다 바뀐다. 그래서 포트를 미리 정해두고 굽지 않는다.
#   스캔 -> mid->포트 지도 -> 대기 목록에 있는 mid 만 굽는다.
param([double]$Threshold = 40, [double]$Warn = 0)

$WANT = @{ "3179103441" = 99; "3179098605" = 2; "219922329" = 3; "3179104773" = 1 }

function Read-Banner([string]$p,[int]$sec=10){
  try{
    $s=New-Object System.IO.Ports.SerialPort $p,115200,None,8,one
    $s.ReadTimeout=400;$s.DtrEnable=$false;$s.RtsEnable=$false
    $s.Open();Start-Sleep -Milliseconds 250;$s.DiscardInBuffer()
    $s.RtsEnable=$true;Start-Sleep -Milliseconds 120;$s.RtsEnable=$false
    $t=Get-Date;$line=$null
    while(((Get-Date)-$t).TotalSeconds -lt $sec){
      try{$l=$s.ReadLine().Trim(); if($l -match '"type"\s*:\s*"MESHID"'){$line=$l;break}}catch [TimeoutException]{}
    }
    $s.Close();$s.Dispose()
    if(-not $line){ return $null }
    $mid=$null;$idv=$null;$thr=$null
    if($line -match '"mid"\s*:\s*(\d+)'){$mid=$matches[1]}
    if($line -match '"id"\s*:\s*(\d+)'){$idv=$matches[1]}
    if($line -match '"death_threshold_c"\s*:\s*([0-9.]+)'){$thr=$matches[1]}
    return [pscustomobject]@{mid=$mid;id=$idv;thr=$thr}
  }catch{ return $null }
}

$done = @()
for($round=1; $round -le 3; $round++){
  $ports = @([System.IO.Ports.SerialPort]::GetPortNames()|Sort-Object)
  Write-Host ("--- {0}회차 스캔: {1} ---" -f $round, ($ports -join ','))
  foreach($p in $ports){
    $b = Read-Banner $p 10
    if(-not $b -or -not $b.mid){ Write-Host ("  {0}  배너 읽기 실패 — 건너뜀" -f $p); continue }
    if(-not $WANT.ContainsKey($b.mid)){ Write-Host ("  {0}  mid={1} 목록에 없음 — 건너뜀" -f $p,$b.mid); continue }
    if($done -contains $b.mid){ continue }
    $idx = $WANT[$b.mid]
    $ok = ($b.thr -ne $null) -and ([math]::Abs([double]$b.thr - $Threshold) -lt 0.05) -and ([int]$b.id -eq $idx)
    if($ok -and $round -eq 1){
      # 이미 새 펌웨어 + 올바른 index 지만, WARN_TEMP_C 수정이 들어갔는지는 배너로 알 수 없다.
      # 이번 회차는 전부 다시 굽는다. (WARN 은 배너에 없다)
    }
    Write-Host ("  {0}  mid={1} id={2} thr={3}  -> NODE_ID={4} 로 굽는다" -f $p,$b.mid,$b.id,$(if($b.thr){$b.thr}else{"없음(구펌웨어)"}),$idx)
    & powershell -ExecutionPolicy Bypass -File "C:\Users\Public\esp32\flash_node.ps1" -Index $idx -Port $p -ExpectMid $b.mid -Threshold $Threshold -Warn $Warn 2>&1 |
      Select-String 'PASS|FAIL|MESHID|error:|오류' | ForEach-Object { "      $_" }
    $done += $b.mid
  }
  $left = @($WANT.Keys | Where-Object { $done -notcontains $_ })
  if($left.Count -eq 0){ break }
  Write-Host ("  남은 대상: {0}" -f ($left -join ','))
  Start-Sleep -Milliseconds 800
}
# ── [침묵실패 사전점검] 굽기 후 검산 1줄 ──────────────────────────────────
#   2026-08-30 사고: COM 번호로 대상을 정했다가 브리지를 두 대 굽고 NODE_ID 1 을 중복시켰다.
#   중복은 **조용하다** — 두 보드가 같은 좌표를 주장해도 게이트웨이는 그냥 돈다.
#   그래서 다 굽고 나면 배너를 다시 읽어 (id, mid) 쌍을 세고, 중복이 있으면 시끄럽게 죽는다.
function Verify-Fleet {
  $seen = @{}
  foreach($p in @([System.IO.Ports.SerialPort]::GetPortNames()|Sort-Object)){
    $b = Read-Banner $p 10
    if($b -and $b.mid){ if(-not $seen.ContainsKey($b.id)){$seen[$b.id]=@()}; $seen[$b.id] += $b.mid }
  }
  $line = ($seen.Keys | Sort-Object {[int]$_} | ForEach-Object { "{0}x id={1}" -f $seen[$_].Count, $_ }) -join '  '
  $dup  = @($seen.Keys | Where-Object { $seen[$_].Count -gt 1 })
  Write-Host ("검산: " + $line) -ForegroundColor $(if($dup.Count){"Red"}else{"Green"})
  if($dup.Count){
    foreach($d in $dup){ Write-Host ("  ★ NODE_ID {0} 중복 — mid {1}" -f $d, ($seen[$d] -join ', ')) -ForegroundColor Red }
    Write-Host "  중복은 게이트웨이에서 조용히 좌표를 뒤섞는다. 다시 구울 것." -ForegroundColor Red
  }
}

Write-Host ""
Verify-Fleet
Write-Host ("완료 mid: {0}" -f ($done -join ','))
$left = @($WANT.Keys | Where-Object { $done -notcontains $_ })
if($left.Count){ Write-Host ("★ 못 구운 mid: {0}" -f ($left -join ',')) -ForegroundColor Red }
