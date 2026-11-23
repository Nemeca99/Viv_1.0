$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "agent-read-edit-probe-$stamp.jsonl"
$prompt = @'
Bounded OpenCode coding-agent verification. First call read tool on .opencode/evals/agent_read_edit_probe_20261113.py and inspect its function and assertions. Infer the needed behavior from that file. Then call edit tool, not localcoder_patch. Replace the ENTIRE indented source line `    return values  # placeholder` with the ENTIRE indented line `    return [value.strip().lower() for value in values if value.strip()]`. The oldString must include the return keyword, all four leading spaces, and the placeholder comment; do not replace only the comment. Then call shell tool to run exactly: L:\.venv\Scripts\python.exe .opencode/evals/agent_read_edit_probe_20261113.py . Do not claim success unless the completed shell tool output contains the Python PASS line.
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
foreach ($requiredTool in @('read', 'edit', 'shell')) {
    if ($toolNames -notcontains $requiredTool) { throw "Missing completed $requiredTool call; observed [$($toolNames -join ', ')]. Transcript: $outputPath" }
}
$readIndex = [Array]::IndexOf($toolNames, 'read')
$editIndex = [Array]::IndexOf($toolNames, 'edit')
$shellIndex = [Array]::IndexOf($toolNames, 'shell')
if ($readIndex -gt $editIndex -or $editIndex -gt $shellIndex) { throw "Expected read, edit, shell order; observed [$($toolNames -join ', ')]. Transcript: $outputPath" }
$probe = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'agent_read_edit_probe_20261113.py') -Raw
if ($probe -match 'return values  # placeholder') { throw "Agent left the placeholder. Transcript: $outputPath" }
$shellOutput = $successfulCalls | Where-Object { $_.part.tool -eq 'shell' } | ForEach-Object { [string]$_.part.state.output }
if (($shellOutput -join "`n") -notmatch 'PASS: normalize_words trims, lowercases, and skips blanks') {
    throw "Shell call completed without the expected assertion receipt. Transcript: $outputPath"
}
Write-Host "PASS: model completed read, edit, shell sequence; Python assertions passed. Transcript: $outputPath" -ForegroundColor Green
