# KC Backup Central – Sicherheitsstandard

Status: vorbereitender Standard. Bestehende produktive Backup-Funktionen werden dadurch nicht ersetzt oder automatisch veraendert.

## Ziel

PC Backup Vault wird schrittweise zur zentralen Backup-, Verify- und Restore-Kontrollstelle fuer KC-Programme. Jedes Programm bleibt eigenstaendig und muss auch dann weiterarbeiten koennen, wenn Backup Central, Internet, Neon oder B2 nicht erreichbar sind.

## Verbindliche Prozesskette bei Sicherheitsstufe MAXIMUM

1. **PREFLIGHT / Probelauf** – nur lesen, nichts veraendern. Quellen, Lesbarkeit, Dateimenge, Zielbereitschaft und Recovery-Material pruefen. Blocker verhindern den echten Lauf.
2. **BACKUP** – verschluesselt, gehasht, transaktional protokolliert. Ein abgebrochener Lauf darf niemals als erfolgreich gelten.
3. **VERIFY** – nach erfolgreichem Backup Vollpruefung des gesicherten Payloads; verschluesselte Chunks und rekonstruierte Dateien werden per SHA-256 geprueft.
4. **RESTORE_TEST** – regelmaessige Wiederherstellung in ein separates Staging-Ziel. Niemals ungefragt in das Originalverzeichnis.
5. **RESTORE** – nur aus erfolgreich verifiziertem Stand, mit Recovery-Material und expliziter Bestaetigung. Standardmaessig kein Ueberschreiben.
6. **AUDIT** – Ergebnis, Dauer, Programm/Version, Datenmenge, Warnungen und Fehler werden append-only protokolliert.

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

1. Standard und Adapter vorbereiten.
2. Vorhandene Backup-Funktionen je KC-Programm inventarisieren – insbesondere KC Verwaltung mit seinem bestehenden Probelauf.
3. Gute vorhandene Funktionen ueber Adapter anbinden statt neu schreiben.
4. Zuerst nur Telemetrie/Status zentralisieren.
5. Backup/Verify/Restore je Programm separat testen.
6. Erst nach Restore-Test und Regression fuer das jeweilige Programm produktiv freigeben.

## Noch bewusst nicht automatisch aktiviert

- Keine zentrale Fernsteuerung produktiver KC-Programme.
- Keine automatische Migration produktiver Neon-/Supabase-Schemata.
- Kein automatisches Loeschen alter Backup-Generationen.
- Kein unbeaufsichtigtes Restore in Originalpfade.
- Keine Ersetzung bestehender KC-Verwaltung-Backupfunktionen ohne vorherige Funktionsinventur und Vergleich.
