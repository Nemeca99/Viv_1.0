$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "agent-edit-probe-$stamp.jsonl"
$prompt = @'
Bounded OpenCode coding-agent verification. Use edit tool, not localcoder_patch tool, to replace the exact oldString return None  # placeholder in .opencode/evals/agent_edit_probe_20261113.py with newString return sum(1 for value in values if value.strip()). Then use shell tool to run exactly: L:\.venv\Scripts\python.exe .opencode/evals/agent_edit_probe_20261113.py . Do not claim success unless the shell tool output contains the Python PASS line.
'@
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
$calls = @($parsed | Where-Object { $_.type -eq 'tool_use' })
$successfulCalls = @($calls | Where-Object { $_.part.state.status -eq 'completed' })
$toolNames = @($successfulCalls | ForEach-Object { [string]$_.part.tool })
if ($toolNames -notcontains 'edit' -or $toolNames -notcontains 'shell') {
    throw "Expected completed edit and shell calls; observed [$($toolNames -join ', ')]. Transcript: $outputPath"
}
$editIndex = [Array]::IndexOf($toolNames, 'edit')
$shellIndex = [Array]::IndexOf($toolNames, 'shell')
if ($editIndex -gt $shellIndex) { throw "Tool order was not edit, shell. Transcript: $outputPath" }
$probe = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'agent_edit_probe_20261113.py') -Raw
if ($probe -match 'return None  # placeholder') { throw "Agent did not replace the placeholder. Transcript: $outputPath" }
$shellOutput = $successfulCalls | Where-Object { $_.part.tool -eq 'shell' } | ForEach-Object { [string]$_.part.state.output }
if (($shellOutput -join "`n") -notmatch 'PASS: count_nonempty ignores whitespace-only strings') {
    throw "Shell call completed without expected Python assertion receipt. Transcript: $outputPath"
}
Write-Host "PASS: model completed native edit and shell tools; Python assertions passed. Transcript: $outputPath" -ForegroundColor Green
