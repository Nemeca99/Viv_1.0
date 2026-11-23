$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "agent-batch-reject-probe-$stamp.jsonl"
$fileA = Join-Path $PSScriptRoot 'agent_batch_reject_a.py'
$fileB = Join-Path $PSScriptRoot 'agent_batch_reject_b.py'
$beforeA = (Get-FileHash -LiteralPath $fileA -Algorithm SHA256).Hash
$beforeB = (Get-FileHash -LiteralPath $fileB -Algorithm SHA256).Hash
$prompt = @'
Bounded fail-closed batch patch test. Call localcoder_patch tool exactly once with the JSON changes below. The second oldString is intentionally absent from its file; do not fix it and do not retry after the patch is rejected. The executor must preflight both files and leave both byte-for-byte unchanged.
<localcoder_patch_paths>
.opencode/evals/agent_batch_reject_a.py
.opencode/evals/agent_batch_reject_b.py
</localcoder_patch_paths>
```json
{"changes":[{"filePath":".opencode/evals/agent_batch_reject_a.py","oldString":"PLACEHOLDER_A","newString":"1"},{"filePath":".opencode/evals/agent_batch_reject_b.py","oldString":"MISSING_B","newString":"2"}]}
```
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
$patches = @($parsed | Where-Object { $_.type -eq 'tool_use' -and $_.part.tool -eq 'localcoder_patch' })
if (-not @($patches | Where-Object { $_.part.state.status -eq 'error' -and $_.part.state.error -match 'oldString must match exactly once' -and $_.part.state.error -match 'agent_batch_reject_b\.py' -and $_.part.state.error -match 'no files were changed' }).Count) {
    throw "Expected second-file exact-match preflight rejection with no files changed. Transcript: $outputPath"
}
$afterA = (Get-FileHash -LiteralPath $fileA -Algorithm SHA256).Hash
$afterB = (Get-FileHash -LiteralPath $fileB -Algorithm SHA256).Hash
if ($beforeA -ne $afterA -or $beforeB -ne $afterB) { throw "Batch preflight changed a file. Transcript: $outputPath" }
Write-Host "PASS: invalid second-file change was rejected before either file changed. Transcript: $outputPath" -ForegroundColor Green
