$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
Write-Host 'VISIBLE ONE-SHOT: authenticated client to shared loopback OpenCode server; read-only status tool.' -ForegroundColor Cyan
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "server-status-probe-$stamp.jsonl"
$prompt = 'Use the localcoder_status tool and report the project root and whether both memory files are present.'
$runOutput = @()
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'L:\LocalCoder\Connect-OpenCode.ps1' run --agent build --format json $prompt 2>&1 | Tee-Object -Variable runOutput
$code = $LASTEXITCODE
$records = foreach ($item in $runOutput) {
    $line = [string]$item
    try { $null = ConvertFrom-Json -InputObject $line -ErrorAction Stop; $line }
    catch { ConvertTo-Json -InputObject @{ type = 'console'; text = $line } -Compress }
}
[System.IO.File]::WriteAllLines($outputPath, [string[]]$records, [System.Text.UTF8Encoding]::new($false))
if ($code -ne 0) { throw "OpenCode client exited $code. Transcript: $outputPath" }
$parsed = @($records | ForEach-Object { $_ | ConvertFrom-Json -ErrorAction Stop })
$calls = @($parsed | Where-Object { $_.type -eq 'tool_use' -and $_.part.tool -eq 'localcoder_status' -and $_.part.state.status -eq 'completed' })
if ($calls.Count -ne 1) { throw "Expected one successful localcoder_status call; found $($calls.Count). Transcript: $outputPath" }
$status = $calls[0].part.state.output | ConvertFrom-Json
if ($status.project_root -ne 'L:\LocalCoder' -or -not $status.memory_files.'MEMORY.md' -or -not $status.memory_files.'USER.md') {
    throw "Shared-server status output failed checks. Transcript: $outputPath"
}
Write-Host "PASS: authenticated shared server routed localcoder_status successfully. Transcript: $outputPath" -ForegroundColor Green
