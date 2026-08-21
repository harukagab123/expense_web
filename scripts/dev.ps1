$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $Root ".venv\bin\python.exe"
if (!(Test-Path $VenvPython)) {
    $VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
}
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"

if (!(Test-Path (Join-Path $Root ".env"))) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
}

Start-Process -WindowStyle Hidden -WorkingDirectory $Backend -FilePath $VenvPython -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"
Start-Process -WindowStyle Hidden -WorkingDirectory $Frontend -FilePath "npm.cmd" -ArgumentList "run", "dev", "--", "--host", "127.0.0.1"

Write-Host "Backend:  http://127.0.0.1:8000"
Write-Host "Frontend: http://127.0.0.1:5173"
