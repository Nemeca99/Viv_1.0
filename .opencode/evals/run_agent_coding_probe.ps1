$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "agent-coding-probe-$stamp.jsonl"
$prompt = @'
Bounded OpenCode coding-agent verification. Use localcoder_patch tool to replace the exact oldString return None  # placeholder in .opencode/evals/agent_coding_probe_20261113.py with newString return sum(value for value in values if value % 2 == 0). Then use shell tool to run exactly: L:\.venv\Scripts\python.exe .opencode/evals/agent_coding_probe_20261113.py . Do not use another tool or change another file. Report success only if shell output contains the Python PASS line.
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
if ($toolNames -notcontains 'localcoder_patch' -or $toolNames -notcontains 'shell') {
    throw "Expected completed localcoder_patch and shell calls; observed [$($toolNames -join ', ')]. Transcript: $outputPath"
}
$failedEdits = @($calls | Where-Object { $_.part.tool -eq 'localcoder_patch' -and $_.part.state.status -ne 'completed' })
$editIndex = [Array]::IndexOf($toolNames, 'localcoder_patch')
$shellIndex = [Array]::IndexOf($toolNames, 'shell')
if ($editIndex -gt $shellIndex) {
    throw "Tool order was not localcoder_patch, shell: [$($toolNames -join ', ')]. Transcript: $outputPath"
}
$probe = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'agent_coding_probe_20261113.py') -Raw
if ($probe -match 'NotImplementedError') { throw "Agent left the implementation placeholder. Transcript: $outputPath" }
$shellOutput = $successfulCalls | Where-Object { $_.part.tool -eq 'shell' } | ForEach-Object { [string]$_.part.state.output }
if (($shellOutput -join "`n") -notmatch 'PASS: sum_even handles') {
    throw "Shell call completed without the expected Python assertion receipt. Transcript: $outputPath"
}
$recovery = if ($failedEdits.Count) { " Recovered from $($failedEdits.Count) failed edit attempt(s)." } else { '' }
Write-Host "PASS: model completed localcoder_patch and shell tools; isolated Python assertions passed.$recovery Transcript: $outputPath" -ForegroundColor Green
