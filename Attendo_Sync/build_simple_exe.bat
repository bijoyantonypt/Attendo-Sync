@echo off
cd /d "%~dp0"

call ..\venv\Scripts\activate.bat

pyinstaller --onefile --windowed --name AttendoSyncSimple simple_exe_app.py

if exist "dist\AttendoSyncSimple.exe" (
    echo.
    echo Build complete: dist\AttendoSyncSimple.exe
) else (
    echo.
    echo Build failed. Check the PyInstaller output above.
)
