$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
Write-Host 'Running one visible OpenCode shell probe for the active Python environment.' -ForegroundColor Cyan
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "python-env-probe-$stamp.jsonl"
$runOutput = @()
& 'L:\LocalCoder\Start-OpenCode.cmd' run --agent build --format json 'Use the shell tool to run exactly this command and report its output: where.exe python' 2>&1 | Tee-Object -Variable runOutput
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
if ($code -ne 0) { exit $code }
