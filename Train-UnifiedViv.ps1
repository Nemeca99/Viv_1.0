param(
    [int]$Updates = 350,
    [int]$PerLengthLimit = 12,
    [int]$MaxWordLength = 4,
    [int]$Threads = 4,
    [string]$SourceDb = ""
)
$ErrorActionPreference = 'Stop'
$trainArgs = @(
    'L:\LocalCoder\workspace\autonomy\train_unified_viv.py',
    '--updates', "$Updates",
    '--per-length-limit', "$PerLengthLimit",
    '--max-word-length', "$MaxWordLength",
    '--threads', "$Threads"
)
if ($SourceDb) {
    $trainArgs += @('--source-db', $SourceDb)
}
& 'L:\.venv\Scripts\python.exe' @trainArgs
if ($LASTEXITCODE -ne 0) {
    throw "Unified Viv toddler training failed with exit code $LASTEXITCODE"
}
