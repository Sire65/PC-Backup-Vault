PC BACKUP VAULT 1.7.0
=====================

Neu in 1.2
----------
- Backup-Explorer wie ein Dateibrowser: Ordnerbaum, Suche, Einzel-/Mehrfachauswahl.
- Ganze Ordner oder einzelne Dateien wiederherstellen.
- Wahlweise ursprüngliche Ordnerstruktur im Zielordner beibehalten.
- Keine stille Überschreibung: vorhandene Dateien erhalten _restore_1, _restore_2 usw.
- One-Touch-Pläne mit fest vorgegebenen Verzeichnissen/Dateien.
- Windows Scheduler: Manuell, täglich, wöchentlich oder bei Windows-Anmeldung.
- Scheduler enthält niemals Neon-Passwort, Connection String oder Recovery-Key.
- Zusätzliche TÜV-Prüfung für Deduplikationsquellen und Scheduler-Geheimnisse.
- Deduplikations-Restore korrigiert: Kompressionsart wird von der tatsächlichen gespeicherten Quelle übernommen.

Neon-Isolation
--------------
Projekt: PC Backup Vault
Projekt-ID: restless-lake-98349332
Datenbank: pc_backup_vault
Schema: backup_vault
Schema-Version: 1.7.0

Das Projekt ist vollständig getrennt von KC Core Mirror und allen KC-Programmen.

Sicherheit
----------
- AES-256-GCM vor dem Upload.
- SHA-256 je Originaldatei und je verschlüsseltem Chunk.
- Datenbankzugang im Betriebssystem-Anmeldetresor (keyring), nicht in config.json.
- Recovery-Key nicht in Neon.
- Warnlimit 350 MB, Hardlimit 420 MB.
- Standard-Laufgrenze 100 MB Originaldaten, im Zahnrad änderbar.
- Unveränderte bzw. identische Dateien werden nicht erneut als Payload hochgeladen.
- Weihnachtsmarkt-Schutz 04.–13.12. standardmäßig aktiv.
- Keine automatische Löschung alter Backups. Bei Platzmangel wird blockiert.

Erster Start
------------
1. STARTEN.bat ausführen.
2. Zahnrad > Datenbanken > Neon PC Backup Vault.
3. Neon Connection String einmalig hinterlegen und Verbindung testen.
4. Recovery-Key exportieren und getrennt aufbewahren.
5. TÜV prüfen.
6. Optional Zahnrad > One-Touch / Scheduler: feste Quellordner anlegen.
7. Gewünschten Scheduler-Typ auswählen und Scheduler installieren.

Backup-Explorer
---------------
Über "Backup-Explorer" werden die in Neon gesicherten Verzeichnisse lokal entschlüsselt
und als Ordnerbaum angezeigt. Einzelne Dateien, mehrere Dateien oder ganze Ordner können
markiert und in einen frei wählbaren Zielordner zurückgeholt werden. Nach jeder
Wiederherstellung wird SHA-256 geprüft und das Ergebnis im Restore-Test protokolliert.

Scheduler
---------
Die Windows-Aufgabe startet nur:
  PC Backup Vault --run-plan <Plan-ID>
Zugangsdaten und Verschlüsselungsschlüssel werden nicht als Parameter übergeben.
Der geplante Lauf verwendet dieselben Kapazitäts-, Weihnachtsmarkt-, Verschlüsselungs-
und Deduplikationsregeln wie ein manueller Lauf.


Dashboard
---------
Neu in 1.2: Dashboard mit Kennzahlen und Diagrammen. Angezeigt werden u. a.
Backup-Status, Dateien, Verzeichnisse, Geschwindigkeit, Kapazität, Dateitypen,
Restore-Tests, TÜV-Ergebnisse und Verlauf der Datenbankgröße.


Sicherungsarten 1.3
------------------
Empfohlen (automatisch): Programm wertet Historie und Auswahl aus und schlägt den passenden Modus vor.
Vollständig: sicherste Vollprüfung; jede Datei wird gehasht. Identische Inhalte werden trotzdem dedupliziert.
Inkrementell: jede Datei wird gehasht; nur neue oder geänderte Dateien erzeugen eine neue Version.
Schnell: unveränderte Dateien werden zuerst über Größe und Änderungszeit erkannt; nur geänderte/verdächtige Dateien werden gehasht.

Empfehlungsregeln: kein Voll-Stand oder letzter Lauf fehlerhaft -> Vollständig; Voll-Stand älter als 14 Tage -> Vollständig; normale Nutzung -> Inkrementell; sehr viele Dateien bei frischem Voll-Stand -> Schnell.


Bedienung 1.4
-------------
Pflichtfelder sind mit einem roten Sternchen markiert. Unvollständige oder
unplausible Einstellungen können nicht gespeichert werden. Die Oberfläche ist
in Sicherung, Übersicht/Wiederherstellung sowie logisch getrennte
Einstellungsbereiche gegliedert.


