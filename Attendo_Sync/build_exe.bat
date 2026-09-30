@echo off
cd /d "%~dp0"

call ..\venv\Scripts\activate.bat

pip install -r Requirements.txt

if not exist "Atteno_Sync_Icon.ico" (
    echo Creating ICO icon from PNG source...
    python -c "from PIL import Image; im=Image.open('Atteno_Sync_Icon.png').convert('RGBA'); s=max(im.size); c=Image.new('RGBA',(s,s),im.getpixel((5,5))); c.paste(im,((s-im.width)//2,(s-im.height)//2)); c.save('Atteno_Sync_Icon.ico',format='ICO',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
)

pyinstaller --onefile --windowed --icon=Atteno_Sync_Icon.ico --name Attendo_Sync ^
    --add-data "sample_essl_attendance.json;." ^
    --add-data "Atteno_Sync_Icon.ico;." ^
    --add-data "Atteno_Sync_Icon.png;." ^
    --exclude-module clr --exclude-module pythonnet ^
    Attendo_Sync.py

if exist "dist\Attendo_Sync.exe" (
    echo.
    echo Build complete: dist\Attendo_Sync.exe
) else (
    echo.
    echo Build failed. Check the PyInstaller output above.
)
