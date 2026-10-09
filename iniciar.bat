@echo off
rem Inicia a Sexta-Feira com a janela de registros aberta.
rem Para iniciar sem janela, use o atalho "Sexta-Feira" da area de trabalho.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo A Sexta-Feira ainda nao foi instalada. Rode instalar.bat primeiro.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m sexta %*
if errorlevel 1 pause
