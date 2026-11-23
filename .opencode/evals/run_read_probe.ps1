$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
Write-Host 'VISIBLE ONE-SHOT: read a known project file through OpenCode.' -ForegroundColor Cyan
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "read-probe-$stamp.jsonl"
$prompt = 'Use the read tool to read .opencode/evals/exact-write-probe.txt and report its exact contents.'
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
$calls = @($parsed | Where-Object { $_.type -eq 'tool_use' -and $_.part.tool -eq 'read' -and $_.part.state.status -eq 'completed' })
if ($calls.Count -ne 1) { throw "Expected one successful read tool call; found $($calls.Count). Transcript: $outputPath" }
$answer = ($parsed | Where-Object { $_.type -eq 'text' } | ForEach-Object { $_.part.text }) -join "`n"
if ($answer -notmatch 'EXACT_WRITE_PROBE_20261113_ONLY_THIS_LINE') { throw "Model report did not contain the actual file contents. Transcript: $outputPath" }
Write-Host "PASS: native read tool and grounded report. Transcript: $outputPath" -ForegroundColor Green
