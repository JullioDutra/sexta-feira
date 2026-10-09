@echo off
rem Instalador da Sexta-Feira - clique duas vezes neste arquivo.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar.ps1"
echo.
pause
