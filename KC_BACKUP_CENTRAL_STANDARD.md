# KC Backup Central – Sicherheits- und Bedienstandard

Status: vorbereitender Standard. Bestehende produktive Backup-Funktionen werden dadurch nicht ersetzt oder automatisch veraendert.

## Ziel

PC Backup Vault wird schrittweise zur zentralen Backup-, Verify- und Restore-Kontrollstelle fuer KC-Programme. Jedes Programm bleibt eigenstaendig und muss auch dann weiterarbeiten koennen, wenn Backup Central, Internet, Neon oder B2 nicht erreichbar sind.

Die technische Qualitaet orientiert sich an den nachgewiesenen professionellen Funktionen des Kreuzfahrt-BackupCore und den heutigen Sicherheitsfunktionen von PC Backup Vault. Die Bedienung wird bewusst deutlich einfacher als im Kreuzfahrt-Verwalter.

## One-Touch als Standardbedienung

Die Standardansicht zeigt keine technische Backup-Konfiguration. Zentraler Einstieg ist ein grosser Button **„Jetzt sicher sichern“**.

Ein One-Touch-Lauf fuehrt intern die professionelle Sicherheitskette aus:

1. Probelauf / Preflight
2. Backup
3. Vollstaendige Verifikation
4. Sicherungspunkt / letzte bekannte gute Generation schuetzen
5. Audit / Ergebnis protokollieren

Der Benutzer bekommt eine klare Ampel:

- **GRUEN**: bereit / erfolgreich
- **GELB**: Warnung, aber kein unkontrollierter Datenverlust
- **ROT**: Blocker, Backup oder Restore wird nicht gestartet

Komplexitaet wird ueber drei Bedienebenen getrennt:

- `SIMPLE`: One-Touch, Kalender, letzte/naechste Sicherung, Fehler
- `ADVANCED`: Jobdetails, Quellen/Ziele, Retention, Verify-/Restore-Test-Planung
- `EXPERT`: technische Parameter, Diagnose, Recovery- und Infrastrukturdetails

Sichere Defaults duerfen in SIMPLE nicht versehentlich abgeschaltet werden.

## Kalender und Job-Scheduler

Geplante Sicherungen werden in Tages-, Wochen- und Monatsansicht dargestellt. Jeder Termin zeigt mindestens Programm, Uhrzeit, Jobname und Sicherheitsstufe.

Unterstuetzte Grundregeln:

- einmalig
- taeglich
- woechentlich
- monatlich

Ein sicherer Starterplan besteht aus:

- taeglicher Sicherung
- woechentlicher Vollpruefung
- monatlichem Restore-Test

Jobs koennen aktiviert/deaktiviert und spaeter verschoben oder bearbeitet werden. Das Kalendermodell plant nur Jobs; es fuehrt niemals selbststaendig destruktive Restore-Schritte aus.

## Verbindliche Prozesskette bei Sicherheitsstufe MAXIMUM

1. **PREFLIGHT / Probelauf** – nur lesen, nichts veraendern. Quellen, Lesbarkeit, Dateimenge, Zielbereitschaft und Recovery-Material pruefen. Blocker verhindern den echten Lauf.
2. **BACKUP** – verschluesselt, gehasht, transaktional protokolliert. Ein abgebrochener Lauf darf niemals als erfolgreich gelten.
3. **VERIFY** – nach erfolgreichem Backup Vollpruefung des gesicherten Payloads; verschluesselte Chunks und rekonstruierte Dateien werden per SHA-256 geprueft.
4. **RESTORE_TEST** – regelmaessige Wiederherstellung in ein separates Staging-Ziel. Niemals ungefragt in das Originalverzeichnis.
5. **RESTORE** – nur aus erfolgreich verifiziertem Stand, mit Recovery-Material und expliziter Bestaetigung. Standardmaessig kein Ueberschreiben.
6. **AUDIT** – Ergebnis, Dauer, Programm/Version, Datenmenge, Warnungen und Fehler werden append-only protokolliert.

