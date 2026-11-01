#Requires -Version 5.0
<#
.SYNOPSIS
    Bonsai Control Panel — Windows onedir build (PyInstaller)

.DESCRIPTION
    Creates .venv, installs dependencies, checks syntax/imports,
    builds a PyInstaller onedir executable, and runs post-build steps.

.PARAMETER Entry
    Python entry point file (default: main.py)

.PARAMETER ConsoleBuild
    Build with console window for debugging (default: no console)

.EXAMPLE
    .\build.ps1 -ConsoleBuild
    Debug build with console output visible.

.EXAMPLE
    .\build.ps1
    Final windowed build.
#>

param(
    [string]$Entry = "main.py",
    [switch]$ConsoleBuild,
    [switch]$SkipVenvCreate
)

$ErrorActionPreference = "Stop"

$root = (Get-Location).Path
Write-Host "Project root: $root" -ForegroundColor Cyan

# ------------------------------------------------------------------
# Virtual environment
# ------------------------------------------------------------------
if (-not $SkipVenvCreate) {
    Write-Host "[1/6] Creating virtual environment .venv..." -ForegroundColor Green
    python -m venv .venv
}

$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Warning "Local venv python not found, falling back to system python"
    $py = "python"
} else {
    Write-Host "Using Python: $py" -ForegroundColor Cyan
}

# ------------------------------------------------------------------
# Install dependencies
# ------------------------------------------------------------------
Write-Host "[2/6] Installing dependencies..." -ForegroundColor Green
& $py -m pip install --upgrade pip wheel
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed (exit code: $LASTEXITCODE)" }

& $py -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "dependency install failed (exit code: $LASTEXITCODE)" }

# ------------------------------------------------------------------
# Syntax check
# ------------------------------------------------------------------
Write-Host "[3/6] Checking syntax..." -ForegroundColor Green
& $py -m compileall -q .
if ($LASTEXITCODE -ne 0) { throw "compileall failed — fix syntax errors first" }

# ------------------------------------------------------------------
# Import check
# ------------------------------------------------------------------
Write-Host "[4/6] Checking imports..." -ForegroundColor Green
& $py tools\check_imports.py
if ($LASTEXITCODE -ne 0) { throw "import check failed — missing modules or dependencies" }

# ------------------------------------------------------------------
# PyInstaller build
# ------------------------------------------------------------------
$env:BONSAI_ENTRY = $Entry
$env:BONSAI_APP_NAME = "Bonsai"

if ($ConsoleBuild) {
    $env:BONSAI_CONSOLE = "1"
} else {
    $env:BONSAI_CONSOLE = "0"
}

Write-Host "[5/6] Building with PyInstaller (onedir, console=$($env:BONSAI_CONSOLE))..." -ForegroundColor Green
& $py -m PyInstaller --clean --noconfirm bonsai.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed (exit code: $LASTEXITCODE)" }

# ------------------------------------------------------------------
# Post-build
# ------------------------------------------------------------------
Write-Host "[6/6] Post-build..." -ForegroundColor Green
& $py tools\post_build.py
if ($LASTEXITCODE -ne 0) { throw "post-build failed (exit code: $LASTEXITCODE)" }

# ------------------------------------------------------------------
# Done
# ------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "BUILD SUCCESSFUL" -ForegroundColor Green
Write-Host "Output: dist\Bonsai\Bonsai.exe" -ForegroundColor Cyan
Write-Host "============================================================"
