param([int]$Steps = 10000, [ValidateSet('transformer','linear')][string]$Engine = 'transformer', [ValidateSet('cpu','cuda')][string]$Device = 'cpu', [switch]$Fresh)
$ErrorActionPreference = 'Stop'
$taskArgs = @((Join-Path $PSScriptRoot 'run.py'), '--steps', $Steps, '--engine', $Engine, '--device', $Device)
if ($Fresh) { $taskArgs += '--fresh' }
& 'L:\.venv\Scripts\python.exe' @taskArgs
if ($LASTEXITCODE -ne 0) { throw 'INN execution failed' }
