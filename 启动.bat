@echo off
cd /d "%~dp0"
chcp 65001 >nul

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launcher.ps1"
if %errorlevel% neq 0 (
    echo.
    echo Error occurred. Press any key to exit.
    pause
)
