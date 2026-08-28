# KC Projektstatus – PC Backup Vault

Stand: 2026-08-28
Branch: `feature/project-finder-safe-cleanup`
Produktivzweig: `main` unverändert

## Aktueller Entwicklungsstatus

- Project-Finder als isolierter Zusatzbereich implementiert.
- Windows-Sichtungsversion wird automatisch gebaut.
- Project-Finder Regression zuletzt grün.
- Vollständiger Quellbaum-Vergleich mit relativen Pfaden und SHA256 implementiert.
- Pflichtdateien oder gleiche Dateizahl allein gelten ausdrücklich nicht als Identitätsnachweis.
- Release-/Merge-Freigabe bleibt beweisgebunden und automatisch gesperrt.

## Verifizierte Git-Referenz

- Version: 1.7.3
- Referenzbranch: `import-1.7.3-clean`
- Referenzcommit: `bb7e6b51e13bb0f60c54508befb53239f221e4c9`
- Erwartete Dateizahl: 59
- Referenzarchiv SHA256: `7224d7cf3aacc104036d9aec70f236a03cac6d7a56328c3911d186314e4dfc62`

Diese Referenz ist **nicht automatisch der führende lokale Benutzerstand**.

## Noch zwingend vor produktiver Integration

1. Führenden lokalen PC-Backup-Vault-Quellstand bestimmen.
2. Vollständigen lokalen Quellbaum gegen die verifizierte Git-Referenz vergleichen.
3. Backup Start regressionsprüfen.
4. Pause/Fortsetzen regressionsprüfen.
5. B2-Verhalten regressionsprüfen.
6. Dashboard/TÜV regressionsprüfen.
7. KC-Communication-Anbindung regressionsprüfen.
8. Dedizierten Windows-Runner prüfen.
9. Quarantäne/Restore/Purge E2E prüfen.
10. Gesamtes Integrationsgate mit technischer Evidenz grün abschließen.

## Sicherheitsregeln

- Kein automatischer Merge nach `main`.
- Kein automatisches Release.
- Backup-Kern darf durch Project-Finder-Arbeiten nicht verändert werden.
- Lokale neuere oder abweichende Stände werden geschützt und niemals blind überschrieben.
- Cloud-/Scheduler-Jobs dürfen keine permanente automatische Löschung ausführen.
- Quarantäne bleibt der einzige automatische Cleanup-Zwischenschritt nach expliziter Freigabe.

## Freigabestatus

**RELEASE_BLOCKED** – Sichtungs-/Entwicklungsstand, keine Produktivfreigabe.
