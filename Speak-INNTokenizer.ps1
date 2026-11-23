param([Parameter(Mandatory=$true)][string]$Prompt)
$ErrorActionPreference='Stop'
& 'L:\.venv\Scripts\python.exe' 'L:\LocalCoder\workspace\autonomy\speak_inn_tokenizer.py' --prompt $Prompt
if ($LASTEXITCODE -ne 0) { throw "INN tokenizer generation exited with code $LASTEXITCODE" }
