# PC Backup Vault – Architektur und verbindliche Regeln

## 1. Isolation
Das Backup-System ist vollständig eigenständig. Es verwendet weder Tabellen,
Trigger, Replikationsslots noch Zugangsdaten der KC-Spiegelung.

- Neon-Projekt: `PC Backup Vault`
- Projekt-ID: `restless-lake-98349332`
- Datenbank: `pc_backup_vault`
- Schema: `backup_vault`

## 2. Tabellen
- `core` – Systemidentität, Schema- und App-Version
- `storage_targets` – Metadaten der Backup-Ziele; niemals Kennwörter
- `backup_jobs` – Backup-Historie pro Lauf
- `files` – Dateimetadaten, Hash, Status, Kompressionsart
- `file_chunks` – clientseitig verschlüsselte Dateiblöcke
- `restore_tests` – nachgewiesene Wiederherstellungstests
- `usage_snapshots` – Kapazitätsstatus
- `tuev_checks` – Prüfhistorie
- `architecture_rules` – versioniertes Regelwerk

## 3. Sicherheitsregeln
1. Keine KC-Tabellen oder KC-Replikation im Backup-Projekt.
2. Keine Datenbankkennwörter in Neon.
3. Verschlüsselung vor Upload mit AES-256-GCM.
4. SHA-256-Prüfung pro Datei und pro verschlüsseltem Chunk.
5. Recovery-Key außerhalb des PCs und außerhalb von Neon aufbewahren.
6. Hardlimit blockiert Uploads.
7. Wiederherstellung gilt erst nach Hashprüfung als erfolgreich.
8. Keine automatischen Hintergrund-Backups.
9. Weihnachtsmarkt-Schutz 04.–13.12. ist standardmäßig aktiv.
10. Weitere Datenbankanbieter werden als separate Profile geführt.

## 4. Kapazitätsregeln
- Warnung ab 350 MB Datenbankgröße.
- Harte Sperre ab 420 MB.
- Standardmäßig maximal 100 MB Originaldaten pro Sicherungslauf.
- Deduplizierung vor Upload.
- Kompression nur, wenn ein messbarer Vorteil entsteht.

## 5. Dashboard
Das Dashboard dient nur der Visualisierung. Es darf niemals Kennwörter oder
Schlüssel anzeigen. Namen und Pfade werden ausschließlich lokal entschlüsselt.
Wichtige Karten und Grafiken: Kapazität, Backup-Status, Geschwindigkeit,
Dateien, Verzeichnisse, Dateitypen, Restore-Tests und TÜV-Ergebnisse.

## 6. TÜV
Ein vollständiger TÜV-Lauf prüft Verbindung, Core-Version, Isolation,
Kapazität, Schlüsselstatus, Recovery-Key, Restore-Test und Schutzmodus.
Alle Ergebnisse werden in `backup_vault.tuev_checks` protokolliert.


## Sicherungsarten 1.3
- AUTO: Empfehlung aus Historie, letztem Voll-Stand, Fehlerstatus und Auswahlgröße.
- FULL: SHA-256 für jede Datei; vollständiger logischer Stand, physische Deduplizierung bleibt aktiv.
- INCREMENTAL: SHA-256 für jede Datei; unveränderte logische Pfade werden übersprungen.
- QUICK: Metadatenvergleich (Größe/mtime) vor Hashing; periodische Vollprüfung bleibt Pflichtempfehlung.
- Der logische Pfadvergleich erfolgt über HMAC und legt keinen Klartextpfad in Neon offen.

## 1.5 – Getrennte Speicherarchitektur (Neon + Backblaze B2)

- Neon bleibt die verbindliche Verwaltungsdatenbank: Core, Dateikatalog, verschlüsselte Pfade/Namen, SHA-256, Versionen, Historie, Restore-Audit, TÜV und Kapazitätsmetadaten.
- Backblaze B2 ist optionaler Object Storage für die großen, bereits lokal mit AES-256-GCM verschlüsselten Dateiblöcke.
- Vor jedem manuellen Backup kann der Benutzer wählen: Automatisch, Backblaze B2 oder Neon nur für Kleinmengen.
- Automatisch bevorzugt B2, sobald Bucket, Endpoint und Zugangsdaten vollständig eingerichtet sind.
- B2-Geheimnisse liegen ausschließlich im Windows-Anmeldetresor. In config.json stehen nur nicht geheime Angaben wie Bucket, Endpoint, Prefix und Kostenlimits.
- Jeder B2-Chunk besitzt weiterhin Nonce, Cipher-SHA-256, Größe und Objektverweis in Neon. Beim Restore wird das B2-Objekt geladen, der Cipher-Hash geprüft, lokal entschlüsselt und anschließend der vollständige Datei-SHA-256 geprüft.
- Bestehende Neon-Backups bleiben kompatibel und werden als Backend NEON weitergeführt.
- B2-Kostenschutz ist getrennt vom Neon-Core-Limit. Standardmäßig sind Warn- und Hardlimit für B2 konfigurierbar.
- Der Weihnachtsmarkt-Schutz sperrt weiterhin alle Online-Backup-/Restore-Zugriffe, unabhängig vom Payload-Backend.


