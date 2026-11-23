param([ValidateRange(20,500)][int]$Articles=80, [ValidateRange(1,2000)][int]$Updates=600,
      [ValidateSet('content','structure')][string]$Stage='content', [ValidateRange(2,10)][int]$RetentionEvery=2)
$ErrorActionPreference='Stop'
& 'L:\.venv\Scripts\python.exe' 'L:\LocalCoder\workspace\autonomy\train_inn_sentences.py' --articles "$Articles" --updates "$Updates" --stage $Stage --retention-every "$RetentionEvery"
if ($LASTEXITCODE -ne 0) { throw "INN sentence training exited with code $LASTEXITCODE" }
