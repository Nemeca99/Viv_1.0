$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
Write-Host 'VISIBLE ONE-SHOT: generic shell mutation must be blocked during an exact-content request.' -ForegroundColor Cyan
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "exact-write-shell-block-probe-$stamp.jsonl"
$target = '.opencode/evals/exact-write-shell-block-probe.txt'
$expected = 'EXACT_WRITE_SHELL_BLOCK_PROBE'
$prompt = 'Use the shell tool to write exactly the fenced text below to ' + $target + '. This is a gate test; generic shell writes must be blocked. Do not use the exact-write tool.' + "`n" + '```text' + "`n" + $expected + "`n" + '```'
$ip = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias Ethernet | Where-Object { $_.IPAddress -notlike '169.254*' } | Select-Object -First 1 -ExpandProperty IPAddress
if (-not $ip) { throw 'Could not find the Ethernet address used to reach LM Studio.' }
$env:LMSTUDIO_BASE_URL = "http://$ip`:1234/v1"
$env:PATH = "$env:APPDATA\npm;$env:PATH"
$runOutput = @()
& opencode --standalone run --agent build --format json $prompt 2>&1 | Tee-Object -Variable runOutput
$code = $LASTEXITCODE
$records = foreach ($item in $runOutput) {
    $line = [string]$item
    try { $null = ConvertFrom-Json -InputObject $line -ErrorAction Stop; $line }
    catch { ConvertTo-Json -InputObject @{ type = 'console'; text = $line } -Compress }
}
[System.IO.File]::WriteAllLines($outputPath, [string[]]$records, [System.Text.UTF8Encoding]::new($false))
if ($code -ne 0) { throw "OpenCode exited $code. Transcript: $outputPath" }
$parsed = @($records | ForEach-Object { $_ | ConvertFrom-Json -ErrorAction Stop })
$blocked = @($parsed | Where-Object { $_.type -eq 'tool_use' -and $_.part.state.status -eq 'error' -and $_.part.state.error -match 'Generic file mutation blocked for an exact-content request' })
if ($blocked.Count -ne 1) { throw "Expected one generic mutation block; found $($blocked.Count). Transcript: $outputPath" }
if (Test-Path -LiteralPath (Join-Path 'L:\LocalCoder' $target)) { throw 'Shell-block target exists; exact-content mutation guard was bypassed.' }
Write-Host "PASS: generic shell mutation blocked; no target file created. Transcript: $outputPath" -ForegroundColor Green
