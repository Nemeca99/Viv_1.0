$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$crate = Join-Path $root "..\local_security_core"
$evidenceRoot = Join-Path $root "sandbox\code\audit\verification_runs"
$runId = "template-toolbox-" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$runDir = Join-Path $evidenceRoot $runId
$null = New-Item -ItemType Directory -Path $runDir -Force
$results = [System.Collections.Generic.List[object]]::new()

function Invoke-Logged {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $logPath = Join-Path $runDir "$Name.log"
    $null = New-Item -ItemType File -Path $logPath -Force
    Push-Location $WorkingDirectory
    try {
        & $Executable @Arguments 2>&1 | Tee-Object -FilePath $logPath
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    $hash = (Get-FileHash -LiteralPath $logPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $results.Add([pscustomobject]@{
        name = $Name
        exit_code = $exitCode
        log = [IO.Path]::GetRelativePath($root, $logPath).Replace("\", "/")
        log_sha256 = $hash
    })
    if ($exitCode -ne 0) {
        throw "$Name failed with exit code $exitCode; see $logPath"
    }
}

Invoke-Logged -Name "rust_format" -WorkingDirectory $crate -Executable "cargo" -Arguments @("fmt", "--check")
Invoke-Logged -Name "rust_tests" -WorkingDirectory $crate -Executable "cargo" -Arguments @("test", "--offline", "--lib")
Invoke-Logged -Name "rust_build" -WorkingDirectory $crate -Executable "cargo" -Arguments @("build", "--offline", "--lib")

$pyd = Join-Path $root "foundation\lib\security_core.pyd"
$dll = Join-Path $crate "target\debug\security_core.dll"
Copy-Item -LiteralPath $dll -Destination $pyd -Force
$pydHash = (Get-FileHash -LiteralPath $pyd -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$pyd.sha256" -Value "sha256=$pydHash" -NoNewline

$env:PYTHONPATH = (Join-Path $root "foundation")
Invoke-Logged -Name "python_tests" -WorkingDirectory $root -Executable "python" -Arguments @("-m", "unittest", "discover", "-s", "build_tools", "-p", "test_*.py", "-v")
Invoke-Logged -Name "security_bridge" -WorkingDirectory $root -Executable "python" -Arguments @("-c", "from lib.security_bridge import rust_available, integrity_status; assert rust_available(), integrity_status(); print(integrity_status())")

$requestPath = Join-Path $root "sandbox\code\requests\verification_selection.json"
$request = '{"schema_version":"viv_code_template_selection_request_v1","templates":[{"template_id":"fixture.echo","target_pillars":["auto"]},{"template_id":"fixture.echo_companion","target_pillars":["auto"]}]}'
$null = New-Item -ItemType Directory -Path (Split-Path -Parent $requestPath) -Force
Set-Content -LiteralPath $requestPath -Encoding utf8 -Value $request
Invoke-Logged -Name "mind_request_dry_run" -WorkingDirectory $root -Executable "python" -Arguments @(
    "build_tools\template_builder_v1.py", "--receipt-root", (Join-Path $runDir "dry_run_receipts"),
    "build", "--dry-run", "--request", $requestPath
)
Invoke-Logged -Name "isolated_runtime_self_test" -WorkingDirectory $root -Executable "python" -Arguments @(
    "build_tools\template_builder_v1.py", "self-test", "--template-id", "fixture.echo",
    "--pillar", "auto", "--repeats", "10", "--isolated", "--no-publish",
    "--receipt-dir", (Join-Path $runDir "self_test_receipts")
)

$dryRun = Get-Content -LiteralPath (Join-Path $runDir "mind_request_dry_run.log") -Raw | ConvertFrom-Json
if ($dryRun.state -ne "HOLD_SECURITY" -or $dryRun.writes_performed -ne $false) {
    throw "Dry-run did not preserve the closed-write security hold."
}
$selfTest = Get-Content -LiteralPath (Join-Path $runDir "isolated_runtime_self_test.log") -Raw | ConvertFrom-Json
if ($selfTest.state -ne "PASS_WITH_EXPECTED_SECURITY_HOLD" -or $selfTest.generated_files_created -ne $false -or $selfTest.active_pointer_changed -ne $false) {
    throw "Isolated self-test failed its expected candidate-only gate."
}

$report = [pscustomobject]@{
    schema_version = "localcoder_template_toolbox_verification_v1"
    run_id = $runId
    scope = "candidate-only; no live pointer or moved Viv tree"
    security_core_pyd_sha256 = $pydHash
    rust_unit_test_summary = ((Get-Content -LiteralPath (Join-Path $runDir "rust_tests.log") | Select-String "test result:").Line | Select-Object -Last 1)
    python_unit_test_summary = ((Get-Content -LiteralPath (Join-Path $runDir "python_tests.log") | Select-String "^Ran ").Line | Select-Object -Last 1)
    dry_run_state = $dryRun.state
    dry_run_writes_performed = $dryRun.writes_performed
    isolated_self_test_state = $selfTest.state
    isolated_self_test_repeats = $selfTest.repeated_run_count
    isolated_self_test_deterministic = $selfTest.deterministic
    isolated_self_test_protected_state_unchanged = $selfTest.protected_state_unchanged
    results = $results
    expected_limits = @(
        "autonomous Python writes remain closed in Rust",
        "dry-run must report HOLD_SECURITY and writes_performed=false",
        "isolated self-test uses disposable assembly only and expects Rust denial"
    )
}
$reportPath = Join-Path $runDir "verification_manifest.json"
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8
$reportHash = (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$reportPath.sha256" -Value $reportHash -NoNewline
Write-Output "PASS: $reportPath"
Write-Output "SHA256: $reportHash"
