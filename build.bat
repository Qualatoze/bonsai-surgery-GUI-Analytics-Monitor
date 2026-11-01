@echo off
setlocal EnableExtensions

REM ============================================================
REM Bonsai Control Panel — Windows onedir build (PyInstaller)
REM Usage: cd "path to bonsai GUI" && build.bat
REM ============================================================

set APP_NAME=Bonsai
set ENTRY=main.py
set CONSOLE=0

REM Для отладочной сборки раскомментируйте строку ниже:
REM set CONSOLE=1

echo [1/6] Creating virtual environment...
if not exist .venv (
    python -m venv .venv
)

set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
    echo ERROR: %PY% not found. Is Python installed?
    pause
    exit /b 1
)

echo Using Python: %PY%

echo [2/6] Installing dependencies...
"%PY%" -m pip install --upgrade pip wheel
if errorlevel 1 (
    echo *** pip upgrade failed ***
    pause
    exit /b 1
)

"%PY%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo *** dependency install failed ***
    pause
    exit /b 1
)

echo [3/6] Checking syntax...
"%PY%" -m compileall -q .
if errorlevel 1 (
    echo *** compileall failed — fix syntax errors first ***
    pause
    exit /b 1
)

echo [4/6] Checking imports...
"%PY%" tools\check_imports.py
if errorlevel 1 (
    echo *** import check failed — missing modules or dependencies ***
    pause
    exit /b 1
)

echo [5/6] Building with PyInstaller (onedir, console=%CONSOLE%)...
set BONSAI_ENTRY=%ENTRY%
set BONSAI_APP_NAME=%APP_NAME%
set BONSAI_CONSOLE=%CONSOLE%

"%PY%" -m PyInstaller --clean --noconfirm bonsai.spec
if errorlevel 1 (
    echo *** PyInstaller build failed ***
    pause
    exit /b 1
)

echo [6/6] Post-build...
"%PY%" tools\post_build.py
if errorlevel 1 (
    echo *** post-build failed ***
    pause
    exit /b 1
)

echo.
echo ============================================================
echo BUILD SUCCESSFUL
echo Output: dist\%APP_NAME%\%APP_NAME%.exe
echo ============================================================
pause
