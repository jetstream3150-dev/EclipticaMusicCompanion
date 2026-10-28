@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=0"
py -3.14 -c "import sys, tkinter; assert (3,14,10) <= sys.version_info[:3] < (3,15,0)" >nul 2>&1
if errorlevel 1 goto missing
py -3.14 "%~dp0build_personal_exe.py"
set "BUILD_RESULT=%ERRORLEVEL%"
if not "%BUILD_RESULT%"=="0" echo Build failed. Please share the displayed message.
echo.
pause
exit /b %BUILD_RESULT%
:missing
echo Python 3.14.10 or newer in the 3.14 series with Tkinter is required.
echo Please open README_FIRST.txt for installation instructions.
pause
exit /b 1
