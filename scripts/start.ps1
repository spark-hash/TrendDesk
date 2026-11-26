param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python environment missing. Install Python 3.12, then run: py -3.12 -m venv .venv; .venv/Scripts/python.exe -m pip install -r requirements.txt'
}
$url = 'http://127.0.0.1:8765'
$health = $null
try { $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2 } catch {}
if ($health -and $health.app -eq 'trenddesk') {
    if (-not $NoBrowser) { Start-Process $url }
    Write-Output "TrendDesk already running: $url"
    exit 0
}
New-Item -ItemType Directory -Path (Join-Path $projectRoot 'data') -Force | Out-Null
$server = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8765','--log-level','warning') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'data/server.log') -RedirectStandardError (Join-Path $projectRoot 'data/server-error.log')
@{pid=$server.Id;python=$pythonPath;root=$projectRoot} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot '.runtime.json') -Encoding utf8
for ($attempt=0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    $server.Refresh()
    if ($server.HasExited) { throw 'TrendDesk exited. See data/server-error.log.' }
    try {
        $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 1
        if ($health.app -eq 'trenddesk') {
            if (-not $NoBrowser) { Start-Process $url }
            Write-Output "TrendDesk ready: $url"
            exit 0
        }
    } catch {}
}
throw 'Startup timed out. See data/server-error.log.'
