$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $projectRoot '.runtime.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Output 'No managed TrendDesk server.'; exit 0 }
# start.ps1 writes UTF-8. Windows PowerShell 5.1 otherwise reads BOM-less files as ANSI.
$state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $($state.pid)"
if ($process) {
    if ($process.ExecutablePath -ne $state.python -or $process.CommandLine -notmatch 'uvicorn app.main:app') {
        throw 'Process identity changed; refusing to stop an unrelated process.'
    }
    Stop-Process -Id $state.pid
}
Remove-Item -LiteralPath $statePath
Write-Output 'TrendDesk stopped. Moomoo OpenD was left running.'
