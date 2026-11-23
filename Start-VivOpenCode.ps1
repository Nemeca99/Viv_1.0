$ErrorActionPreference = 'Stop'

# OpenCode Viv launcher.
#
# Viv's global roots live on L: under her own territory. OpenCode resolves its
# data, state, config, cache and temp directories from the XDG variables below,
# so setting them here keeps sessions, credentials, logs and shell captures
# inside L: instead of the user profile. Without this the host falls back to the
# system drive by default.
$vivRoot = 'L:\LocalCoder\viv'
$forkRoot = 'L:\LocalCoder\tools\opencode-viv'
$bun = 'L:\LocalCoder\tools\bun\bun-windows-x64\bun.exe'

foreach ($name in @('data', 'state', 'config', 'cache', 'bin')) {
    $path = Join-Path $vivRoot $name
    if (-not (Test-Path -LiteralPath $path)) {
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }
}

$env:XDG_DATA_HOME   = Join-Path $vivRoot 'data'
$env:XDG_STATE_HOME  = Join-Path $vivRoot 'state'
$env:XDG_CONFIG_HOME = Join-Path $vivRoot 'config'
$env:XDG_CACHE_HOME  = Join-Path $vivRoot 'cache'

# Local tool roots on L:. These exist only after Move-VivOff-SystemDrive.ps1 has run,
# so each is guarded and the launcher behaves identically before and after the move.
# Without these, node, rustup and cargo resolve to the system drive.
$nodeRoot = 'L:\LocalCoder\tools\node'
if (Test-Path -LiteralPath $nodeRoot) {
    $env:PATH = $nodeRoot + ';' + $env:PATH
}
$rustupRoot = 'L:\LocalCoder\tools\rustup'
if (Test-Path -LiteralPath $rustupRoot) {
    $env:RUSTUP_HOME = $rustupRoot
}
$cargoRoot = 'L:\LocalCoder\tools\cargo'
if (Test-Path -LiteralPath $cargoRoot) {
    $env:CARGO_HOME = $cargoRoot
    $env:PATH = (Join-Path $cargoRoot 'bin') + ';' + $env:PATH
}
$npmRoot = 'L:\LocalCoder\tools\npm'
if (Test-Path -LiteralPath $npmRoot) {
    $env:PATH = $npmRoot + ';' + $env:PATH
}

# Prefer an explicit override, then a compiled Viv, then her own source, and
# only fall back to the installed host if the fork is unavailable.
$vivExe = if ($env:VIV_BINARY) { $env:VIV_BINARY } else { Join-Path $vivRoot 'bin\viv.exe' }
$sourceEntry = Join-Path $forkRoot 'packages\cli\src\index.ts'

Push-Location -LiteralPath 'L:\LocalCoder'
try {
    if (Test-Path -LiteralPath $vivExe) {
        & $vivExe 'L:\LocalCoder' @args
    }
    elseif ((Test-Path -LiteralPath $bun) -and (Test-Path -LiteralPath $sourceEntry)) {
        & $bun run --cwd (Join-Path $forkRoot 'packages\cli') src/index.ts 'L:\LocalCoder' @args
    }
    else {
        & opencode 'L:\LocalCoder' @args
    }
    $runtimeExit = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $runtimeExit
