# build_node.ps1 — node.ino 복사 → 컴파일 → 업로드 → 시리얼 캡처 (한 번에)
#
# 사용법:
#   powershell -ExecutionPolicy Bypass -File scripts\build_node.ps1                 # 컴파일만
#   powershell -ExecutionPolicy Bypass -File scripts\build_node.ps1 -Upload         # 업로드까지
#   powershell -ExecutionPolicy Bypass -File scripts\build_node.ps1 -Upload -Capture 40
#
# 배경: 저장소가 한글 경로에 있어 GNU 툴체인이 깨지므로 영문 경로로 복사해서 빌드한다.
#       자세한 내용과 라이브러리 버전 고정은 firmware/BUILD.md 참조.
param(
    [string]$Port    = "",        # 비우면 자동 탐지
    [switch]$Upload,              # 업로드 수행
    [int]$Capture    = 0,         # >0 이면 업로드 후 그 초만큼 시리얼 캡처
    [string]$Label   = "phaseB"   # 캡처 로그 파일 이름표
)

$ErrorActionPreference = "Stop"

$Repo    = Split-Path -Parent $PSScriptRoot
$Src     = Join-Path $Repo "firmware\node"
$Work    = "C:\Users\Public\esp32\sketchbook\node"     # 영문 경로 필수
$Fqbn    = "esp32:esp32:esp32"
$Cli     = "arduino-cli"

Write-Host "=== [1/4] 영문 경로로 복사 ===" -ForegroundColor Cyan
if (-not (Test-Path $Work)) { New-Item -ItemType Directory -Force -Path $Work | Out-Null }
Copy-Item (Join-Path $Src "node.ino")  $Work -Force
Copy-Item (Join-Path $Src "config.h")  $Work -Force
# secrets.h 는 .gitignore 라 저장소에 없다. 없으면 컴파일이 #error 로 죽으므로 여기서 안내한다.
if (Test-Path (Join-Path $Src "secrets.h")) { Copy-Item (Join-Path $Src "secrets.h") $Work -Force }
else { Write-Host "  secrets.h 가 없다. firmware/node/secrets.h.example 을 복사해 만들 것." -ForegroundColor Red; exit 1 }
Write-Host "  $Src  ->  $Work"

Write-Host "=== [2/4] 컴파일 ===" -ForegroundColor Cyan
& $Cli compile --fqbn $Fqbn $Work
if ($LASTEXITCODE -ne 0) { Write-Host "컴파일 실패. firmware/BUILD.md 의 라이브러리 버전 확인." -ForegroundColor Red; exit 1 }

if (-not $Upload) { Write-Host "`n컴파일만 수행했습니다. 업로드하려면 -Upload 를 붙이세요." -ForegroundColor Yellow; exit 0 }

Write-Host "=== [3/4] 포트 확인 ===" -ForegroundColor Cyan
if (-not $Port) {
    $found = [System.IO.Ports.SerialPort]::GetPortNames()
    if (-not $found) {
        Write-Host "COM 포트를 찾을 수 없습니다. 보드가 USB로 연결돼 있는지 확인하세요." -ForegroundColor Red
        Write-Host "(장치관리자에 CP210x 항목만 있고 포트 열거가 비어 있으면 = 물리적으로 빠진 상태)" -ForegroundColor Red
        exit 1
    }
    $Port = $found[0]
}
Write-Host "  포트: $Port"

Write-Host "=== [4/4] 업로드 ===" -ForegroundColor Cyan
& $Cli upload -p $Port --fqbn $Fqbn $Work
if ($LASTEXITCODE -ne 0) { Write-Host "업로드 실패." -ForegroundColor Red; exit 1 }
Write-Host "업로드 완료." -ForegroundColor Green

if ($Capture -le 0) { exit 0 }

# ---- 시리얼 캡처 ----
# ★ DTR/RTS를 절대 건드리지 말 것. 토글하면 ESP32가 다운로드 모드로 들어가
#   버퍼에 남은 낡은 데이터만 계속 나온다(2026-08-03에 실제로 겪은 오진).
$stamp   = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir  = Join-Path $Repo "results\hw"
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
$outFile = Join-Path $outDir "node_${Label}_${stamp}.jsonl"

Write-Host "`n=== 시리얼 캡처 ${Capture}초 -> $outFile ===" -ForegroundColor Cyan
$sp = New-Object System.IO.Ports.SerialPort $Port, 115200, "None", 8, "One"
$sp.ReadTimeout = 500
$sp.Open()
$deadline = (Get-Date).AddSeconds($Capture)
$lines = New-Object System.Collections.Generic.List[string]
while ((Get-Date) -lt $deadline) {
    try {
        $line = $sp.ReadLine().TrimEnd()
        if ($line) { $lines.Add($line); Write-Host $line }
    } catch [TimeoutException] { }
}
$sp.Close()
$lines | Out-File -FilePath $outFile -Encoding utf8
Write-Host "`n캡처 완료: $($lines.Count) 줄 -> $outFile" -ForegroundColor Green
Write-Host "확인할 것: MODE 배너 / ST 전이 ALIVE->DYING->DEAD / LG 1회 / 이후 HB 중단 / 모든 줄에 fake 필드" -ForegroundColor Yellow
