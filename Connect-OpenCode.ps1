param([Parameter(ValueFromRemainingArguments=$true)][string[]]$OpenCodeArguments)
$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
$exe = Join-Path $env:APPDATA 'npm\node_modules\@opencode\cli\bin\opencode.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "Installed OpenCode executable not found: $exe" }
. (Join-Path $PSScriptRoot 'OpenCode-ServerAuth.ps1')
$env:OPENCODE_SERVER_PASSWORD = Get-OpenCodeServerPassword
$env:PATH = "$env:APPDATA\npm;$env:PATH"
$env:TERM = 'xterm-256color'
& $exe --server http://127.0.0.1:4096 @OpenCodeArguments
exit $LASTEXITCODE
