$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = $PSScriptRoot
$basePython = 'L:\Python312\python.exe'
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$buildRoot = Join-Path $projectRoot 'build'
$evidenceRoot = Join-Path $projectRoot 'artifacts'

if (!(Test-Path -LiteralPath $basePython)) {
    throw "Expected base Python interpreter not found: $basePython"
}
if (!(Test-Path -LiteralPath $venvPython)) {
    & $basePython -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Creating the project venv failed.' }
}

& $venvPython -m pip install --disable-pip-version-check --no-input -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Installing the pinned project dependencies failed.' }

$runId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')
$runDirectory = Join-Path $evidenceRoot $runId
New-Item -ItemType Directory -Force -Path $runDirectory,$buildRoot | Out-Null
$rustBinary = Join-Path $buildRoot 'rust_frontend.exe'
$receiptPath = Join-Path $runDirectory 'bridge_receipt.json'
$switchboard = Join-Path $projectRoot 'python_switchboard.py'
$rustSource = Join-Path $projectRoot 'rust_frontend.rs'

Push-Location $projectRoot
try {
    & $venvPython -m unittest discover -s 'tests' -v 2>&1 |
        Tee-Object -FilePath (Join-Path $runDirectory 'python_tests.log')
    $pythonTestExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($pythonTestExit -ne 0) { throw "Python unit tests failed; see $runDirectory\python_tests.log" }

$rustfmtLog = Join-Path $runDirectory 'rustfmt.log'
"COMMAND rustfmt --edition 2021 --check $rustSource" | Set-Content -LiteralPath $rustfmtLog -Encoding utf8
& rustfmt --edition 2021 --check $rustSource 2>&1 |
    Tee-Object -FilePath $rustfmtLog -Append
$rustfmtExit = $LASTEXITCODE
if ($rustfmtExit -ne 0) { throw "rustfmt check failed; see $runDirectory\rustfmt.log" }

$rustcLog = Join-Path $runDirectory 'rustc.log'
"COMMAND rustc --edition=2021 -D warnings $rustSource -o $rustBinary" | Set-Content -LiteralPath $rustcLog -Encoding utf8
& rustc --edition=2021 -D warnings $rustSource -o $rustBinary 2>&1 |
    Tee-Object -FilePath $rustcLog -Append
$rustcExit = $LASTEXITCODE
if ($rustcExit -ne 0) { throw "Rust compilation failed; see $runDirectory\rustc.log" }

& $rustBinary $venvPython $switchboard $receiptPath 2>&1 |
    Tee-Object -FilePath (Join-Path $runDirectory 'bridge_run.log')
$bridgeExit = $LASTEXITCODE
if ($bridgeExit -ne 0) { throw "Rust/NumPy round-trip failed; see $runDirectory\bridge_run.log" }

$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if (!$receipt.accepted_by_rust) { throw 'Rust did not accept the round-trip result.' }
if (!($receipt.after_feedback_backprop_loss -lt $receipt.initial_loss)) {
    throw 'The final loss did not improve over the initial loss.'
}

$filesToHash = @(
    'numpy_backend.py',
    'python_switchboard.py',
    'rust_frontend.rs',
    'tests/test_numpy_backend.py',
    'requirements.txt',
    'run_proof.ps1',
    'bridge_receipt.json',
    'python_tests.log',
    'rustfmt.log',
    'rustc.log',
    'bridge_run.log'
)
$hashes = [ordered]@{}
foreach ($relativePath in $filesToHash) {
    $absolutePath = if ($relativePath -eq 'bridge_receipt.json' -or $relativePath -like '*.log') {
        Join-Path $runDirectory $relativePath
    } else {
        Join-Path $projectRoot $relativePath
    }
    $hashes[$relativePath] = (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash
}

$pythonVersion = (& $venvPython --version 2>&1).ToString()
$rustVersion = (& rustc --version 2>&1).ToString()
$rustfmtVersion = (& rustfmt --version 2>&1).ToString()
$manifest = [ordered]@{
    schema = 'hive_numpy_bridge_run_v1'
    run_id = $runId
    timestamp_utc = [DateTime]::UtcNow.ToString('o')
    status = 'PASS'
    architecture = 'Rust control/front end -> Python switchboard -> NumPy backend -> Python -> Rust feedback and acceptance'
    checks = [ordered]@{
        numpy_unit_tests = 'PASS'
        rustfmt = 'PASS'
        rust_compile_warnings_denied = 'PASS'
        end_to_end_roundtrip = 'PASS'
        rust_acceptance_gate = 'PASS'
        loss_decreased = 'PASS'
    }
    metrics = $receipt
    tools = [ordered]@{
        python = $pythonVersion
        numpy = $receipt.numpy_version
        rustc = $rustVersion
        rustfmt = $rustfmtVersion
    }
    sha256 = $hashes
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDirectory 'run_manifest.json') -Encoding utf8

Write-Output "PROOF_PASS $runDirectory"
Write-Output ("LOSS {0:G8} -> {1:G8} -> {2:G8}" -f $receipt.initial_loss,$receipt.after_forward_loss,$receipt.after_feedback_backprop_loss)
Write-Output ("NUMPY {0}; SEED {1}; SHAPE X={2}x{3}, y={4}x{5}" -f $receipt.numpy_version,$receipt.seed,$receipt.return_shapes.X[0],$receipt.return_shapes.X[1],$receipt.return_shapes.y[0],$receipt.return_shapes.y[1])
