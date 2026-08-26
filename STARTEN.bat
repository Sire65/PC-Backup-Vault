@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title PC Backup Vault 1.7.1 - Start

set "LOG=%~dp0STARTFEHLER.log"
set "SETUPLOG=%~dp0EINRICHTUNG.log"
if exist "%LOG%" del /q "%LOG%" >nul 2>nul

echo ================================================================
echo PC BACKUP VAULT 1.7.1
echo ================================================================
echo.
echo Startpruefung laeuft...
echo.

if not exist "requirements.txt" goto :not_extracted
if not exist "app.py" goto :not_extracted
if not exist "ui.py" goto :not_extracted
if not exist "schema.sql" goto :not_extracted

REM Python finden
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto :no_python

echo [1/6] Python gefunden:
%PY% --version
if errorlevel 1 goto :no_python

REM Tkinter pruefen - gehoert zur normalen Windows-Pythoninstallation
echo [2/6] Windows-GUI (Tkinter) pruefen...
%PY% -c "import tkinter; print('      Tkinter: OK')" 2>>"%SETUPLOG%"
if errorlevel 1 goto :no_tkinter

set "VENV=%~dp0.venv"
if not exist "%VENV%\Scripts\python.exe" (
  echo [3/6] Python-Umgebung wird einmalig erstellt...
  echo       Das kann beim ersten Start einige Minuten dauern.
  %PY% -m venv "%VENV%" >>"%SETUPLOG%" 2>&1
  if errorlevel 1 goto :setup_err
) else (
  echo [3/6] Python-Umgebung vorhanden.
)

echo [4/6] Paketverwaltung pruefen...
"%VENV%\Scripts\python.exe" -m pip --version >nul 2>>"%SETUPLOG%"
if errorlevel 1 (
  "%VENV%\Scripts\python.exe" -m ensurepip --upgrade >>"%SETUPLOG%" 2>&1
  if errorlevel 1 goto :setup_err
)

REM Erst pruefen, dann nur bei Bedarf installieren.
echo [5/6] Benoetigte Programmpakete pruefen...
"%VENV%\Scripts\python.exe" -c "import psycopg, cryptography, keyring, matplotlib, boto3, qrcode, tkinter" >nul 2>>"%SETUPLOG%"
if errorlevel 1 (
  echo.
  echo       Komponenten fehlen. Installation wird jetzt ausgefuehrt.
  echo       Bitte dieses Fenster NICHT schliessen.
  echo.
  "%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
  if errorlevel 1 goto :setup_err
) else (
  echo       Alle Python-Komponenten: OK
)

echo [6/6] PC Backup Vault wird geprueft und gestartet...
"%VENV%\Scripts\python.exe" -c "import ui; print('      Programmimport: OK')" 2>"%LOG%"
if errorlevel 1 goto :app_err
if exist "%LOG%" del /q "%LOG%" >nul 2>nul

echo.
echo ================================================================
echo Einrichtung OK - Programm startet jetzt.
echo ================================================================
echo.

"%VENV%\Scripts\python.exe" -X faulthandler "%~dp0app.py" 2>"%LOG%"
set "APP_RC=%ERRORLEVEL%"
if not "%APP_RC%"=="0" goto :app_err
if exist "%LOG%" del /q "%LOG%" >nul 2>nul
exit /b 0

:app_err
echo.
echo ================================================================
echo PC BACKUP VAULT KONNTE NICHT GESTARTET WERDEN
echo ================================================================
echo.
echo Fehlerprotokoll:
echo %LOG%
echo.
if exist "%LOG%" type "%LOG%"
echo.
echo Dieses Fenster bleibt offen.
pause
exit /b 10

:not_extracted
echo.
echo FEHLER: ZIP wurde nicht vollstaendig entpackt.
echo STARTEN.bat muss zusammen mit app.py, ui.py, schema.sql und
echo requirements.txt im gleichen Ordner liegen.
echo.
pause
exit /b 2

:no_python
echo.
echo ================================================================
echo PYTHON 3 WURDE NICHT GEFUNDEN
echo ================================================================
echo.
echo Benoetigt wird eine normale 64-Bit-Python-3-Installation fuer Windows
echo inklusive "py launcher" und Tcl/Tk.
echo.
echo Danach STARTEN.bat erneut doppelklicken.
echo.
pause
exit /b 3

:no_tkinter
echo.
echo ================================================================
echo PYTHON IST VORHANDEN, ABER TKINTER FEHLT
echo ================================================================
echo.
echo PC Backup Vault braucht die Windows-GUI-Komponente Tcl/Tk.
echo Bitte Python reparieren/neu installieren und Tcl/Tk mit installieren.
echo.
echo Details stehen in:
echo %SETUPLOG%
echo.
pause
exit /b 5

:setup_err
echo.
echo ================================================================
echo EINRICHTUNG DER PYTHON-UMGEBUNG FEHLGESCHLAGEN
echo ================================================================
echo.
echo Details stehen in:
echo %SETUPLOG%
echo.
if exist "%SETUPLOG%" type "%SETUPLOG%"
echo.
echo Dieses Fenster bleibt offen.
pause
exit /b 4
