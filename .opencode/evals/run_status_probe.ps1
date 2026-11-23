$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
Write-Host 'VISIBLE ONE-SHOT: read-only LocalCoder status through the project skill contract.' -ForegroundColor Cyan
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "status-probe-$stamp.jsonl"
$prompt = 'Use the localcoder_status tool and report project_root, memory_files, and OpenCode receipt count.'
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
$calls = @($parsed | Where-Object { $_.type -eq 'tool_use' -and $_.part.tool -eq 'localcoder_status' -and $_.part.state.status -eq 'completed' })
if ($calls.Count -ne 1) { throw "Expected one successful localcoder_status call; found $($calls.Count). Transcript: $outputPath" }
$result = $calls[0].part.state.output | ConvertFrom-Json
if ($result.project_root -ne 'L:\LocalCoder' -or -not $result.memory_files.'MEMORY.md' -or -not $result.memory_files.'USER.md' -or $result.opencode_receipt_count -lt 1) {
    throw "Status output failed expected path/availability checks. Transcript: $outputPath"
}
Write-Host "PASS: read-only status returns project/memory/receipt paths. Transcript: $outputPath" -ForegroundColor Green
