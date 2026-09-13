@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-exe.ps1"
if errorlevel 1 exit /b 1
echo.
echo Gotovo: dist\MediaApp\MediaApp.exe
pause
