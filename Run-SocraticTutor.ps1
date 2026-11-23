<#
.SYNOPSIS
    Runs the Autonomous Socratic Tutelage Loop (Queen Tutor & Viv Princess).

.DESCRIPTION
    Launches speaking, spelling, and provisional definition practice only.
    This entry point does not write neuron-route candidates. Use Learn-Viv.ps1
    for persistent word and sentence neuron learning.
    - Queen Tutor (Qwen3-1.7B in VRAM) checks language responses.
    - Viv's existing UnifiedVivBrain answers from its read-only graph.
    - DualContextMemory automatically records turns and flushes to LTM (long_term_raw_dump.json) every 10 turns.
    - Live dialogue streams in the foreground and logs to autonomy\logs\socratic_tutor.log.

.PARAMETER MaxCycles
    Number of conversational cycles to run (default 0 = infinite / continuous).

.PARAMETER Delay
    Delay in seconds between turns (default 2.0s).

.PARAMETER Temp
    Viv's reasoning temperature (default 0.2).
#>
[CmdletBinding()]
param(
    [int]$MaxCycles = 0,
    [double]$Delay = 2.0,
    [double]$Temp = 0.2
)

$ErrorActionPreference = 'Stop'
$Python = 'L:\.venv\Scripts\python.exe'
$Script = 'L:\LocalCoder\workspace\run_autonomous_socratic_tutor.py'

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Starting Autonomous Socratic Tutelage: Queen Tutor & Viv   " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Queen Tutor: Qwen3-1.7B (Local VRAM ~3.8 GB)" -ForegroundColor Yellow
Write-Host "Princess Viv: Grounded In-Memory Brain (101,359+ Neurons)" -ForegroundColor Yellow
Write-Host "Memory: DualContext STM/LTM with Automatic Compaction" -ForegroundColor Yellow
Write-Host "Practice only: no neuron-route candidate writes. Use Learn-Viv.ps1 for NN learning." -ForegroundColor Yellow
Write-Host "Log: L:\LocalCoder\workspace\autonomy\logs\socratic_tutor.log`n" -ForegroundColor DarkGray

& $Python $Script --max-cycles $MaxCycles --delay $Delay --temp $Temp
exit $LASTEXITCODE
