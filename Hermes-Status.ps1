Get-ScheduledTask -TaskName 'LocalCoder-Hermes-Continuous' | Select-Object TaskName, State
& "$env:USERPROFILE\.local\bin\hermes.exe" gateway status
& "$env:USERPROFILE\.local\bin\hermes.exe" cron list
& "$env:USERPROFILE\.local\bin\hermes.exe" cron runs 6106e7d68386 --limit 5
