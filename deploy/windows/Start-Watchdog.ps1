param(
    [string]$RepoPath = "",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoPath)) {
    $RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
} else {
    $RepoPath = (Resolve-Path $RepoPath).Path
}

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $PythonExe = $pythonCmd.Source
    } else {
        $pyCmd = Get-Command py -ErrorAction SilentlyContinue
        if (-not $pyCmd) {
            throw "python/py not found in PATH."
        }
        Set-Location $RepoPath
        & $pyCmd.Source -3 -m backend.worker.watchdog --workspace $RepoPath
        exit $LASTEXITCODE
    }
}

Set-Location $RepoPath
& $PythonExe -m backend.worker.watchdog --workspace $RepoPath
exit $LASTEXITCODE
