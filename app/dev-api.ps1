$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Remove-Item Env:PYTHONHOME,Env:PYTHONPATH -ErrorAction SilentlyContinue
& '.\.venv\Scripts\python.exe' -E -m uvicorn anxin.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend/src
