<#
.SYNOPSIS
    Runs the Autonomous Dual-Substrate Cognitive Engine in the Foreground.

.DESCRIPTION
    Launches Viv's continuous cognitive loop where:
    - GPU (RTX 3060 Ti VRAM) subconsciously explores associative combinations & proposes paths.
    - CPU (System RAM) executes solidified deterministic paths and gates proposals with UML !0 logic.
    - Formatted telemetry streams to console and is persisted in autonomy\logs\autonomous_daemon.log.

.PARAMETER MaxCycles
    Number of cycles to run (default 0 = infinite / run continuously).

.PARAMETER Delay
    Delay in seconds between cycles (default 0.75s).
#>
[CmdletBinding()]
param(
    [int]$MaxCycles = 0,
    [double]$Delay = 0.75
)

$ErrorActionPreference = 'Stop'
$Python = 'L:\.venv\Scripts\python.exe'
$Script = 'L:\LocalCoder\workspace\run_autonomous_viv_dual_substrate.py'

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Starting AIOS Viv Autonomous Cognitive Loop in Foreground  " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "GPU: Subconscious Associative Exploration" -ForegroundColor Yellow
Write-Host "CPU: Deterministic Solidified Paths & UML !0 Arbiter" -ForegroundColor Yellow
Write-Host "Log: L:\LocalCoder\workspace\autonomy\logs\autonomous_daemon.log`n" -ForegroundColor DarkGray

& $Python $Script --max-cycles $MaxCycles --delay $Delay
exit $LASTEXITCODE
