# Projekt-Finder – Speicher-, Job- und Backup-Architektur

## Ziel
Der Projekt-Finder soll große lokale Entwicklungsbestände (auch 9.000+ Dateien) analysieren, ohne die Cloud mit Dateilisten und Hashes zu füllen und ohne das bestehende Backup-Verhalten zu verändern.

## Feste Trennung

### Lokal auf dem PC
- Vollständiges Inventar aller gefundenen Dateien
- Pfade, Größen, Zeitstempel, Versionshinweise
- SHA-256-Hashes und Dublettenbeziehungen
- Cleanup-Vorschläge
- Quarantäne-Manifeste und Wiederherstellung
- Detailberichte JSON/CSV
- Scheduler-Ausführung und lokale Job-Logs

Diese Daten bleiben standardmäßig lokal.

### Supabase – Steuerzentrale
Supabase erhält ausschließlich kleine Steuer- und Statusdaten:
- Job-ID und Zielgerät
- Profilname und Suchbereiche
- geplant / wartet / läuft / fertig / Fehler
- Fortschritt in groben Intervallen
- Anzahl Dateien, Dubletten, Prüfkandidaten
- geschätzter bzw. potenziell freiwerdender Speicher
- höchstens eine kleine Auswahl relevanter Funde

Keine vollständige 9.000-Dateien-Liste, keine komplette Hash-Datenbank.

### Neon – Failover/Spiegel der Steuerdaten
Neon dient für die kleinen Job-/Statusdaten als Ausweich- bzw. Spiegelweg. Es ist kein Speicherziel für das lokale Dateiinventar. Fällt Supabase aus, kann der Agent Status/Jobsteuerung über den vorgesehenen Failover-Weg weiterführen bzw. später abgleichen.

### B2 – Backup-Nutzdaten
B2 bleibt der Ort für echte Backup-Daten und größere Sicherungspakete.

Optional kann vor einer später freigegebenen Bereinigung ein Sicherheits-Snapshot bzw. ein kompaktes Sicherungspaket nach B2 geschrieben werden. Erst nach bestätigtem Backup darf eine lokale Bereinigungsfreigabe umgesetzt werden.

## Sicherheitsregeln
1. Unbeaufsichtigte/Scheduler-Jobs analysieren nur.
2. Cloud-Jobs dürfen `allow_cleanup=true` nicht akzeptieren.
3. Keine automatische irreversible Löschung.
4. Bereinigung zuerst Quarantäne, mit Manifest und Restore-Möglichkeit.
5. Endgültiges Löschen ist ein separater, expliziter Schritt.
6. Vor größeren Bereinigungen kann optional B2-Sicherung Pflicht werden.
7. Das Backup-Modul selbst bleibt unverändert; Projekt-Finder wird als isolierte Zusatzfunktion angebunden.

## Offline-Verhalten
Ein Cloud-Job kann geplant werden, während der PC aus ist. Er bleibt `QUEUED`. Sobald der lokale Agent wieder läuft, holt er den Auftrag und startet ihn gemäß Profil. Ohne laufenden PC ist kein Zugriff auf lokale Laufwerke möglich.

## One-Touch-Profile
Vorgesehen:
- USB-Stick komplett prüfen
- KC-Entwicklung Tiefenscan
- Dubletten suchen
- Alte Versionen prüfen
- Schnellscan
- Über-Nacht-Tiefenscan

## Geplante Bedienlogik
`Planen -> PC/Agent übernimmt -> lokal analysieren -> kompakten Status an Supabase/Neon -> Detailbericht lokal -> Bewertung -> optional B2-Sicherung -> Quarantäne -> später endgültig löschen`
