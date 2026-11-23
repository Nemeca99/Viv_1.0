param(
    [int]$MaxCycles = 0
)

$ErrorActionPreference = 'Stop'
$workspace = 'L:\LocalCoder\workspace'
$python = 'L:\.venv\Scripts\python.exe'
$learnerScript = Join-Path $workspace 'Run-MultiDaemon-Foreground.ps1'
$dashboard = 'L:\LocalCoder\dashboard\app.py'

$existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'multi_daemon_orchestrator\.py' }
if ($existing) {
    Write-Host 'Learner already running; dashboard will attach to its heartbeat.'
} else {
    $learnerArgs = @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File', $learnerScript)
    if ($MaxCycles -gt 0) {
        $learnerArgs += @('-MaxCycles', $MaxCycles)
    }
    Start-Process -FilePath 'powershell.exe' -ArgumentList $learnerArgs -WorkingDirectory $workspace -WindowStyle Normal | Out-Null
    Write-Host 'Learner started in a separate foreground window.'
}

$env:PYTHONPATH = $workspace
Set-Location $workspace
& $python -m streamlit run $dashboard --server.port 8501 --server.headless false
exit $LASTEXITCODE
