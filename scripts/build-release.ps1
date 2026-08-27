param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $ProjectRoot ".venv\bin\python.exe"
$Frontend = Join-Path $ProjectRoot "frontend"
$Backend = Join-Path $ProjectRoot "backend"
$Release = Join-Path $ProjectRoot "outputs\release"
$Build = Join-Path $ProjectRoot "outputs\pyinstaller-build"
$Version = & $Python -c "from app.version import APP_VERSION; print(APP_VERSION)" 2>$null
if ($LASTEXITCODE -ne 0) {
    Push-Location $Backend
    try { $Version = & $Python -c "from app.version import APP_VERSION; print(APP_VERSION)" } finally { Pop-Location }
}

Push-Location $Frontend
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed. Close any running Vite development server and retry." }
    npm run lint
    if ($LASTEXITCODE -ne 0) { throw "Frontend lint failed." }
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw "Frontend typecheck failed." }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed." }
} finally {
    Pop-Location
}

if (!$SkipTests) {
    Push-Location $Backend
    try {
        & $Python -m pytest
        if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." }
    } finally { Pop-Location }
}

New-Item -ItemType Directory -Force -Path $Release | Out-Null
& $Python -m PyInstaller --noconfirm --clean --distpath $Release --workpath $Build (Join-Path $ProjectRoot "packaging\PersonalFinanceManager.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller package build failed." }

$PortableZip = Join-Path $Release "PersonalFinanceManager-$Version-Portable.zip"
Compress-Archive -Force -LiteralPath (Join-Path $Release "PersonalFinanceManager.exe"), (Join-Path $ProjectRoot "docs\USER_GUIDE.md") -DestinationPath $PortableZip

$Inno = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($Inno) {
    & $Inno.Source "/DMyAppVersion=$Version" (Join-Path $ProjectRoot "packaging\PersonalFinanceManager.iss")
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed." }
} else {
    Write-Warning "Inno Setup was not found. Portable package built; installer was not built."
}

Write-Host "Release artifacts: $Release"
