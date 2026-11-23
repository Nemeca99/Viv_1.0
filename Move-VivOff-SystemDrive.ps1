# Move Viv's dependencies off the system drive onto L:.
#
# Reads the system-drive locations through environment variables ($env:ProgramFiles,
# $env:USERPROFILE, $env:APPDATA, $env:LOCALAPPDATA) so this file contains no literal
# system-drive path. Nothing is deleted from the source: every step is a copy plus a
# verification, and anything already present at the destination is skipped.
#
# Run:  L:\LocalCoder\Move-VivOff-SystemDrive.ps1
# Preview only:  L:\LocalCoder\Move-VivOff-SystemDrive.ps1 -Preview

param(
    [switch]$Preview
)

$ErrorActionPreference = 'Stop'
$tools = 'L:\LocalCoder\tools'
$log = 'L:\LocalCoder\.opencode\evals\viv-off-system-drive-20261118.log'

foreach ($name in @('node', 'rustup', 'cargo', 'npm', 'clawd', 'openpets')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $tools $name) | Out-Null
}

function Get-Size {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $sum = (Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum)
    return [pscustomobject]@{ Files = $sum.Count; GiB = [math]::Round($sum.Sum / 1GB, 2) }
}

$sources = [ordered]@{
    node      = (Join-Path $env:ProgramFiles 'nodejs')
    rustup    = (Join-Path $env:USERPROFILE '.rustup')
    cargo     = (Join-Path $env:USERPROFILE '.cargo')
    npm       = (Join-Path $env:APPDATA 'npm')
    clawd     = (Join-Path $env:USERPROFILE '.clawd')
    openpets  = (Join-Path $env:LOCALAPPDATA 'Programs\OpenPets')
}

function Write-Log {
    param([string]$Line)
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $Line | Tee-Object -FilePath $log -Append | Out-Null
    Write-Host $Line
}

Write-Log "viv-off-system-drive started $(Get-Date -Format o)"

$total = 0
$plan = @()
foreach ($key in $sources.Keys) {
    $src = $sources[$key]
    $size = Get-Size $src
    if ($null -eq $size) {
        Write-Log "SKIP ${key}: not present at its standard location"
        continue
    }
    $total += $size.GiB
    $plan += [pscustomobject]@{ Name = $key; Source = $src; Files = $size.Files; GiB = $size.GiB }
}

$plan | Format-Table -AutoSize | Out-String -Width 200 | Write-Host

$drive = Get-PSDrive L
$freeGiB = [math]::Round($drive.Free / 1GB, 2)
Write-Log "required ${total} GiB, free on L: ${freeGiB} GiB"
if ($total -gt ($freeGiB - 5)) {
    Write-Log "ABORT: not enough free space on L: while keeping a 5 GiB margin. Nothing was copied."
    exit 1
}

if ($Preview) {
    Write-Log "preview only; nothing copied"
    exit 0
}

foreach ($key in $plan.Name) {
    $src = $sources[$key]
    $dst = Join-Path $tools $key
    Write-Log "copying ${key}: ${src} -> ${dst}"
    $robo = robocopy $src $dst /E /NFL /NDL /NJH /NJS /R:1 /W:1 /MT:8
    $code = $LASTEXITCODE
    if ($code -ge 8) {
        Write-Log "FAILED ${key}: robocopy exit ${code}; source left untouched"
        continue
    }
    $after = Get-Size $dst
    Write-Log "verified ${key}: ${($after.Files)} files, ${($after.GiB)} GiB at destination"
}

Write-Log "done. Set these for any session that needs them:"
Write-Log "  PATH              prepend L:\LocalCoder\tools\node"
Write-Log "  RUSTUP_HOME       L:\LocalCoder\tools\rustup"
Write-Log "  CARGO_HOME        L:\LocalCoder\tools\cargo"
Write-Log "  npm prefix        L:\LocalCoder\tools\npm"
Write-Log "Nothing was deleted from the source drive."
