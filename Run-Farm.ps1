[CmdletBinding()]
param(
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
$Python = 'L:\.venv\Scripts\python.exe'
$Autonomy = 'L:\LocalCoder\workspace\viv_autonomy.py'

if ($Status) {
    & $Python $Autonomy status
} else {
    & $Python $Autonomy farm
}
exit $LASTEXITCODE
