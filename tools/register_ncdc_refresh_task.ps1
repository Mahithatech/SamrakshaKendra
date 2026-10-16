$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$scriptPath = Join-Path $PSScriptRoot 'refresh_ncdc_candidates.ps1'
$taskName = 'SamrakshaKendra-NCDC-Candidate-Refresh'
if (!(Test-Path $scriptPath)) { throw "Refresh script not found: $scriptPath" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At '06:30'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Downloads up to three current-year NCDC weekly report PDFs and validates candidates. Does not modify PostgreSQL or live surveillance.' -Force | Out-Null
Write-Host "Registered daily task: $taskName at 06:30 (local time)."
Write-Host 'It runs only while this Windows user is signed in. It does not promote records into live surveillance.'
Write-Host 'To run it once now: Start-ScheduledTask -TaskName "SamrakshaKendra-NCDC-Candidate-Refresh"'
