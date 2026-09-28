@echo off
cd /d "%~dp0"

call ..\venv\Scripts\activate.bat

if not exist "Atteno_Sync_Icon.ico" (
    echo Creating ICO icon from PNG source...
    python -c "from pathlib import Path; from PIL import Image; img = Image.open('Atteno_Sync_Icon.png'); img.save('Atteno_Sync_Icon.ico', format='ICO')"
)

pyinstaller --onefile --windowed --icon=Atteno_Sync_Icon.ico --name AttendoSyncSimple simple_exe_app.py

if exist "dist\AttendoSyncSimple.exe" (
    echo.
    echo Build complete: dist\AttendoSyncSimple.exe
) else (
    echo.
    echo Build failed. Check the PyInstaller output above.
)
