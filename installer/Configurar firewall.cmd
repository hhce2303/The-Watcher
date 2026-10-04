@echo off
rem Doble clic: crea o corrige las reglas de firewall de The Watcher (pide UAC).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0watcher-firewall.ps1" %*
