@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title PC Backup Vault 1.7.1 - Ersteinrichtung

echo ================================================================
echo PC BACKUP VAULT 1.7.1 - ERSTEINRICHTUNG
echo ================================================================
echo.
echo Dieses Programm baut die lokale Python-Umgebung neu auf.
echo Es loescht KEINE Sicherungen, Datenbankdaten oder Einstellungen.
echo.

if exist ".venv" (
  echo Alte lokale Python-Umgebung wird entfernt...
  rmdir /s /q ".venv"
)

call STARTEN.bat
exit /b %errorlevel%
