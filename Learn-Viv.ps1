param(
    [string]$InputText,
    [ValidateRange(1, 64)][int]$Attempts = 24,
    [switch]$Autonomous,
    [switch]$MadLibs,
    [switch]$Homophones,
    [switch]$Grade3,
    [int]$MaxLessons = 0,
    [double]$DurationMinutes = 0
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'L:\LocalCoder\workspace'
$Arguments = @('-u', '-m', 'autonomy.terminal_neuron_learning', '--attempts', $Attempts)
if ($MadLibs) {
    $Arguments += @('--mad-libs')
}
if ($Homophones -or $Grade3) {
    $Arguments += @('--homophones')
}
if ($Autonomous) {
    $Arguments += @('--autonomous')
    if ($MaxLessons -gt 0) {
        $Arguments += @('--max-lessons', $MaxLessons)
    }
    if ($DurationMinutes -gt 0) {
        $Arguments += @('--duration-minutes', $DurationMinutes)
    }
} else {
    $Arguments += @('--interactive')
}
if ($PSBoundParameters.ContainsKey('InputText')) {
    $Arguments += @('--input', $InputText)
}
& 'L:\.venv\Scripts\python.exe' @Arguments
