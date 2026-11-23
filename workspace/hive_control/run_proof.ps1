param(
    [ValidateSet('fixture', 'live')]
    [string]$MindMode = 'fixture',
    [switch]$InjectParentFault
)

$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$python = Join-Path $root '..\hive_numpy_bridge\.venv\Scripts\python.exe'
$binary = Join-Path $root 'target\debug\hive_control.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "NumPy bridge Python environment is missing: $python"
}

Push-Location $root
try {
    & cargo fmt -- --check
    if ($LASTEXITCODE -ne 0) { throw 'Rust formatting check failed' }
    $env:RUSTFLAGS = '-D warnings'
    & cargo test --offline
    if ($LASTEXITCODE -ne 0) { throw 'Rust tests failed' }
    & cargo build --offline
    if ($LASTEXITCODE -ne 0) { throw 'Rust build failed' }
    & $python -m unittest discover -s .. -p test_hive_template_runtime.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Template tests failed' }
    $runArgs = @($python, $MindMode)
    if ($InjectParentFault) { $runArgs += '--inject-parent-fault' }
    & $binary @runArgs
    if ($LASTEXITCODE -ne 0) { throw 'Integrated Hive proof held; inspect the emitted receipt' }
} finally {
    Pop-Location
}
