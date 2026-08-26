PC Backup Vault 1.6.2 - Runtime-Reparatur

Grund:
Bei kleinen Updatepaketen fehlte verification.py. Dadurch brach der Start mit
ModuleNotFoundError: No module named 'verification' ab.

Anwendung:
1. PC Backup Vault schließen.
2. Alle Dateien aus diesem Ordner in den vorhandenen Programmordner kopieren.
3. Vorhandene Dateien ersetzen.
4. .venv NICHT löschen.
5. Keine config-/Schlüssel-/Daten-Dateien werden durch dieses Paket mitgeliefert oder überschrieben.
6. STARTEN.bat ausführen.

Das Paket synchronisiert ausschließlich die Runtime-Module auf Version 1.6.2.
