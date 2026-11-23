param([string]$Query = 'Architect owns intent and final authority')
$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
Write-Host 'VISIBLE ONE-SHOT: read-only persistent USER.md retrieval.' -ForegroundColor Cyan
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "memory-read-probe-$stamp.jsonl"
$prompt = 'Use the localcoder_memory_read tool. Read USER.md and query ' + $Query + '. Report the exact match and returned hash.'
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
$calls = @($parsed | Where-Object { $_.type -eq 'tool_use' -and $_.part.tool -eq 'localcoder_memory_read' -and $_.part.state.status -eq 'completed' })
if ($calls.Count -ne 1) { throw "Expected one successful localcoder_memory_read call; found $($calls.Count). Transcript: $outputPath" }
Write-Host "PASS: persistent memory read tool completed. Transcript: $outputPath" -ForegroundColor Green
