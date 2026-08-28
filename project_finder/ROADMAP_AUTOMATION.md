# Projekt-Finder – One-Touch, Planjobs und sichere Automatisierung

## Ziel
Der Projekt-Finder wird in PC Backup Vault integriert, ohne die bestehende Backup-Logik zu verändern. Große Analysen mit vielen tausend Dateien sollen unbeaufsichtigt laufen können.

## One-Touch-Profile
Vorgesehene Schnellaktionen:

- **USB-Stick komplett prüfen** – vollständige Metadateninventur, relevante Hashes, Dublettenerkennung.
- **Nur KC-Entwicklung** – Fokus auf KC-, DP2-, Kasse-, Futura-, Verwaltung-, Communication-, Backup- und Manager-Projekte.
- **Nur alte Versionen/Dubletten** – priorisiert Versionsnamen, Archive und bit-identische Dubletten.
- **Schnellscan** – Metadaten zuerst, Hashes nur für besonders relevante Kandidaten.
- **Tiefenscan über Nacht** – größere Hash-Grenze und vollständige Projektanalyse.

## Planjobs / Scheduler
Die Windows-Aufgabenplanung kann Analysejobs ausführen, auch wenn die Oberfläche nicht geöffnet ist. Ein Profil enthält Suchbereiche und Scanregeln. Der Job Runner schreibt jeden Lauf in einen eigenen Ergebnisordner mit:

- `inventory.json`
- `inventory.csv`
- `cleanup-proposals.json`
- `summary.json`
- `status.json`
- `job.log`

Wichtig: geplante Jobs sind standardmäßig **Analyse-only**. Sie löschen und verschieben keine Dateien automatisch.

## Sicherheitsmodell
1. Scan = immer lesen.
2. Löschvorschläge = automatisch möglich.
3. Quarantäne = nur nach expliziter Freigabe oder später optional über ein separat bestätigtes Regelwerk.
4. Endgültiges Löschen = eigener Schritt mit Wartefrist und Protokoll.
5. Aktuelle/führende Projektstände dürfen nie allein aufgrund des Dateinamens als löschbar gelten.
6. Bit-identische Dubletten bleiben die höchste automatische Vertrauensstufe.

## Spätere Komfortfunktionen
- Dashboard-Kachel „Nächster Analysejob“.
- Verlauf der letzten Jobs mit grün/gelb/rot Status.
- One-Touch „Heute Nacht Tiefenscan“.
- Ruhezeit-/CPU-/Datenträgerlast-Limit.
- Pause bei Akkubetrieb und Fortsetzung bei Netzbetrieb.
- Optional nur starten, wenn das Ziellaufwerk/USB-Laufwerk vorhanden ist.
- Speicherplatz-Prognose vor und nach vorgeschlagener Bereinigung.
- Top-20 größte Dubletten/Altstände.
- Projektgruppenansicht: gleiche Anwendung, mehrere Versionen nebeneinander.
- Vergleich mit GitHub-Metadaten/führendem Stand über exportierbares Analysepaket.
- `.kcscan` Auftragsdateien aus Chat/Clipboard.
- Benachrichtigung nach Abschluss über die bestehende KC-Communication-Anbindung, sobald diese Integration separat abgenommen wurde.

## Keine Regression am Backup
Der gesamte Projekt-Finder liegt zunächst in `project_finder/` und auf einem isolierten Feature-Branch. Eine Einbindung in die bestehende Backup-GUI erfolgt erst nach Abgleich mit dem führenden PC-Backup-Vault-Quellstand und separater Regression von Backup-Start, Pause, Fortsetzen, Dashboard, TÜV und Kommunikationsstatus.
