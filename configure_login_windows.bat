@echo off
cd /d "%~dp0"
python main.py --configure-login
if errorlevel 1 (
  echo Login configuration did not complete.
)
pause
