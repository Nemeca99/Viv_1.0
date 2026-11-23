$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot 'farm_rust')
try {
    cargo build --release --offline
    if ($LASTEXITCODE -ne 0) { throw 'Rust farm build failed' }
} finally { Pop-Location }
