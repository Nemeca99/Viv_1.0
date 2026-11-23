[CmdletBinding()]
param(
    [int]$Port = 8501
)

$ErrorActionPreference = 'Stop'
$Python = 'L:\.venv\Scripts\python.exe'
$Dashboard = 'L:\LocalCoder\workspace\autonomy\streamlit_dashboard.py'

if (-not (Test-Path -LiteralPath $Python)) {
    throw "LocalCoder Python environment was not found at $Python"
}
if (-not (Test-Path -LiteralPath $Dashboard)) {
    throw "LocalCoder dashboard was not found at $Dashboard"
}

$Existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Output "INN dashboard is already running at http://127.0.0.1:$Port"
    exit 0
}

& $Python -m streamlit run $Dashboard --server.address 127.0.0.1 --server.port $Port
exit $LASTEXITCODE
