# Projekt-Finder – 8-Sprint-Status

Stand: Feature-Branch `feature/project-finder-safe-cleanup`. `main` bleibt unverändert, bis der führende lokale PC-Backup-Vault-Quellstand eindeutig bestimmt und separat regressionsgeprüft ist.

## Sprint 1 – Chat-Inventur & Datenschutz
**Status: umgesetzt / Regression vorhanden**
- ChatGPT-Export lokal analysieren
- Entwicklungs-Chats und Findings erfassen
- Redaction/Pfadanonymisierung
- inkrementelle Zusammenführung
- kompakte sichere Analyseexports

## Sprint 2 – Entwicklungszentrale & Nachweislogik
**Status: umgesetzt / Regression vorhanden**
- konservative Ampellogik
- Chat ist kein technischer Beweis
- Git + Test + lokaler Vergleich für GREEN
- Projektübersicht und Detail-Drilldown
- exakte Chat-Provenienz an Entwicklungsfunden

## Sprint 3 – Projektidentität & Anforderungsabgleich
**Status: umgesetzt / Regression vorhanden**
- kanonische Projektnamen/Aliase
- toleranter RepoSnapshot-Import
- projektbezogener Requirement-Matcher
- Match-Index und Match-Terme als nachvollziehbare Evidenz

## Sprint 4 – Festplatten-/Projektinventur
**Status: Kern umgesetzt / lokale Integration später**
- read-only Scan
- Hash/Dubletten
- Projekt-/Versionsgruppierung
- JSON/CSV-Ausgabe
- lokale Projektinventur
- keine Cloud-Massenübertragung der Dateiliste

## Sprint 5 – Sichere Bereinigung
**Status: Kern umgesetzt / UI-Freigabefluss noch zu komplettieren**
- Löschvorschläge getrennt vom Scan
- reversible Quarantäne
- Manifest mit Quelle, Ziel, Größe, Hash, Zeitpunkt und Grund
- Restore mit Hash-Prüfung
- endgültiges Löschen nur aus Quarantäne, mit expliziter Bestätigung und Altersgrenze
- Cloud-/Planjobs besitzen keine Löschrechte

## Sprint 6 – Planjobs & Cloud-Aufträge
**Status: fortgeschritten / Anschluss an echte Cloudtabellen später**
- Analyse-only Job Runner
- Windows Task Scheduler Modell
- EXE-Sicherheitsregel: Backup-GUI wird nie blind als Hintergrundrunner benutzt
- dedizierter Runner-Einstieg
- Cloudjob-Vertrag ohne Cleanup-Recht
- Lease/Heartbeat/Terminalstatus gegen doppelte Ausführung
- Zielgerätbindung

## Sprint 7 – Git / Update-Verteilung & Recovery
**Status: Sicherheitsmodell umgesetzt / Programmintegration nach Quellstand-Abgleich**
- Git-Inventur und Update-Bereitschaft
- eindeutiger Ziel-Commit erforderlich
- grüne Tests erforderlich
- lokaler Git-Vergleich zwingend: MATCH oder GIT_NEWER
- LOCAL_NEWER wird als mögliche Entwicklung geschützt und blockiert Updates
- DIVERGED erzwingt Vergleich und blockiert Updates
- versionierte Download-/Release-Quelle erforderlich
- CURRENT wird von READY unterschieden
- Recovery-Entscheidung getrennt von Update-Bereitschaft
- kein stilles automatisches Installieren
- kein Überschreiben lokaler neuerer/abweichender Entwicklung
- Rollback wird bevorzugt
- Aktivierung in bestehenden Programmen erst nach eindeutiger Bestimmung ihres führenden Quellstands

## Sprint 8 – Integration, TÜV, Regression, Übergabe
**Status: bewusst gesperrt bis Quellstand-Abgleich**
Vor Merge in `main` erforderlich:
1. führenden lokalen PC-Backup-Vault-GUI-Quellstand finden
2. lokalen Stand gegen Git vergleichen
3. Projekt-Finder als neuen Tab integrieren, ohne Backupkern/B2-Verhalten zu ändern
4. Backup Start/Pause/Fortsetzen regressionsprüfen
5. Dashboard/TÜV/KC-Communication regressionsprüfen
6. Windows-Build des dedizierten Runners prüfen
7. Quarantäne/Restore/Purge E2E prüfen
8. erst danach Merge-/Release-Entscheidung

## Unverrückbare Schutzregeln
- keine simulierten Produktionsdaten
- Scan standardmäßig read-only
- kein automatisches permanentes Löschen aus Cloudjobs oder Planjobs
- `LOCAL_NEWER`/`DIVERGED` darf nicht durch grünen Git-Test überdeckt werden
- Chat-Behauptung allein macht nie GREEN
- B2-Backupkern bleibt bis zur Integrationsabnahme unangetastet
