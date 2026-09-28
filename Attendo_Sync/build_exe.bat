@echo off
cd /d "%~dp0"
echo Installing dependencies...
python -m pip install -r Requirements.txt
if errorlevel 1 exit /b 1

echo Building Attendo-Sync.exe ...
python -m PyInstaller --clean --noconfirm AttendanceTracker.spec
if errorlevel 1 exit /b 1

echo.
echo Done. Find your exe in the "dist" folder.
echo IMPORTANT: Copy config.json next to Attendo-Sync.exe before running it.
pause
