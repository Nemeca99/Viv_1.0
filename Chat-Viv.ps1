<#
.SYNOPSIS
    Starts an Interactive Chat Session with AIOS Viv.

.DESCRIPTION
    Opens a live conversational CLI session directly grounded in Viv's
    101,345+ in-memory neural network without any external LLM dependencies.

.PARAMETER Voice
    Dispatches spoken utterances to Viv's local TTS voice model if available.
#>
[CmdletBinding()]
param(
    [switch]$Voice
)

$ErrorActionPreference = 'Stop'
$Python = 'L:\.venv\Scripts\python.exe'
$Script = 'L:\LocalCoder\workspace\chat_viv.py'

if ($Voice) {
    & $Python $Script --voice
} else {
    & $Python $Script
}
exit $LASTEXITCODE
