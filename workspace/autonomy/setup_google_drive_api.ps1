[CmdletBinding()]
param(
    [string]$CredentialsPath,
    [string]$FolderId,
    [switch]$SkipSupervisorRestart
)

$ErrorActionPreference = 'Stop'
$python = 'L:\.venv\Scripts\python.exe'
$workspace = 'L:\LocalCoder\workspace'
$configDir = Join-Path $env:USERPROFILE '.config\viv-google-drive'
$credentialsTarget = Join-Path $configDir 'credentials.json'
$folderTarget = Join-Path $configDir 'folder_id.txt'

New-Item -ItemType Directory -Path $configDir -Force | Out-Null

if (-not $CredentialsPath) {
    if (Test-Path -LiteralPath $credentialsTarget -PathType Leaf) {
        $CredentialsPath = $credentialsTarget
        Write-Host "Using detected credentials file: $CredentialsPath" -ForegroundColor Green
    } else {
        $CredentialsPath = Read-Host 'Path to the Google OAuth desktop-client JSON file or its folder'
    }
}
$credentialItem = Get-Item -LiteralPath $CredentialsPath -ErrorAction SilentlyContinue
if ($credentialItem -and $credentialItem.PSIsContainer) {
    $CredentialsPath = Join-Path $credentialItem.FullName 'credentials.json'
}
if (-not (Test-Path -LiteralPath $CredentialsPath -PathType Leaf)) {
    throw "OAuth credentials file not found: $CredentialsPath`nExpected default: $credentialsTarget"
}
$CredentialsPath = (Resolve-Path -LiteralPath $CredentialsPath).Path
$resolvedTarget = (Resolve-Path -LiteralPath $credentialsTarget -ErrorAction SilentlyContinue)
if (-not $resolvedTarget -or $resolvedTarget.Path -ne $CredentialsPath) {
    Copy-Item -LiteralPath $CredentialsPath -Destination $credentialsTarget -Force
}

if (-not $FolderId) {
    if (Test-Path -LiteralPath $folderTarget) {
        $FolderId = (Get-Content -LiteralPath $folderTarget -Raw).Trim()
        if ($FolderId -match '^[A-Za-z]:[\\/]' -or (Test-Path -LiteralPath $FolderId -PathType Container -ErrorAction SilentlyContinue)) {
            $FolderId = ''
        }
    }
    if (-not $FolderId) {
        $FolderId = Read-Host 'Google Drive destination folder ID'
    }
}
if (-not $FolderId) {
    throw 'A Google Drive destination folder ID is required.'
}
if ($FolderId -match '^[A-Za-z]:[\\/]' -or (Test-Path -LiteralPath $FolderId -PathType Container -ErrorAction SilentlyContinue)) {
    throw "'$FolderId' is a local filesystem path. Provide the Google Drive folder ID from the folder URL instead."
}
Set-Content -LiteralPath $folderTarget -Value $FolderId.Trim() -NoNewline -Encoding UTF8

Write-Host 'Starting Google OAuth in your browser...' -ForegroundColor Cyan
$env:PYTHONPATH = $workspace
Set-Location -LiteralPath $workspace
& $python (Join-Path $workspace 'autonomy\authorize_google_drive.py')
if ($LASTEXITCODE -ne 0) {
    throw "Google OAuth authorization failed with exit code $LASTEXITCODE"
}

$configured = & $python -c "from autonomy.google_drive_api_uploader import GoogleDriveApiUploader; print(GoogleDriveApiUploader.configured())"
if ($configured.Trim() -ne 'True') {
    throw 'OAuth completed, but the Drive API configuration did not validate.'
}

if (-not $SkipSupervisorRestart) {
    Write-Host 'Restarting the scheduled archive supervisor...' -ForegroundColor Cyan
    Stop-ScheduledTask -TaskName 'AIOS_Viv_Archive_Supervisor' -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "name='python.exe'" |
        Where-Object { $_.CommandLine -match 'archive_storage_supervisor.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName 'AIOS_Viv_Archive_Supervisor'
}

Write-Host "Google Drive API authorization is ready. Token stored at $configDir (contents not displayed)." -ForegroundColor Green
