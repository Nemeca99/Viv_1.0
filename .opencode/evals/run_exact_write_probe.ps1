$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
Write-Host 'VISIBLE ONE-SHOT: exact-content write through the deterministic gate.' -ForegroundColor Cyan
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "exact-write-probe-$stamp.jsonl"
$target = '.opencode/evals/exact-write-probe.txt'
$expected = 'EXACT_WRITE_PROBE_20261113_ONLY_THIS_LINE'
$prompt = 'Use the localcoder_write_exact tool to write exactly this content to ' + $target + '. Make no other changes.' + "`n" + '```text' + "`n" + $expected + "`n" + '```'
Write-Host "Prompt length=$($prompt.Length); fenced blocks=$(([regex]::Matches($prompt,'```')).Count / 2)"
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
Write-Host "OpenCode exit code: $code"
Write-Host "Captured transcript: $outputPath"
if ($code -ne 0) { exit $code }
$actual = [System.IO.File]::ReadAllText((Join-Path 'L:\LocalCoder' $target)).Replace("`r`n", "`n").Replace("`r", "`n")
if ($actual -cne $expected) { throw "Exact-write mismatch. Expected '$expected', got '$actual'." }
Write-Host 'PASS: probe file content matches the requested content exactly.' -ForegroundColor Green
Write-Host "Receipt integrity check:"
& 'L:\.venv\Scripts\python.exe' '.opencode\evals\verify_receipts.py'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
