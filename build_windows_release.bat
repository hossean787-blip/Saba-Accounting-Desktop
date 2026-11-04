@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo [1/5] Checking Windows Python runtime...
where py >nul 2>nul || (echo ERROR: Python launcher not found. & exit /b 10)
py -3 -c "import tkinter,sqlite3" || (echo ERROR: Tkinter or SQLite unavailable. & exit /b 11)
echo [2/5] Running full automated test suite...
py -3 -m unittest discover -s tests -q || (echo ERROR: Tests failed. & exit /b 12)
echo [3/5] Checking PyInstaller...
py -3 -m PyInstaller --version >nul 2>nul || (echo ERROR: Install compatible PyInstaller manually. & exit /b 13)
echo [4/5] Building Windows executable...
py -3 -m PyInstaller --clean --noconfirm --onefile --windowed --name SabaAccountingPreview ^
  --add-data "saba_accounting\schema.sql;saba_accounting" ^
  --add-data "saba_accounting\erp_schema.sql;saba_accounting" ^
  --add-data "saba_accounting\finance_schema.sql;saba_accounting" main.py
if errorlevel 1 (echo ERROR: Build failed. & exit /b 14)
if not exist "dist\SabaAccountingPreview.exe" (echo ERROR: EXE missing. & exit /b 15)
echo [5/5] Generating Windows SHA256 file...
certutil -hashfile "dist\SabaAccountingPreview.exe" SHA256 > "dist\SabaAccountingPreview.sha256.txt"
if errorlevel 1 (echo ERROR: Hash generation failed. & exit /b 16)
echo SUCCESS: Preview EXE created. Manual clean-machine tests still mandatory.
exit /b 0
