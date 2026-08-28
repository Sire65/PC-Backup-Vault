@echo off
setlocal
chcp 65001 >nul
title PC Backup Vault - Projekt-Finder Vorschau
set "DIR=%~dp0PC-Backup-Vault-Vorschau"
where py >nul 2>nul && (set "PY=py") || (set "PY=python")
where git >nul 2>nul || goto :nogit
if not exist "%DIR%\.git" (
  git clone --depth 1 --branch feature/project-finder-safe-cleanup https://github.com/Sire65/PC-Backup-Vault.git "%DIR%" || goto :fail
) else (
  git -C "%DIR%" fetch origin feature/project-finder-safe-cleanup || goto :fail
  git -C "%DIR%" checkout feature/project-finder-safe-cleanup || goto :fail
  git -C "%DIR%" pull --ff-only origin feature/project-finder-safe-cleanup || goto :fail
)
cd /d "%DIR%"
%PY% PROJECT_FINDER_VORSCHAU.py
if errorlevel 1 goto :nopy
exit /b 0
:nogit
echo Git fuer Windows fehlt. Bitte Git installieren und erneut starten.
pause
exit /b 2
:nopy
echo Python 3 mit Tkinter konnte nicht gestartet werden.
pause
exit /b 3
:fail
echo Vorschau konnte nicht aus GitHub geladen werden.
pause
exit /b 4
