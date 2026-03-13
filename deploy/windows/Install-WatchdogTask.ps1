param(
    [string]$RepoPath = "",
    [string]$TaskName = "MultiLLMDocAgentWatchdog",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoPath)) {
    $RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
} else {
    $RepoPath = (Resolve-Path $RepoPath).Path
}

$scriptPath = Join-Path $RepoPath "deploy\windows\Start-Watchdog.ps1"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -RepoPath `"$RepoPath`""
if (-not [string]::IsNullOrWhiteSpace($PythonExe)) {
    $arguments += " -PythonExe `"$PythonExe`""
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Watch and restart Multi-LLM Doc Agent API/Worker only when health checks fail." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed scheduled task: $TaskName"
Write-Host "Repo: $RepoPath"
