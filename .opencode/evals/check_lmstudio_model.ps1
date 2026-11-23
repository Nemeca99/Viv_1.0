param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,
    [string]$ProjectRoot = 'L:\LocalCoder'
)

$ErrorActionPreference = 'Stop'
$configPath = Join-Path $ProjectRoot 'opencode.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$selection = [string]$config.model
$modelId = $selection -replace '^[^/]+/', ''
$apiRoot = $BaseUrl -replace '/v1/?$', ''
$response = Invoke-RestMethod -Uri "$apiRoot/api/v0/models" -TimeoutSec 5
$model = $response.data | Where-Object { $_.id -eq $modelId } | Select-Object -First 1

if (-not $model) {
    Write-Error "Configured model '$modelId' was not returned by LM Studio."
    exit 2
}

$state = [string]$model.state
$context = $model.loaded_context_length
if ($state -eq 'loaded') {
    Write-Host "LM Studio ready: $modelId (state=$state, loaded_context_length=$context)" -ForegroundColor Green
} else {
    Write-Warning "Configured model '$modelId' is present but not loaded (state='$state'). No model was loaded by this check."
}
