$Host.UI.RawUI.WindowTitle = 'Hermes - LIVE Viv development activity'
Write-Host 'HERMES: LIVE VIV DEVELOPMENT' -ForegroundColor Cyan
Write-Host 'Assignment: verify epoch10040 serving/evaluation state, establish baseline, investigate helper resolution.'
Write-Host 'Each run: do one concrete step, verify it, append L:\LocalCoder\BUILD_LOG.md, preserve continuation.'
Write-Host 'This window shows real agent/tool activity. Closing it does not stop Hermes.' -ForegroundColor Yellow
Write-Host 'Full instructions: L:\LocalCoder\HERMES_AUTONOMY.md'
Write-Host ''
& "$env:USERPROFILE\.local\bin\hermes.exe" cron runs 6106e7d68386 --limit 3
Write-Host ''
Get-Content "$env:LOCALAPPDATA\hermes\logs\agent.log" -Tail 35 -Wait