SPEICHERARCHITEKTUR AB 1.5
--------------------------
Neon speichert Core, Dateikatalog, Prüfsummen, Historie, Versionen und TÜV.
Große verschlüsselte Dateiblöcke können in Backblaze B2 gespeichert werden.
Im Hauptfenster steht dafür die Auswahl "Speicherziel" bereit.

Automatisch (empfohlen): B2 wenn eingerichtet, sonst Neon-Kleinbackup.
Backblaze B2: Dateiblöcke nach lokaler AES-256-GCM-Verschlüsselung in B2.
Neon – nur Kleinmengen: Dateiblöcke weiterhin direkt in Neon, mit dem eingestellten Lauf-/Kapazitätsschutz.

B2-Zugangsdaten werden ausschließlich im Windows-Anmeldetresor gespeichert.


Pause / Fortsetzen / Abbrechen (ab 1.5.3)
------------------------------------------
Während manueller und One-Touch-Sicherungen stehen im Live-Status die Tasten
Pause/Fortsetzen und Abbrechen zur Verfügung. Pause hält die eigentliche
Hash-/Dateiarbeit an sicheren Checkpoints an. Ein bereits laufender einzelner
B2-Request wird sauber abgeschlossen. Abbrechen setzt den Lauf auf CANCELLED
und rollt unvollständige Daten soweit möglich zurück.

BACKUP-PASS / NOTFALL-WIEDERHERSTELLUNG (ab 1.6.0)
---------------------------------------------------
Unter Einstellungen > Sicherheit / Core kann ein Backup-Pass plus verschlüsseltes Notfall-Paket erstellt werden.
Der PNG-Pass ist fürs Handy/Print und enthält keine Passwörter oder Schlüssel.
Das .pvr-Paket enthält die notwendigen Recovery-Daten stark verschlüsselt und kann z.B. zusätzlich auf Handy oder USB-Stick liegen.
Das persönliche Notfall-Passwort wird nie gespeichert.
Auf einem neuen PC: Notfall-Paket importieren, Verbindungen testen, Backup-Explorer öffnen und Dateien/Ordner wiederherstellen.


Verifizierung / Backup-Report (1.6)
----------------------------------
- Button „Letzte Sicherung prüfen“ mit Schnell- und Vollprüfung.
- Schnellprüfung kontrolliert Katalog, Chunks und B2-Objekte ohne kompletten Download.
- Vollprüfung lädt die gespeicherten Inhalte, prüft Chunk-SHA-256, entschlüsselt lokal und vergleicht Datei-SHA-256.
- Nach erfolgreichen Backups wird standardmäßig eine Schnellprüfung ausgeführt.
- Nach jedem erfolgreichen manuellen/One-Touch-Lauf öffnet sich ein ausführlicher Job-Report.
- Reports können später über Historie erneut geöffnet sowie als TXT/CSV gespeichert werden.
- Dateilisten, Explorer, Historie und TÜV besitzen horizontale und vertikale Scrollleisten.


Recovery / Systemstatus / KC Communication 1.7.0
------------------------------------------------
- Unerwartete Strom-/Prozessabbrüche hinterlassen einen lokal mit AES-256-GCM verschlüsselten Recovery-Checkpoint. Beim nächsten Start wird die unterbrochene Sicherung erkannt und kann fortgesetzt, später bearbeitet oder verworfen werden.
- Manuell abgebrochene bzw. bekannte fehlgeschlagene Läufe werden nicht automatisch als fortsetzbar behandelt.
- Fortgesetzte Läufe verknüpfen Ursprungs- und Folgejob; bereits vollständig gespeicherte und unveränderte Dateien werden sicher wiederverwendet. Geänderte Quelldateien werden neu verarbeitet.
- Ein OS-Single-Instance-Lock verhindert, dass Oberfläche und Scheduler gleichzeitig in denselben Vault schreiben.
- Die obere Statusleiste zeigt Neon, B2, Tresor, Scheduler, Verify/TÜV und KC Communication; Datenverkehr wird zusätzlich angezeigt.
- Der Backup-Startbutton ist zugleich Bereitschaftsanzeige: grün=bereit, orange=Warnung/noch nicht bereit, rot=blockiert, blau=Backup läuft.
- Dashboard lädt Job-/Kennzahlen im Hintergrund. Der große Dateikatalog wird erst bei Dateisuche oder im Tab Dateien/Verzeichnisse geladen und lokal entschlüsselt.
- KC Communication verwendet die zentrale `kc-communication-machine`-Schnittstelle. Geräte-ID wird lokal erzeugt, das Geräte-Token liegt nur im Windows-Anmeldetresor, und die Kopplung erfolgt per Pairing-Code.
- An KC Communication dürfen ausschließlich technische Ereignismetadaten übertragen werden; Backup-Inhalte, Originalpfade, Recovery-Key, Neon-DSN und B2-Zugangsdaten sind verboten.
