@echo off
REM Build the Windows .exe on a Windows machine.
REM Usage: build_windows.bat
setlocal enabledelayedexpansion
cd /d "%~dp0"

set VENV_DIR=.build-venv-win
set APP_NAME=DOSCAR Plotter

echo ==^> Setting up build environment (%VENV_DIR%)
py -3 -m venv %VENV_DIR%
call %VENV_DIR%\Scripts\python -m pip install --quiet --upgrade pip
call %VENV_DIR%\Scripts\pip install --quiet -r requirements-build.txt

if not exist "packaging\icon.ico" (
    echo ==^> Generating app icon
    call %VENV_DIR%\Scripts\python packaging\make_icons.py
)

echo ==^> Running PyInstaller
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
call %VENV_DIR%\Scripts\pyinstaller packaging\doscar.spec --noconfirm --clean
if errorlevel 1 goto :error

if exist "HOW_TO_OPEN.md" (
    copy /y "HOW_TO_OPEN.md" "dist\%APP_NAME%\How To Open.txt" >nul
)

echo ==^> Zipping the build for distribution
powershell -NoProfile -Command "Compress-Archive -Path 'dist\%APP_NAME%' -DestinationPath 'dist\%APP_NAME%-windows.zip' -Force"

echo.
echo Done.
echo   Folder: dist\%APP_NAME%\
echo   Zip:    dist\%APP_NAME%-windows.zip
echo.
echo Note: this build is not code-signed. Windows SmartScreen may warn on
echo first launch ("Windows protected your PC") — click "More info" then
echo "Run anyway" to allow it (see HOW_TO_OPEN.md, also bundled in the zip
echo as "How To Open.txt").
echo If the window fails to render, install the Microsoft Edge WebView2
echo Runtime (usually already present on Windows 10/11):
echo   https://developer.microsoft.com/microsoft-edge/webview2/
goto :eof

:error
echo Build failed.
exit /b 1
