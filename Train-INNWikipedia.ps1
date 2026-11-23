param(
    [ValidateRange(1,2000)][int]$Updates = 1000,
    [ValidateRange(1,256)][int]$Articles = 64,
    [ValidateRange(1,100)][int]$Segments = 1
)
$ErrorActionPreference = 'Stop'
for ($segment = 1; $segment -le $Segments; $segment++) {
    & 'L:\.venv\Scripts\python.exe' "$PSScriptRoot\workspace\autonomy\train_inn_wikipedia.py" --updates $Updates --articles $Articles
    if ($LASTEXITCODE -ne 0) { throw "Wikipedia training stopped; inspect inn_wikipedia_status.json (exit $LASTEXITCODE)" }
}
