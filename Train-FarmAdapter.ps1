param([string]$Base='', [int]$Steps=160, [switch]$Train, [switch]$SkipEvaluation, [switch]$ResumeFarm)
$ErrorActionPreference='Stop'
if ($Train) {
    & 'L:\.venv\Scripts\python.exe' 'L:\LocalCoder\workspace\viv_autonomy.py' pause
    if ($LASTEXITCODE -ne 0) { throw "Farm pause exited with code $LASTEXITCODE" }
}
$adapterArgs = @('L:\LocalCoder\workspace\autonomy\farm_adapter.py', '--steps', "$Steps")
if ($Base) { $adapterArgs += @('--base', $Base) }
if ($Train) { $adapterArgs += @('--train', '--gpu-phase') }
& 'L:\.venv\Scripts\python.exe' @adapterArgs
if ($LASTEXITCODE -ne 0) { throw "Farm adapter command exited with code $LASTEXITCODE" }
if ($Train -and -not $SkipEvaluation) {
    & 'L:\.venv\Scripts\python.exe' 'L:\LocalCoder\workspace\autonomy\evaluate_farm_adapter.py'
    if ($LASTEXITCODE -ne 0) { throw "Farm adapter evaluation exited with code $LASTEXITCODE" }
}
if ($Train) {
    if ($ResumeFarm) {
        & 'L:\.venv\Scripts\python.exe' 'L:\LocalCoder\workspace\viv_autonomy.py' resume
        if ($LASTEXITCODE -ne 0) { throw "Farm resume exited with code $LASTEXITCODE" }
        Write-Host 'GPU job finished. Continuous farm explicitly resumed; it runs until paused.'
    } else {
        Write-Host 'GPU job finished. Farm remains paused; no continuous learning worker was restarted.'
    }
}
