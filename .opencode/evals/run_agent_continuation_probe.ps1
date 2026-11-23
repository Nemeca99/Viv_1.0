$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
$sessionId = 'ses_e27ee639dffe5g53MApqcFMTe4'
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "agent-continuation-probe-$stamp.jsonl"
$prompt = 'Continue the bounded pipeline diagnostic in this session. Call shell tool. The exact tool arguments are {"command":"Write-Output CONTINUATION_TOOL_CALL_PASS"}. Invoke the tool; do not print the arguments or the expected output. Do not edit files.'
$runOutput = @()
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'L:\LocalCoder\Connect-OpenCode.ps1' run --session $sessionId --agent build --format json $prompt 2>&1 | Tee-Object -Variable runOutput
$code = $LASTEXITCODE
$records = foreach ($item in $runOutput) {
    $line = [string]$item
    try { $null = ConvertFrom-Json -InputObject $line -ErrorAction Stop; $line }
    catch { ConvertTo-Json -InputObject @{ type = 'console'; text = $line } -Compress }
}
[System.IO.File]::WriteAllLines($outputPath, [string[]]$records, [System.Text.UTF8Encoding]::new($false))
if ($code -ne 0) { throw "OpenCode client exited $code. Transcript: $outputPath" }
$parsed = @($records | ForEach-Object { $_ | ConvertFrom-Json -ErrorAction Stop })
$shell = @($parsed | Where-Object { $_.type -eq 'tool_use' -and $_.part.tool -eq 'shell' -and $_.part.state.status -eq 'completed' })
if ($shell.Count -ne 1 -or [string]$shell[0].part.state.output -notmatch 'CONTINUATION_TOOL_CALL_PASS') {
    throw "Expected one completed shell call with the marker. Transcript: $outputPath"
}
Write-Host "PASS: model resumed the prior session and completed the bounded shell step. Transcript: $outputPath" -ForegroundColor Green
