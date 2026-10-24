@echo off
REM === Bonsai Control Panel — Windows build ===
setlocal

echo [1/3] Installing build dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo [2/3] Cleaning previous build...
if exist build rmdir /S /Q build
if exist dist  rmdir /S /Q dist

echo [3/3] Running PyInstaller...
python -m PyInstaller --clean --noconfirm bonsai.spec

if errorlevel 1 (
    echo.
    echo *** BUILD FAILED ***
    pause
    exit /b 1
)

echo.
echo === DONE ===
echo Output: dist\BonsaiControlPanel\BonsaiControlPanel.exe
pause
