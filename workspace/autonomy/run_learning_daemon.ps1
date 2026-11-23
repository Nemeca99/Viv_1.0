$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'L:\LocalCoder\workspace;L:\Standalone\NN'
$env:VIV_TUTOR_MODEL = 'qwen1.5-moe-a2.7b-wikihow'
Set-Location -LiteralPath 'L:\LocalCoder\workspace'
& 'L:\.venv\Scripts\python.exe' -u 'L:\LocalCoder\workspace\autonomy\multi_daemon_orchestrator.py'
exit $LASTEXITCODE
