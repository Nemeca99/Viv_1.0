param([int]$Steps = 10000, [int]$Loops = 1, [ValidateSet('source','learned','linear','transformer')][string]$Engine = 'learned', [ValidateSet('cpu','cuda')][string]$Device = 'cpu', [string]$RunRoot = 'F:\LocalCoder_Archive\INN_live_runs', [switch]$Fresh, [switch]$FromSheet, [switch]$ExperimentalTransformer, [switch]$CompactLog)
$ErrorActionPreference = 'Stop'
if ($Steps -lt 1 -or $Loops -lt 1) { throw 'Steps and Loops must be positive' }
for ($cycle = 1; $cycle -le $Loops; $cycle++) {
    $taskArgs = @((Join-Path $PSScriptRoot 'run.py'), '--steps', $Steps, '--engine', $Engine, '--device', $Device, '--run-root', $RunRoot)
    if ($Fresh -and $cycle -eq 1) { $taskArgs += '--fresh' }
    if ($FromSheet -and $cycle -eq 1) { $taskArgs += '--from-sheet' }
    if ($ExperimentalTransformer) { $taskArgs += '--experimental-transformer' }
    if ($CompactLog) { $taskArgs += '--compact-log' }
    Write-Host "INN cycle $cycle/$Loops"
    & 'L:\.venv\Scripts\python.exe' @taskArgs
    if ($LASTEXITCODE -ne 0) { throw "INN execution failed on cycle $cycle" }
}
