@echo off
setlocal
cd /d "%~dp0"
py -m pip install --only-binary=:all: -r requirements.txt || goto :failure
py -m PyInstaller --noconfirm --clean --onedir --windowed --noupx --name EclipticaMusicCompanion --exclude-module yt_dlp --exclude-module imageio_ffmpeg --add-data "player.html;." --add-data "unified.html;." --add-data "engine.js;." --add-data "boss_weakness_data.txt;." --add-data "LICENSE_EclipticaHUD-C.txt;." EclipticaMusic.py || goto :failure
py tools\verify_release.py dist\EclipticaMusicCompanion || goto :failure
echo EXE: dist\EclipticaMusicCompanion\EclipticaMusicCompanion.exe
echo WARNING: VirusTotal / Chrome safety status is NOT guaranteed. Run antivirus scans before distribution.
pause
exit /b 0
:failure
echo BUILD / VERIFICATION FAILED
pause
exit /b 1
