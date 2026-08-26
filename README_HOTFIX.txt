PC Backup Vault 1.6.2 – Dashboard/Schema-Hotfix

Behebt den Fehler:
  column "directory_count" does not exist

Ursache:
Programm 1.6.2 lief gegen einen noch nicht auf 1.6.x aktualisierten Neon-Core.

Installation:
1. PC Backup Vault schließen.
2. vault_db.py und dashboard_window.py in den bestehenden Programmordner kopieren.
3. Vorhandene Dateien ersetzen.
4. STARTEN.bat starten.

Das Dashboard läuft danach auch mit Core 1.5.1 im Kompatibilitätsmodus.
Anschließend einmal Schema/Core prüfen, damit alle neuen 1.6.x-Kennzahlen und Verify-Funktionen verfügbar sind.

Keine Konfiguration, Schlüssel, .venv, Backups oder B2-Daten werden verändert.
