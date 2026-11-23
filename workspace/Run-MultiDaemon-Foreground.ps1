param([int]$MaxCycles = 0)

$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'L:\LocalCoder\workspace'
$python = 'L:\.venv\Scripts\python.exe'
$program = 'L:\LocalCoder\workspace\autonomy\multi_daemon_orchestrator.py'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log = "L:\LocalCoder\workspace\autonomy\logs\multi_daemon_$stamp.log"
Write-Host "Multi-daemon stdout log: $log"
$ErrorActionPreference = 'Continue'  # Python logging on stderr is output, not a PowerShell terminating error.
if ($MaxCycles -gt 0) {
    & $python -u $program --max-cycles $MaxCycles 2>&1 | Tee-Object -FilePath $log
} else {
    & $python -u $program 2>&1 | Tee-Object -FilePath $log
}
$exitCode = $LASTEXITCODE
"[ORCHESTRATOR EXIT] code=$exitCode" | Tee-Object -FilePath $log -Append
