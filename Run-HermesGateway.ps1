$ErrorActionPreference = 'Stop'
$env:PATH = "$env:LOCALAPPDATA\hermes\bin;$env:USERPROFILE\.local\bin;$env:PATH"
$env:TERM = 'xterm-256color'
Set-Location 'L:\LocalCoder\workspace'
$logRoot = 'L:\LocalCoder\receipts\hermes_gateway'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
while ($true) {
    if (Test-Path 'L:\LocalCoder\HERMES_STOP') { exit 0 }
    $stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
    & "$env:USERPROFILE\.local\bin\ori.exe" hermes --model 'nvidia/nemotron-3-ultra-550b-a55b:free' -- gateway run --external-supervisor *>> "$logRoot\gateway-$stamp.log"
    $code = $LASTEXITCODE
    Add-Content -LiteralPath "$logRoot\supervisor.log" -Value "$(Get-Date -Format o) gateway exited: $code; restarting in sixty seconds"
    Start-Sleep -Seconds 60
}
