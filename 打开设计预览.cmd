@echo off
powershell.exe -NoProfile -File "%~dp0打开设计预览.ps1"
if errorlevel 1 pause
