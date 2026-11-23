param([switch]$NoToolControl)
$ErrorActionPreference = 'Stop'
Set-Location 'L:\LocalCoder'
Write-Host 'VISIBLE ONE-SHOT: opt-in OpenCode-to-LM-Studio request trace; prompt text is not logged.' -ForegroundColor Cyan
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
$label = if ($NoToolControl) { 'no-tool-control' } else { 'tool-turn' }
$outputPath = Join-Path $PSScriptRoot "request-trace-$label-$stamp.jsonl"
$providerTracePath = Join-Path $PSScriptRoot "provider-requests-$label-$stamp.jsonl"
$prompt = if ($NoToolControl) { 'In one sentence, state the configured LocalCoder project root from the project instructions. Do not call any tools.' } else { 'Use the read tool to read .opencode/evals/exact-write-probe.txt and report its exact contents.' }
$ip = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias Ethernet | Where-Object { $_.IPAddress -notlike '169.254*' } | Select-Object -First 1 -ExpandProperty IPAddress
if (-not $ip) { throw 'Could not find the Ethernet address used to reach LM Studio.' }
$env:LMSTUDIO_BASE_URL = "http://$ip`:1234/v1"
$priorTraceValue = [Environment]::GetEnvironmentVariable('LOCALCODER_TRACE_LLM', 'Process')
$priorTracePath = [Environment]::GetEnvironmentVariable('LOCALCODER_TRACE_LLM_PATH', 'Process')
$env:LOCALCODER_TRACE_LLM = '1'
$env:LOCALCODER_TRACE_LLM_PATH = $providerTracePath
$env:PATH = "$env:APPDATA\npm;$env:PATH"
$runOutput = @()
$opencodeExe = Join-Path $env:APPDATA 'npm\node_modules\@opencode\cli\bin\opencode.exe'
if (-not (Test-Path -LiteralPath $opencodeExe)) { throw "Installed OpenCode executable not found: $opencodeExe" }
& $opencodeExe --standalone run --agent build --format json $prompt 2>&1 | Tee-Object -Variable runOutput
$code = $LASTEXITCODE
if ($null -eq $priorTraceValue) { Remove-Item Env:\LOCALCODER_TRACE_LLM -ErrorAction SilentlyContinue }
else { $env:LOCALCODER_TRACE_LLM = $priorTraceValue }
if ($null -eq $priorTracePath) { Remove-Item Env:\LOCALCODER_TRACE_LLM_PATH -ErrorAction SilentlyContinue }
else { $env:LOCALCODER_TRACE_LLM_PATH = $priorTracePath }
if ($code -ne 0) { throw "OpenCode exited $code." }
$records = @()
$requestTraces = @()
foreach ($item in $runOutput) {
    $line = [string]$item
    try {
        $record = $line | ConvertFrom-Json -ErrorAction Stop
        if ($record.type -in @('step_start','tool_use','text','step_finish')) { $records += $line }
    } catch { }
}
[System.IO.File]::WriteAllLines($outputPath, [string[]]$records, [System.Text.UTF8Encoding]::new($false))
$requestTraces = @(Get-Content -LiteralPath $providerTracePath | ForEach-Object { $_ | ConvertFrom-Json -ErrorAction Stop })
$stepStarts = @($records | ForEach-Object { $_ | ConvertFrom-Json -ErrorAction Stop } | Where-Object type -eq 'step_start')
if ($requestTraces.Count -lt 1) { throw "No provider request trace appeared. Transcript: $outputPath" }
if (@($requestTraces | Where-Object { -not $_.persistent_memory_injected -or -not $_.memory_matches_disk -or -not $_.user_matches_disk -or -not $_.architect_preference_injected }).Count -gt 0) {
    throw "Outbound model request did not contain verified persistent memory sections. Provider trace: $providerTracePath"
}
if ($NoToolControl -and ($requestTraces.Count -ne 1 -or $stepStarts.Count -ne 1)) {
    throw "No-tool control expected one provider request and one assistant step; got $($requestTraces.Count) and $($stepStarts.Count). Transcript: $outputPath"
}
Write-Host "Captured $($requestTraces.Count) provider request(s) and $($stepStarts.Count) assistant step(s)."
foreach ($trace in $requestTraces) {
    Write-Host ("Request {0}: {1} kind={2} model={3} tools={4} prompt_chars={5} memory_injected={6} MEMORY_matches_disk={7} USER_matches_disk={8}" -f $trace.sequence,$trace.captured_at,$trace.kind,$trace.model,($trace.tool_names -join ','),$trace.prompt_chars,$trace.persistent_memory_injected,$trace.memory_matches_disk,$trace.user_matches_disk)
}
Write-Host "Step transcript: $outputPath"
Write-Host "Provider request trace: $providerTracePath"
