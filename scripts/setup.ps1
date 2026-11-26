param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not $PythonPath) {
    $installed = Get-Command python -ErrorAction SilentlyContinue
    if ($installed -and $installed.Source -notlike '*Microsoft/WindowsApps*' -and $installed.Source -notlike '*Microsoft\WindowsApps*') { $PythonPath = $installed.Source }
}
if (-not $PythonPath) {
    $bundles = Get-ChildItem -LiteralPath 'C:/Program Files/WindowsApps' -Directory -ErrorAction SilentlyContinue | Where-Object Name -Like 'OpenAI.CodexPrimaryRuntime*' | Sort-Object Name -Descending
    foreach ($bundle in $bundles) {
        $candidate = Join-Path $bundle.FullName 'dependencies/python/python.exe'
        if (Test-Path -LiteralPath $candidate) { $PythonPath = $candidate; break }
    }
}
if (-not $PythonPath) { throw 'Install Python 3.12 first, or pass -PythonPath to scripts/setup.ps1.' }
& $PythonPath -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment.' }
& './.venv/Scripts/python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Output 'Ready. Double-click start.cmd to open TrendDesk.'