## Uebernahme aus dem Kreuzfahrt-BackupCore

Nachgewiesene Referenzfunktionen, die beim Ausbau beruecksichtigt werden:

- eigener BackupCore
- Backup-Erzeugung
- Backup-Validierung
- Restore
- RestoreGuard mit Dry-Run-Schutz
- Sicherungspunkte
- BackupScopeCore mit 17 Sicherungsbereichen, davon 16 Pflichtbereiche
- Dokumentbezug fuer Dokumente, Schema und Verknuepfungen
- Vollsicherungs-Schema
- Backup-Freigabe-Gate
- vorbereitete Benachrichtigung/E-Mail
- eigener Systemcheck fuer Backupfunktionen

Diese Fachlogik wird uebernommen bzw. nachgebaut, die komplizierte Kreuzfahrt-Bedienoberflaeche jedoch nicht.

## Sicherheitsregeln

- AES-256-GCM fuer Backup-/Recovery-Inhalte; Schluessel niemals zusammen mit unverschluesselten Nutzdaten speichern.
- SHA-256 fuer Integritaet von Dateien/Chunks und Update-/Recovery-Artefakten.
- Secrets, DSNs und Zugangsdaten niemals in GitHub, Dashboard-Metriken oder normalen Job-Protokollen speichern.
- Recovery-Key und verschluesseltes Recovery-Paket getrennt behandeln; Notfall-Pass/QR enthaelt keine Geheimnisse.
- Mindestens zwei unabhaengige Backup-Kopien; fuer kritische KC-Daten werden drei Kopien empfohlen, davon moeglichst eine offline/immutable.
- Retention/Loeschung erst nach bestaetigter Integritaet neuerer Generationen. Kein automatisches Loeschen der letzten bekannten guten Generation.
- Restore ist destruktiver als Backup und bekommt deshalb eigene Sperren: verifizierte Quelle, separates Ziel, Vorschau, explizite Bestaetigung und nachgelagerte Integritaetspruefung.
- Backup Central darf kein Single Point of Failure fuer Kasse, DP2, Verwaltung oder andere KC-Programme sein.

## Einheitlicher KC-Jobvertrag

Alle Programme koennen spaeter folgende Jobtypen melden:

- `PREFLIGHT`
- `BACKUP`
- `VERIFY`
- `RESTORE_TEST`
- `RESTORE`

Statuswerte: `RUNNING`, `SUCCESS`, `WARN`, `FAILED`, `CANCELLED`, `BLOCKED`.

Jeder Datensatz traegt mindestens `program_id`, Programmversion, Jobtyp, Status, Start/Ende, Sicherheitsstufe, Verify-Stufe und Kennzahlen. Nutzdaten und Secrets gehoeren nicht in den zentralen Jobdatensatz.

## Einfuehrung ohne Regression

1. Standard, Scheduler und Adapter vorbereiten.
2. Vorhandene Backup-Funktionen je KC-Programm inventarisieren; Kreuzfahrt-BackupCore dient als Referenz fuer Fachfunktionen.
3. Gute vorhandene Funktionen ueber Adapter anbinden statt neu schreiben.
4. Zuerst nur Telemetrie/Status und geplante Jobs zentralisieren.
5. Backup/Verify/Restore je Programm separat testen.
6. Erst nach Restore-Test und Regression fuer das jeweilige Programm produktiv freigeben.

## Noch bewusst nicht automatisch aktiviert

- Keine zentrale Fernsteuerung produktiver KC-Programme.
- Keine automatische Migration produktiver Neon-/Supabase-Schemata.
- Kein automatisches Loeschen alter Backup-Generationen.
- Kein unbeaufsichtigtes Restore in Originalpfade.
- Keine Ersetzung bestehender KC-Verwaltung- oder Kreuzfahrt-Backupfunktionen ohne vorherige Funktionsinventur und Vergleich.
