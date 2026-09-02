# port_watch.ps1 — COM 포트 증감을 짧은 간격으로 감시하고, 새로 생긴 포트의 mid 를 읽어 알린다.
#   보드를 물리적으로 구분할 수 없을 때, "하나씩 뽑았다 꽂게 하고 mid 로 식별"하는 용도.
param(
  [string]$TargetMid = "",
  [int]   $MaxWaitSec = 180,
  [switch]$StopAfterCycle,        # 뽑힘 -> 꽂힘 한 번을 보면 끝낸다

  [int]   $PollMs = 200
)

function Read-MidNow([string]$p,[int]$sec=8){
  try{
    $s=New-Object System.IO.Ports.SerialPort $p,115200,None,8,one
    $s.ReadTimeout=300;$s.DtrEnable=$false;$s.RtsEnable=$false
    $s.Open();Start-Sleep -Milliseconds 200;$s.DiscardInBuffer()
    $s.RtsEnable=$true;Start-Sleep -Milliseconds 120;$s.RtsEnable=$false
    $t=Get-Date;$m=$null
    while(((Get-Date)-$t).TotalSeconds -lt $sec){
      try{$l=$s.ReadLine().Trim()
        if($l -match '"type"\s*:\s*"MESHID"'){ if($l -match '"mid"\s*:\s*(\d+)'){$m=$matches[1]}; break }
      }catch [TimeoutException]{}
    }
    $s.Close();$s.Dispose();return $m
  }catch{ return $null }
}

$sawGone = $false
$prev = @([System.IO.Ports.SerialPort]::GetPortNames()|Sort-Object)
Write-Host ("시작 포트: " + ($prev -join ','))
Write-Host "WATCH_READY"
$t0 = Get-Date
while(((Get-Date)-$t0).TotalSeconds -lt $MaxWaitSec){
  Start-Sleep -Milliseconds $PollMs
  $now = @([System.IO.Ports.SerialPort]::GetPortNames()|Sort-Object)
  $gone = @($prev | Where-Object { $now -notcontains $_ })
  $new  = @($now  | Where-Object { $prev -notcontains $_ })
  if($gone.Count){ $sawGone = $true; Write-Host ("{0:N1}s  빠짐: {1}" -f ((Get-Date)-$t0).TotalSeconds, ($gone -join ',')) }
  if($new.Count){
    $el = ((Get-Date)-$t0).TotalSeconds
    foreach($p in $new){
      Start-Sleep -Milliseconds 700
      $m = Read-MidNow $p 8
      Write-Host ("{0:N1}s  생김: {1}  mid={2}" -f $el, $p, $(if($m){$m}else{"읽기실패"}))
      if($TargetMid -and $m -eq $TargetMid){
        Write-Host ("HIT {0} {1}" -f $p, $m)
        Write-Host ("최종 포트: " + ((@([System.IO.Ports.SerialPort]::GetPortNames())|Sort-Object) -join ','))
        exit 0
      }
      if($TargetMid -and $m -and $m -ne $TargetMid){ Write-Host ("MISS {0} {1}" -f $p, $m) }
      if($StopAfterCycle -and $sawGone){
        Write-Host ("CYCLE {0} {1}" -f $p, $(if($m){$m}else{"읽기실패"}))
        Write-Host ("최종 포트: " + ((@([System.IO.Ports.SerialPort]::GetPortNames())|Sort-Object) -join ','))
        exit 0
      }
    }
  }
  $prev = $now
}
Write-Host "TIMEOUT"
Write-Host ("최종 포트: " + ((@([System.IO.Ports.SerialPort]::GetPortNames())|Sort-Object) -join ','))
