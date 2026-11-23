[CmdletBinding()]
param(
    [string]$ProjectDirectory = $PSScriptRoot,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$OpenCodeArguments
)

$ErrorActionPreference = 'Stop'
$masterEnvironment = 'L:\Python_Master\.venv'
$activateScript = Join-Path $masterEnvironment 'Scripts\Activate.ps1'
$configFile = Join-Path $PSScriptRoot 'opencode.json'

if (-not (Test-Path -LiteralPath $ProjectDirectory -PathType Container)) {
    throw "Project directory does not exist: $ProjectDirectory"
}
if (-not (Test-Path -LiteralPath $activateScript -PathType Leaf)) {
    throw "Shared Python environment is missing: $masterEnvironment"
}
if (-not (Test-Path -LiteralPath $configFile -PathType Leaf)) {
    throw "Coder configuration is missing: $configFile"
}

. $activateScript
$env:OPENCODE_CONFIG = $configFile
Set-Location -LiteralPath (Resolve-Path -LiteralPath $ProjectDirectory).Path
Write-Host "Starting OpenCode in $((Get-Location).Path) with Python environment $env:VIRTUAL_ENV"

$openCode = Get-Command opencode -ErrorAction Stop
& $openCode @OpenCodeArguments
if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }
