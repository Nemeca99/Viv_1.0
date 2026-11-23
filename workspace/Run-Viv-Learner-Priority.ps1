param(
    [int]$MaxCycles = 0
)

$ErrorActionPreference = "Stop"
$workspace = "L:\LocalCoder\workspace"
$python = "L:\.venv\Scripts\python.exe"
$learnerScript = "$workspace\Run-MultiDaemon-Foreground.ps1"
$chatScript = "$workspace\viv_chat_cli.py"

$existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "multi_daemon_orchestrator\.py" }
if ($existing) {
    Write-Host "Learner already running; no duplicate learner started."
} else {
    $learnerArgs = @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", $learnerScript)
    if ($MaxCycles -gt 0) {
        $learnerArgs += @("-MaxCycles", $MaxCycles)
    }
    $learnerWindow = Start-Process -FilePath "powershell.exe" -ArgumentList $learnerArgs -WorkingDirectory $workspace -WindowStyle Normal -PassThru
    Start-Sleep -Seconds 5
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "multi_daemon_orchestrator\.py" } |
        ForEach-Object {
            try {
                $process = Get-Process -Id $_.ProcessId -ErrorAction Stop
                $process.PriorityClass = "High"
            } catch {
                Write-Host "Learner priority was not changed for PID $($_.ProcessId): $($_.Exception.Message)"
            }
        }
    Write-Host "Learner window started with priority."
}

$chatCommand = '$env:VIV_LEARNER_PRIORITY="1"; $Host.UI.RawUI.WindowTitle="Viv Chat - Learner Priority"; & "' + $python + '" -u "' + $chatScript + '"'
$chatWindow = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $chatCommand) -WorkingDirectory $workspace -WindowStyle Normal -PassThru
try {
    (Get-Process -Id $chatWindow.Id -ErrorAction Stop).PriorityClass = "BelowNormal"
} catch {
    Write-Host "Chat priority was not changed: $($_.Exception.Message)"
}

Write-Host "Viv learner and learner-priority chat windows are running."
Write-Host "Chat turns wait for the learner's SQLite commit window to clear."
