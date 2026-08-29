@echo off
setlocal
cd /d "%~dp0"
title PC Backup Vault 1.8.0 - EXE Build

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py"
) else (
  where python >nul 2>nul
  if %errorlevel% neq 0 (
    echo Python 3 wurde nicht gefunden.
    pause
    exit /b 1
  )
  set "PY=python"
)

if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  if errorlevel 1 goto :err
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :err
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto :err

".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --name "PC_Backup_Vault" --hidden-import "matplotlib.backends.backend_tkagg" --collect-all boto3 --collect-all botocore --collect-all qrcode --add-data "schema.sql;." --add-data "schema_core_jobs.sql;." app.py
if errorlevel 1 goto :err

echo.
echo EXE liegt unter dist\PC_Backup_Vault\PC_Backup_Vault.exe
pause
exit /b 0

:err
echo.
echo EXE-Erstellung fehlgeschlagen.
pause
exit /b 1
