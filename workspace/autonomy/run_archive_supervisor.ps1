$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'L:\LocalCoder\workspace'
Set-Location -LiteralPath 'L:\LocalCoder\workspace'
& 'L:\.venv\Scripts\python.exe' -u 'L:\LocalCoder\workspace\autonomy\archive_storage_supervisor.py' *>> 'L:\LocalCoder\workspace\autonomy\learning\archive_supervisor.log'
exit $LASTEXITCODE
