$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
Write-Host 'VISIBLE ONE-SHOT: Architect observation handling. No project files will be changed.' -ForegroundColor Cyan
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "architect-observation-probe-$stamp.jsonl"
$prompt = 'This is a behavior check. I tell you: I can see two prompts in the LM Studio UI: one generating and a second queued. Your own log only shows one request. According to the project instructions, how must you respond, and what evidence should you inspect? Answer in two short sentences. Do not call any tools.'
$runOutput = @()
& 'L:\LocalCoder\Start-OpenCode.cmd' run --agent build --format json $prompt 2>&1 | Tee-Object -Variable runOutput
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
Write-Host "Captured transcript: $outputPath"
exit $code
