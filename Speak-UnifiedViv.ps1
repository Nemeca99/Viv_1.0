param(
    [string]$All = "",
    [string]$Spell = "",
    [string]$Unscramble = "",
    [string]$Say = "",
    [string]$Meaning = "",
    [string]$Flashcards = "",
    [string]$Morpheme = "",
    [int]$MaxWords = 10,
    [switch]$Dream,
    [int]$DreamIterations = 1200,
    [string]$PromoteNeologism = "",
    [string]$EvolveNeologism = "",
    [string]$EvolvedMeaning = "",
    [string]$ExperienceContext = "Direct interactive learning experience with the Architect",
    [string]$TeachWord = "",
    [string]$IngestCorpus = "",
    [int]$MaxTokens = 2000000,
    [switch]$ActivationReport,
    [string]$ReportKind = "WORD",
    [int]$Top = 25,
    [switch]$Voice,
    [switch]$Status
)
$ErrorActionPreference = 'Stop'
$cliArgs = @('L:\LocalCoder\workspace\autonomy\speak_unified_viv.py')
if ($All) { $cliArgs += @('--all', $All) }
if ($Spell) { $cliArgs += @('--spell', $Spell) }
if ($Unscramble) { $cliArgs += @('--unscramble', $Unscramble) }
if ($Say) { $cliArgs += @('--say', $Say) }
if ($Meaning) { $cliArgs += @('--meaning', $Meaning) }
if ($Flashcards) { $cliArgs += @('--flashcards', $Flashcards) }
if ($Morpheme) { $cliArgs += @('--morpheme', $Morpheme, '--max-words', $MaxWords.ToString()) }
if ($Dream) { $cliArgs += @('--dream', '--dream-iterations', $DreamIterations.ToString()) }
if ($PromoteNeologism) { $cliArgs += @('--promote-neologism', $PromoteNeologism) }
if ($EvolveNeologism) { $cliArgs += @('--evolve-neologism', $EvolveNeologism, '--evolved-meaning', $EvolvedMeaning, '--experience-context', $ExperienceContext) }
if ($TeachWord) { $cliArgs += @('--teach-word', $TeachWord) }
if ($IngestCorpus) { $cliArgs += @('--ingest-corpus', $IngestCorpus, '--max-tokens', $MaxTokens.ToString()) }
if ($ActivationReport) { $cliArgs += @('--activation-report', '--report-kind', $ReportKind, '--top', $Top.ToString()) }
if ($Voice) { $cliArgs += '--voice' }
if ($Status) { $cliArgs += '--status' }
& 'L:\.venv\Scripts\python.exe' @cliArgs
if ($LASTEXITCODE -ne 0) {
    throw "Unified Viv CLI exited with code $LASTEXITCODE"
}
