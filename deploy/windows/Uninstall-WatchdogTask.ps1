param(
    [string]$RepoPath = "",
    [string]$TaskName = "MultiLLMDocAgentWatchdog"
)

$ErrorActionPreference = "Stop"

if (-not [string]::IsNullOrWhiteSpace($RepoPath)) {
    $RepoPath = (Resolve-Path $RepoPath).Path
} else {
    $RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$pidDir = Join-Path $RepoPath "artifacts\runtime\pids"
if (Test-Path $pidDir) {
    Get-ChildItem -Path $pidDir -Filter *.json | ForEach-Object {
        try {
            $payload = Get-Content $_.FullName -Raw | ConvertFrom-Json
            if ($payload.pid) {
                Stop-Process -Id ([int]$payload.pid) -Force -ErrorAction SilentlyContinue
            }
        } catch {
        }
    }
}

Write-Host "Removed scheduled task: $TaskName"
