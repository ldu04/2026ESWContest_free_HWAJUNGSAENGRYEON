param(
  [string]$LogPath = "C:\Users\Public\esp32\_burnloop4.txt",
  [int]$MaxMin = 90
)
$ErrorActionPreference = "SilentlyContinue"
$alert = "C:\Users\Public\esp32\alert.ps1"
$seen  = 0
$deadline = (Get-Date).AddMinutes($MaxMin)

function Say([string]$msg) {
  Write-Host ("[ALERT] " + $msg)
  & powershell -ExecutionPolicy Bypass -File $alert -Say $msg | Out-Null
}

while ((Get-Date) -lt $deadline) {
  $lines = @(Get-Content $LogPath -Encoding UTF8)
  if ($lines.Count -gt $seen) {
    for ($i = $seen; $i -lt $lines.Count; $i++) {
      $L = $lines[$i]
      if ($L -match '>>>\s*(n\d+)\s*보드를') {
        Say ("$($matches[1]) 보드를 꽂아주세요")
      }
      elseif ($L -match '^\s*\[OK\]\s*(n\d+)') {
        Say ("$($matches[1]) 굽기 성공. 다음 보드 꽂아주세요")
      }
      elseif ($L -match '^\s*\[실패\]') {
        Say "굽기 실패. 확인이 필요합니다"
      }
      elseif ($L -match '전체\s*완료|모두\s*끝') {
        Say "모든 노드 굽기가 끝났습니다"
        $seen = $lines.Count
        exit 0
      }
    }
    $seen = $lines.Count
  }
  Start-Sleep -Milliseconds 400
}
