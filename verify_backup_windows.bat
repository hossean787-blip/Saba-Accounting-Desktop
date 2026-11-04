@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
 echo Usage: verify_backup_windows.bat "C:\path\to\backup.sqlite3"
 exit /b 2
)
where py >nul 2>nul || (echo Python launcher not found. & exit /b 10)
py -3 main.py --verify-backup "%~1"
exit /b %errorlevel%