## Laufzeitsteuerung 1.5.3
- Manuelle und One-Touch-Backups besitzen Pause/Fortsetzen und Abbrechen.
- Pause ist kooperativ und blockiert den Worker mit einem Event; es gibt kein Busy-Waiting.
- Ein bereits laufender Netzwerk-/Datenbankrequest wird nicht hart abgerissen, sondern am nächsten sicheren Checkpoint angehalten.
- Benutzerabbruch markiert den Job als `CANCELLED`. Unvollständige Jobdaten werden zurückgerollt; B2-Objekte des abgebrochenen Laufs werden bestmöglich entfernt.
- Pausenzeit wird aus der aktiven Laufzeit und ETA herausgerechnet.

## Backup-Pass / Notfall-Paket (1.6.0)
- Der sichtbare Backup-Pass wird als PNG für Handy oder Ausdruck erzeugt.
- Der QR-Code enthält ausschließlich nicht geheime Wiederherstellungs-Metadaten und einen Recovery-Key-Fingerprint.
- DSN, B2 Application Key, B2 Access Key und Recovery-Key dürfen niemals im sichtbaren Pass oder QR im Klartext stehen.
- Das `.pvr`-Notfall-Paket enthält die für einen neuen PC benötigten Recovery-Daten nur verschlüsselt.
- Verschlüsselung des `.pvr`: Scrypt (N=32768, r=8, p=1) + AES-256-GCM.
- Das Notfall-Passwort wird nicht gespeichert und muss getrennt aufbewahrt werden.
- Beim Import werden Zugangsdaten ausschließlich in den lokalen OS-Anmeldetresor zurückgeschrieben.


## Verifizierung und Job-Reports (1.6)
- Jeder erfolgreiche Sicherungslauf kann automatisch per Schnellprüfung kontrolliert werden.
- Schnellprüfung: Datenbankkonsistenz, Chunk-Anzahl, verschlüsselte Chunk-Hashes in Neon sowie Existenz/Größe von B2-Objekten.
- Vollprüfung: tatsächlicher Download der zum Job gespeicherten Inhalte, Prüfung des verschlüsselten Chunk-SHA-256, lokale AES-256-GCM-Entschlüsselung, Dekompression und finaler Datei-SHA-256/Größenvergleich.
- Verifizierungen werden separat in `backup_vault.backup_verifications` protokolliert.
- Job-Reports enthalten mindestens Dateizahl, Verzeichniszahl, Datenvolumen, neu gespeicherte Daten, Deduplizierungs-/Kompressionsersparnis, Chunk-Anzahl, Speichersplit Neon/B2, aktive Dauer, Durchschnitts- und Transfer-Spitzengeschwindigkeit sowie den letzten Verify-Status.
- Reportdarstellung entschlüsselt Dateinamen ausschließlich lokal.
- Große Listen müssen vertikal und horizontal scrollbar sein.


## Dashboard / Historie 1.6.1
- Semantische Statusfarben sind in allen Dashboard-Diagrammen konsistent.
- Kennzahlen und Diagramme muessen immer den aktiven Filter widerspiegeln.
- Zeitfilter: Tag/Woche/Monat/Quartal/Jahr sowie frei waehlbarer Von/Bis-Bereich.
- Zusatzfilter: Status, Sicherungsart, Speicherziel und Verify-Status.
- Suchbegriffe duerfen Dateinamen/Pfade nur nach lokaler Entschluesselung durchsuchen; Klartextnamen werden nicht nach Neon geschrieben.
- Historie und Dashboard verwenden dieselbe Filtersemantik.
- Filter-/Visualisierungsfunktionen duerfen Backup-, Restore-, Kryptografie- und Speicherroutinen nicht veraendern.

## Performance-Pipeline 1.6.2

- Backblaze-B2/S3-Client und HTTP-Verbindungspool werden innerhalb eines Laufs wiederverwendet; es wird nicht pro Chunk ein neuer Client aufgebaut.
- B2-Dateien werden mit begrenzter Parallelität verarbeitet. Standard sind 4 Worker, konfigurierbar von 1 bis 8.
- Jeder Worker liest, komprimiert falls sinnvoll, verschlüsselt mit AES-256-GCM und berechnet den SHA-256 des Ciphertexts vor dem Upload. Datenbankzugriffe bleiben im Hauptthread.
- Pause/Fortsetzen/Abbrechen bleiben kooperativ. Bereits laufende einzelne Netzwerkrequests werden nicht hart abgebrochen; der nächste sichere Checkpoint beendet den Worker.
- Erfolgreich hochgeladene B2-Objektschlüssel werden für Fehler-/Abbruchbereinigung verfolgt.
- Dateimetadaten werden vor der Upload-Phase gebündelt angelegt; fertige Dateien werden nach Abschluss ihrer Metadaten dauerhaft committed. Dadurch sinkt die Zahl der unnötigen Netzwerk-Roundtrips, ohne den abgeschlossenen Dateistand ungesichert zu lassen.
- Pro Job werden getrennte Messwerte geführt: Scan/Hash, Upload-Walltime, kumulierte lokale Verarbeitung, kumulierte B2-Requestzeit, Neon-Metadatenzeit und Workerzahl.
- PERF-001, PERF-002 und PERF-003 sind verbindliche Architekturregeln.

