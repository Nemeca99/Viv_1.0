param([ValidateRange(1,1000)][int]$Updates=1000, [ValidateRange(41,64)][int]$FinalPlot=43)
$ErrorActionPreference='Stop'
& 'L:\.venv\Scripts\python.exe' 'L:\LocalCoder\workspace\autonomy\rebuild_inn_tokenizer.py' --updates "$Updates" --final-plot "$FinalPlot"
if ($LASTEXITCODE -ne 0) { throw "Tokenizer rebuild exited with code $LASTEXITCODE" }
