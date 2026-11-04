@echo off
setlocal
cd /d "%~dp0"
echo SABA v0.5 - Windows EXE build (Windows 10/11 recommended)
where py >nul 2>nul
if errorlevel 1 (
    echo Python Launcher is required. Install Python 3.12 or newer.
    pause
    exit /b 1
)
py -3 -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo PyInstaller not found. Install with: py -3 -m pip install pyinstaller
    echo No packages will be installed automatically.
    pause
    exit /b 1
)
py -3 -m PyInstaller --clean --noconfirm --onefile --windowed --name SabaAccountingV05 ^
    --add-data "saba_accounting\schema.sql;saba_accounting" ^
    --add-data "saba_accounting\erp_schema.sql;saba_accounting" ^
    --add-data "saba_accounting\finance_schema.sql;saba_accounting" main.py
if errorlevel 1 (
    echo BUILD FAILED. Do not distribute.
    pause
    exit /b 1
)
if not exist "dist\SabaAccountingV05.exe" (
    echo OUTPUT NOT FOUND
    pause
    exit /b 2
)
echo EXE generated but NOT quality-approved. Test on target Windows.
pause