## Dashboard- und Statusarchitektur 1.6.3
- Diagramme dürfen nicht durch die verfügbare Notebook-Höhe komprimiert werden. Jeder Chart besitzt eine Mindesthöhe; die Tabs scrollen vertikal.
- `constrained_layout` übernimmt Randberechnung für Titel, Achsen, Ticktexte und Legenden.
- Die Hauptoberfläche zeigt dauerhaft Systemzustände für Neon, B2, lokalen Credential-Tresor, Scheduler, Verify/TÜV und KC Communication.
- Bei Neon/B2/KC zeigt eine zweite kleine LED tatsächliche Aktivität. Die Aktivität wird von Datenbank-/Objektspeicher-/Kommunikationszugriffen ausgelöst, nicht von einer künstlichen Animation.

## KC Communication Machine Bridge 1.7.0
- PC Backup Vault bleibt vollständig vom KC-Datenbestand isoliert. Die Integration ist ausschließlich eine ausgehende technische Ereignisschnittstelle.
- Verbindlicher zentraler Endpunkt ist die KC-Communication-Machine-API; `sourceProgram` lautet fest `pc-backup-vault`.
- Jedes Gerät besitzt eine lokale UUID und ein zufälliges Geräte-Token. Das Token wird ausschließlich im Betriebssystem-Tresor gespeichert und niemals in `config.json`, Neon oder Logs geschrieben.
- Neue Geräte werden registriert und über einen Pairing-Code zentral freigeschaltet.
- Zugelassene Kanäle des Fachprogramms sind Push und E-Mail. Provider, Empfänger, Vorlagen, Fallback und 0-Euro-Regeln bleiben Eigentum von KC Communication.
- Zugelassene Ereignisse umfassen u. a. Backup erfolgreich/fehlgeschlagen/abgebrochen/unterbrochen/fortgesetzt, Verify-/Restore-/TÜV-Fehler, Speichererreichbarkeit, Kapazitätswarnung/-sperre und Schedulerfehler.
- Verboten sind Backup-Payloads, Originaldateipfade, Recovery-Keys, DSNs, Datenbankpasswörter, B2-Zugangsdaten und Kommunikationstokens.

## Startprotokoll 1.6.3
- Das Startprotokoll ist für Entwicklung/Diagnose schaltbar.
- Es darf keine Zugangsdaten oder Recovery-Geheimnisse enthalten.
- Für normalen Echtbetrieb kann es deaktiviert und bei Fehlersuche wieder aktiviert werden.


## Crash-/Stromausfall-Recovery 1.7.0
- Während eines laufenden manuellen oder geplanten Backups existiert genau ein lokaler Recovery-Checkpoint. Er ist mit AES-256-GCM und dem lokalen Vault-Schlüssel geschützt.
- Der Checkpoint darf keine Originalpfade im Klartext enthalten. Manipulierte oder mit falschem Schlüssel gelesene Checkpoints müssen fehlschlagen.
- Bei normalem Erfolg, bewusstem Benutzerabbruch oder bekanntem Fehler wird der Checkpoint entfernt. Nur ein unerwarteter Prozess-/Stromabbruch lässt ihn zurück.
- Ein beim Neustart ermittelter RUNNING-Job kann als `INTERRUPTED` und `RECOVERABLE` markiert werden. `CANCELLED` und bekannte `FAILED`-Jobs sind nicht automatisch fortsetzbar.
- Resume-Jobs referenzieren den Ursprungsjob und umgekehrt. Nur bereits vollständig persistierte, unveränderte Dateien dürfen übersprungen werden; veränderte Quellen werden neu verarbeitet.
- Automatische Fortsetzung ist standardmäßig AUS. Der Weihnachtsmarkt-Schutz gilt auch für Recovery.

## Single-Instance / Schreibschutz 1.7.0
- UI und Scheduler verwenden denselben Betriebssystem-Lock. Ein zweiter Vault-Prozess darf keinen parallelen Backup-Schreiblauf beginnen.

## Dashboard-Performance / Studio 1.7.0
- Dashboard-Basisdaten werden in einem Hintergrundthread geladen; das Fenster bleibt responsiv.
- Der verschlüsselte Dateikatalog wird beim Öffnen nicht vollständig geladen oder entschlüsselt. Er wird erst für Dateisuche oder Inventaransicht nachgeladen.
- Es wird nur der aktuell sichtbare Diagramm-Tab gerendert.
- Filterbereich und Hauptfenster-Aktionsbereich sind bei typischen Desktopgrößen mehrzeilig/responsiv, damit keine Controls abgeschnitten werden.
- Studio-Abnahme prüft neben Geometrie auch semantische Backup-Button-Farben und Mehrstatus-Diagramme.
