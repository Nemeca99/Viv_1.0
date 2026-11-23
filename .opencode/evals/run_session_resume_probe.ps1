param([Parameter(Mandatory=$true)][string]$SessionId)
$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
Write-Host "VISIBLE ONE-SHOT: resume persisted OpenCode session $SessionId." -ForegroundColor Cyan
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$outputPath = Join-Path $PSScriptRoot "session-resume-probe-$stamp.jsonl"
$prompt = 'Continue this same conversation after the earlier process ended. State the project root you gave in the previous turn.'
$ip = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias Ethernet | Where-Object { $_.IPAddress -notlike '169.254*' } | Select-Object -First 1 -ExpandProperty IPAddress
if (-not $ip) { throw 'Could not find the Ethernet address used to reach LM Studio.' }
$env:LMSTUDIO_BASE_URL = "http://$ip`:1234/v1"
$env:PATH = "$env:APPDATA\npm;$env:PATH"
$exe = Join-Path $env:APPDATA 'npm\node_modules\@opencode\cli\bin\opencode.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "Installed OpenCode executable not found: $exe" }
$runOutput = @()
& $exe --standalone run --session $SessionId --agent build --format json $prompt 2>&1 | Tee-Object -Variable runOutput
$code = $LASTEXITCODE
$records = foreach ($item in $runOutput) {
    $line = [string]$item
    try { $null = ConvertFrom-Json -InputObject $line -ErrorAction Stop; $line }
    catch { ConvertTo-Json -InputObject @{ type = 'console'; text = $line } -Compress }
}
[System.IO.File]::WriteAllLines($outputPath, [string[]]$records, [System.Text.UTF8Encoding]::new($false))
if ($code -ne 0) { throw "OpenCode exited $code. Transcript: $outputPath" }
$parsed = @($records | ForEach-Object { $_ | ConvertFrom-Json -ErrorAction Stop })
$answer = ($parsed | Where-Object type -eq 'text' | ForEach-Object { $_.part.text }) -join "`n"
if ($answer -notmatch 'L:\\LocalCoder') { throw "Resumed answer did not recall the prior project root. Transcript: $outputPath" }
Write-Host "PASS: resumed session recalled prior turn's project root. Transcript: $outputPath" -ForegroundColor Green
