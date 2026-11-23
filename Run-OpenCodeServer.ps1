$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
$exe = Join-Path $env:APPDATA 'npm\node_modules\@opencode\cli\bin\opencode.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "Installed OpenCode executable not found: $exe" }

$ip = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias Ethernet |
    Where-Object { $_.IPAddress -notlike '169.254*' } |
    Select-Object -First 1 -ExpandProperty IPAddress
if (-not $ip) { throw 'Could not find the Ethernet address used to reach LM Studio.' }
$env:LMSTUDIO_BASE_URL = "http://$ip`:1234/v1"
$config = Get-Content -LiteralPath 'L:\LocalCoder\opencode.json' -Raw | ConvertFrom-Json
$modelId = ([string]$config.model) -replace '^[^/]+/', ''
$apiRoot = $env:LMSTUDIO_BASE_URL -replace '/v1/?$', ''
$models = Invoke-RestMethod -Uri "$apiRoot/api/v0/models" -TimeoutSec 5
$model = $models.data | Where-Object id -eq $modelId | Select-Object -First 1
if (-not $model) { throw "LM Studio did not return configured model '$modelId'. No model was loaded or changed." }
if ([string]$model.state -ne 'loaded') {
    throw "Configured model '$modelId' is not loaded (state='$($model.state)'). Load it in LM Studio, then start this visible server again."
}

. (Join-Path $PSScriptRoot 'OpenCode-ServerAuth.ps1')
New-OpenCodeServerPassword
$env:OPENCODE_SERVER_PASSWORD = Get-OpenCodeServerPassword
$env:PATH = "$env:APPDATA\npm;$env:PATH"
$env:TERM = 'xterm-256color'
Write-Host "OpenCode server ready for clients at http://127.0.0.1:4096" -ForegroundColor Green
Write-Host "Model: $modelId (state=$($model.state), loaded_context_length=$($model.loaded_context_length))"
Write-Host 'Bound to loopback only. This foreground window shows server activity; close it to stop the server.' -ForegroundColor Cyan
Write-Host 'No model was loaded or unloaded. No scheduled task or background worker was started.'
try {
    $priorErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $exe serve --hostname 127.0.0.1 --port 4096
    $serverExitCode = $LASTEXITCODE
    $ErrorActionPreference = $priorErrorAction
    exit $serverExitCode
} finally {
    Remove-Item Env:\OPENCODE_SERVER_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:\LMSTUDIO_BASE_URL -ErrorAction SilentlyContinue
}
