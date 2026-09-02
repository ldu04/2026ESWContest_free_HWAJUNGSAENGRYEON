# alert.ps1 — 사용자에게 물리 동작을 요청할 때 소리로 알린다.
#   사용자가 다른 작업 중이라 화면을 안 보고 있는 경우가 많다.
#   【지금 해주세요】를 낼 때마다 이걸 같이 울린다.
param([string]$Say = "지금 해주세요", [int]$Repeat = 2)

for ($r = 0; $r -lt $Repeat; $r++) {
  # 상승 3음 — 시스템 알림음과 구분되도록 일부러 특이한 패턴을 쓴다
  [console]::beep(880, 140)
  [console]::beep(1175, 140)
  [console]::beep(1568, 260)
  Start-Sleep -Milliseconds 220
}
try {
  Add-Type -AssemblyName System.Speech -ErrorAction Stop
  $sp = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $ko = $sp.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'ko*' -and $_.Enabled }
  if ($ko) { $sp.SelectVoice($ko[0].VoiceInfo.Name); $sp.Speak($Say) }
  else     { $sp.Speak("Action needed") }
  $sp.Dispose()
} catch { }
