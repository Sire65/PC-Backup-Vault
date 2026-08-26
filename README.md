# PC Backup Vault

Aktueller konsolidierter Quellstand: **1.7.3**.

## Windows-Anwendung

Das Programm ist eine Python/Tkinter-Desktopanwendung. Es kann lokal mit `BUILD_EXE.bat` als Windows-Anwendung gebaut werden. Zusätzlich baut GitHub Actions bei Änderungen am Programm automatisch ein Windows-Paket.

### Lokaler Start aus dem Quellcode

1. Python 3 installieren.
2. `ERSTEINRICHTUNG.bat` ausführen.
3. Danach `STARTEN.bat` verwenden.

### Windows-EXE bauen

`BUILD_EXE.bat` ausführen. Die Anwendung liegt anschließend unter:

`dist\PC_Backup_Vault\PC_Backup_Vault.exe`

## Sicherheit

Lokale Laufzeitdaten, virtuelle Python-Umgebungen, Logs, Datenbanken und lokale Konfigurationen gehören nicht ins Repository und werden über `.gitignore` ausgeschlossen.
