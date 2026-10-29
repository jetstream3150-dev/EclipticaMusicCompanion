@echo off
setlocal
cd /d "%~dp0"
py -3.14 -c "import sys; assert sys.version_info >= (3, 14, 10), 'Python 3.14.10 or newer is required'" || goto :failure
py -3.14 -m pip install --only-binary=:all: -r requirements.txt || goto :failure
py -3.14 -m tools.generate_demo_tracks || goto :failure
py -3.14 -m PyInstaller --noconfirm --clean --onedir --windowed --noupx --name EclipticaMusicCompanion --exclude-module yt_dlp --exclude-module imageio_ffmpeg --collect-all openvr --add-data "player.html;." --add-data "unified.html;." --add-data "engine.js;." --add-data "demo_audio;demo_audio" --add-data "party.js;." --add-data "boss_weakness_data.txt;." --add-data "LICENSE_EclipticaHUD-C.txt;." EclipticaMusic.py || goto :failure
py -3.14 tools\verify_release.py dist\EclipticaMusicCompanion || goto :failure
echo EXE: dist\EclipticaMusicCompanion\EclipticaMusicCompanion.exe
echo WARNING: VirusTotal / Chrome safety status is NOT guaranteed. Run antivirus scans before distribution.
pause
exit /b 0
:failure
echo BUILD / VERIFICATION FAILED
pause
exit /b 1
