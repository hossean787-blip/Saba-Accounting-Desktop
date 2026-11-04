@echo off
setlocal
cd /d "%~dp0"
if "%~2"=="" (
 echo Usage: restore_backup_windows.bat "C:\backup.sqlite3" "C:\new-recovered.sqlite3"
 echo The destination MUST NOT already exist.
 exit /b 2
)
where py >nul 2>nul || (echo Python launcher not found. & exit /b 10)
py -3 main.py --restore-backup "%~1" --restore-to "%~2"
exit /b %errorlevel%
