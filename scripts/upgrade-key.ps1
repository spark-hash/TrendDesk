$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv/Scripts/python.exe'
& $python -X utf8 -m app.save_key
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& "$PSScriptRoot/stop.ps1"
& "$PSScriptRoot/start.ps1" -NoBrowser
$state = Invoke-RestMethod 'http://127.0.0.1:8765/api/ai/config'
if (-not ($state.configured -and $state.key_storage -eq 'dpapi')) {
    throw 'The restarted service could not confirm the encrypted credential.'
}
Write-Host 'Encrypted key saved and restored after restart.'
