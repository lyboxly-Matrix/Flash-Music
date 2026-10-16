@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set PY=python
if exist "D:\Python311\python.exe" set PY=D:\Python311\python.exe

echo [Flash Music] Using: %PY%
"%PY%" -m pip install -r requirements.txt
"%PY%" -m pip install "pyinstaller>=6.0"
"%PY%" -m PyInstaller --noconfirm FlashMusic.spec

if not exist "dist\FlashMusic.exe" goto :failed
copy /Y "dist\FlashMusic.exe" "FlashMusic.exe" >nul
echo.
echo Build OK: FlashMusic.exe ^(project root^)
endlocal
exit /b 0

:failed
echo.
echo Build may have failed - check output above.
endlocal
exit /b 1
