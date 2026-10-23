param([switch]$Rebuild)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
# Isolate only this process from globally configured Python 3.8 variables.
Remove-Item Env:PYTHONHOME,Env:PYTHONPATH -ErrorAction SilentlyContinue
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Missing virtual environment. Follow README.md installation steps first.' }
if ($Rebuild -or -not (Test-Path -LiteralPath 'apps\web\dist\index.html')) {
    Push-Location 'apps\web'
    try { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Web build failed.' } }
    finally { Pop-Location }
}
Write-Host 'Anxin Relay: http://127.0.0.1:8000 (Ctrl+C to stop)'
& $pythonExe -E -m uvicorn anxin.main:app --host 127.0.0.1 --port 8000
