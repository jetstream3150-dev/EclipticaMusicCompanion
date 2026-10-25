@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt
py -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all webview --name EclipticaMusicCompanion --add-data "player.html;." EclipticaMusic.py
echo EXE: dist\EclipticaMusicCompanion.exe
pause
