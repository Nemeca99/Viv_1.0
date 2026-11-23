param(
    [ValidateRange(1, 256)][int]$Steps = 16,
    [ValidateRange(1, 6)][int]$Rounds = 3,
    [ValidateRange(1, 120)][int]$MaxMinutesPerRound = 45,
    [ValidateRange(0.0000001, 0.001)][double]$LearningRate = 0.00001,
    [ValidateSet('v4', 'v5', 'v6', 'v7', 'v8', 'v9', 'v10')][string]$Curriculum = 'v5',
    [ValidateRange(1, 128)][int]$LoraR = 8,
    [ValidatePattern('^\d+-\d+$')][string]$LoraLayers = '24-31',
    [switch]$ReuseBaseline,
    [ValidateRange(64, 4096)][int]$MaxTokens = 256,
    [ValidateRange(256, 8192)][int]$MaxPromptTokens = 1024,
    [string]$ResumeAdapter = ''
)
$ErrorActionPreference = 'Stop'
$workRoot = 'E:\Viv_Sandbox\omnicoder_identity_20261118'
$env:PYTHONPATH = Join-Path $workRoot 'packages'
$env:HF_HOME = Join-Path $workRoot 'cache'
$env:HF_HUB_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
$env:TEMP = Join-Path $workRoot 'tmp'
$env:TMP = $env:TEMP
$trainArgs = @('-B', 'L:\LocalCoder\workspace\autonomy\omnicoder_identity_training\train.py',
    'train', '--work', $workRoot, '--steps', $Steps, '--rounds', $Rounds,
    '--max-minutes', $MaxMinutesPerRound, '--learning-rate',
    $LearningRate.ToString('G17', [Globalization.CultureInfo]::InvariantCulture),
    '--curriculum', $Curriculum,
    '--lora-r', $LoraR,
    '--lora-layers', $LoraLayers,
    '--max-tokens', $MaxTokens,
    '--max-prompt-tokens', $MaxPromptTokens)
if ($ReuseBaseline) {
    $trainArgs += '--reuse-baseline'
}
if ($ResumeAdapter) {
    $resolvedAdapter = (Resolve-Path -LiteralPath $ResumeAdapter).Path
    if (-not $resolvedAdapter.StartsWith($workRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Resume adapter must stay in this candidate workspace.'
    }
    $trainArgs += @('--resume-adapter', $resolvedAdapter)
}
& 'L:\.venv\Scripts\python.exe' @trainArgs
exit $LASTEXITCODE
