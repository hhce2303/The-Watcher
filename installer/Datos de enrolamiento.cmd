@echo off
rem Doble clic: muestra y copia los datos públicos para enrolar esta estación en Daily.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0watcher-enrollment.ps1" %*
