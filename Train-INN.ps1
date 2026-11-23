param([int]$Updates=2000, [int]$CollectSteps=1200, [int]$Threads=2, [string]$Resume='')
$ErrorActionPreference='Stop'
$trainingArgs = @('L:\LocalCoder\workspace\autonomy\train_neural_inn.py', '--updates', "$Updates", '--collect-steps', "$CollectSteps", '--threads', "$Threads")
if ($Resume) { $trainingArgs += @('--resume', $Resume) }
& 'L:\.venv\Scripts\python.exe' @trainingArgs
if ($LASTEXITCODE -ne 0) { throw "Neural training failed with exit code $LASTEXITCODE" }
