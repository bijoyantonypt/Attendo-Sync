@echo off
setlocal
cd /d "%~dp0"

python -c "import tkinter" || exit /b 1
if not exist ".build-venv\Scripts\python.exe" python -m venv .build-venv
if errorlevel 1 exit /b 1
set "BUILD_PYTHON=%CD%\.build-venv\Scripts\python.exe"
set "PYTHONPATH="
set "PYTHONHOME="
set "PYTHONNOUSERSITE=1"
set "MPLBACKEND=TkAgg"
if not defined PIP_CERT if defined CURL_CA_BUNDLE if exist "%CURL_CA_BUNDLE%" set "PIP_CERT=%CURL_CA_BUNDLE%"
"%BUILD_PYTHON%" -m pip install -r Requirements.txt || exit /b 1
"%BUILD_PYTHON%" -m unittest discover -s . -p "test_attendance_data.py" -v || exit /b 1

if not exist "Atteno_Sync_Icon.ico" if exist "Atteno_Sync_Icon.png" (
    echo Creating ICO icon from PNG source...
    "%BUILD_PYTHON%" -c "from PIL import Image; im=Image.open('Atteno_Sync_Icon.png').convert('RGBA'); s=max(im.size); c=Image.new('RGBA',(s,s),im.getpixel((5,5))); c.paste(im,((s-im.width)//2,(s-im.height)//2)); c.save('Atteno_Sync_Icon.ico',format='ICO',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
)

set "ICON_ARGS="
if exist "Atteno_Sync_Icon.ico" set ICON_ARGS=--icon="Atteno_Sync_Icon.ico" --add-data "Atteno_Sync_Icon.ico;."
if exist "Atteno_Sync_Icon.png" set ICON_ARGS=%ICON_ARGS% --add-data "Atteno_Sync_Icon.png;."

"%BUILD_PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed --name Attendo_Sync ^
    --add-data "sample_essl_attendance.json;." ^
    %ICON_ARGS% ^
    --collect-all ttkbootstrap ^
    --noupx --version-file version_info.txt ^
    --hidden-import matplotlib.backends.backend_tkagg ^
    --exclude-module clr --exclude-module pythonnet ^
    Attendo_Sync.py
if errorlevel 1 exit /b 1

if exist "dist\Attendo_Sync.exe" (
    echo.
    echo Build complete: dist\Attendo_Sync.exe
    echo Distribute only this EXE. Target PCs do not need Python or installed packages.
) else (
    echo.
    echo Build failed. Check the PyInstaller output above.
)
