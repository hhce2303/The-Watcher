@echo off
setlocal EnableDelayedExpansion
title The Watcher Setup
cd /d "%~dp0"

echo.
echo  ============================================
echo   The Watcher - Instalador
echo  ============================================
echo.

:: Check that The Watcher.exe is in the same folder
if not exist "%~dp0The Watcher.exe" (
    echo  [ERROR] No se encontro The Watcher.exe en esta carpeta.
    echo          Ejecute Setup.bat desde la carpeta de The Watcher.
    echo.
    pause
    exit /b 1
)

:: Launch the PowerShell installer with execution policy bypass so it works
:: on any Windows machine regardless of the user's ExecutionPolicy setting.
powershell.exe -NoProfile -ExecutionPolicy Bypass ^
    -File "%~dp0install.ps1"

set _exit=%errorlevel%
echo.
if %_exit% equ 0 (
    echo  Instalacion completada correctamente.
) else (
    echo  La instalacion finalizo con codigo de error: %_exit%
)
echo.
pause
exit /b %_exit%
