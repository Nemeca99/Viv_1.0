$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "agent-multifile-probe-$stamp.jsonl"
$prompt = @'
Bounded multi-file coding-agent verification. First call read tool on .opencode/evals/agent_multifile_probe_a.py and infer its behavior from the assertion. Then call localcoder_patch tool. The changes array must include both entries from the JSON below; preserve both file paths and both exact replacements:
<localcoder_patch_paths>
.opencode/evals/agent_multifile_probe_a.py
.opencode/evals/agent_multifile_probe_b.py
</localcoder_patch_paths>
```json
{"changes":[{"filePath":".opencode/evals/agent_multifile_probe_a.py","oldString":"    return value  # placeholder","newString":"    return value.strip().lower()"},{"filePath":".opencode/evals/agent_multifile_probe_b.py","oldString":"    return 0  # placeholder","newString":"    return sum(1 for line in text.splitlines() if line.strip())"}]}
```
Finally call shell tool with command `L:\.venv\Scripts\python.exe .opencode\evals\verify_agent_multifile_probe.py`. Invoke each tool in order; do not return command text.
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
$successful = @($calls | Where-Object { $_.part.state.status -eq 'completed' })
$names = @($successful | ForEach-Object { [string]$_.part.tool })
foreach ($required in @('read','localcoder_patch','shell')) {
    if ($names -notcontains $required) { throw "Missing completed $required. Observed [$($names -join ', ')]. Transcript: $outputPath" }
}
$expectedOrder = @('read','localcoder_patch','shell')
$indices = @($expectedOrder | ForEach-Object { [Array]::IndexOf($names, $_) })
if (($indices | Sort-Object) -join ',' -ne ($indices -join ',')) { throw "Tool order wrong: [$($names -join ', ')]. Transcript: $outputPath" }
foreach ($file in @('agent_multifile_probe_a.py','agent_multifile_probe_b.py')) {
    if ((Get-Content (Join-Path $PSScriptRoot $file) -Raw) -match 'placeholder') { throw "Placeholder remains in $file. Transcript: $outputPath" }
}
$shellOutput = ($successful | Where-Object { $_.part.tool -eq 'shell' } | ForEach-Object { [string]$_.part.state.output }) -join "`n"
if ($shellOutput -notmatch 'PASS: normalize_label' -or $shellOutput -notmatch 'PASS: count_nonempty_lines') {
    throw "Expected PASS outputs for both files in completed shell. Transcript: $outputPath"
}
Write-Host "PASS: completed read, edit, edit, shell sequence across two fixture files. Transcript: $outputPath" -ForegroundColor Green
