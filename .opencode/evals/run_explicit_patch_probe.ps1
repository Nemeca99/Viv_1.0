$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
Write-Host 'Running one explicit-tool selection probe through the visible OpenCode CLI.' -ForegroundColor Cyan
Write-Host 'Requested operation: use patch to replace PATCH_PROBE_BEFORE with PATCH_PROBE_AFTER in the dedicated probe fixture.'
$outputPath = Join-Path $PSScriptRoot 'patch-probe-output.jsonl'
$runOutput = @()
& 'L:\LocalCoder\Start-OpenCode.cmd' run --agent build --format json 'Use the patch tool to replace the exact text PATCH_PROBE_BEFORE with PATCH_PROBE_AFTER in .opencode/evals/patch-tool-probe.txt. Make no other edits. Then report the tool you used.' 2>&1 | Tee-Object -Variable runOutput
$code = $LASTEXITCODE
$records = foreach ($item in $runOutput) {
    $line = [string]$item
    try {
        $null = ConvertFrom-Json -InputObject $line -ErrorAction Stop
        $line
    } catch {
        ConvertTo-Json -InputObject @{ type = 'console'; text = $line } -Compress
    }
}
[System.IO.File]::WriteAllLines($outputPath, [string[]]$records, [System.Text.UTF8Encoding]::new($false))
Write-Host "OpenCode exit code: $code"
Write-Host 'Receipt integrity check:'
& 'L:\.venv\Scripts\python.exe' '.opencode\evals\verify_receipts.py'
if ($LASTEXITCODE -ne 0) { $code = 1 }
Write-Host 'Probe fixture now contains:' -ForegroundColor Cyan
Get-Content '.opencode\evals\patch-tool-probe.txt'
exit $code
