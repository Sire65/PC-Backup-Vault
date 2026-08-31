# PC Backup Vault 1.8.0 – Release Candidate Status

Stand: 2026-08-31

## Ergebnis

Der Entwicklungsbranch `feature/modular-control-center` hat die technische Abschlusskonsolidierung bestanden und ist als Release Candidate vorbereitet.

- Release-Candidate-Commit: `9870f89275b271b3d9fb30aaaaa500f55d5e8aaa`
- `main` bleibt unverändert auf `9657a5e8100760e8bcabae2d58dbeb46ad716998`.
- Kein Merge und keine Release-Veröffentlichung wurden automatisch ausgeführt.

## Erfolgreiche Abschlussprüfungen

### Modular Control Center Regression
Run #94 / ID `33428546401`: SUCCESS.

Geprüft wurden u. a. Architektur, Leitstand-UX, Release-Gate, NAS-/RAID-Sicherheit, Missing-Disk-Erkennung, SSH-read-only, Inventar, Recovery-Workflow, Image-Verifikation, Recovery-Härtung, physische Device-Guards, Cloud-Kostenschutz und Sicherheitsmarker.

### Final Consolidation Gate
Run #9 / ID `33428859377`: SUCCESS.

Geprüft wurden:
- Abschlussvertrag / fail-closed Release-Gate
- Usability-Regression
- Recovery-Hardening
- Unified Core Job Schema und Packaging
- Project Finder Core Job Regression
- Framework-Studio- und Sicherheitsregeln

### Windows Build
Run #58 / ID `33428859492`: SUCCESS.

Erzeugt wurden:
- `PC_Backup_Vault_1.8.0_Setup`
- `PC_Backup_Vault_1.8.0_Windows_Portable`

Der Build umfasst den konsolidierten Quellstand, Project Finder, NAS/Recovery, Control Center, Framework-Adapter, Release-/Consolidation-Gates sowie `schema.sql` und `schema_core_jobs.sql`.

## Framework Studio

Die Baseline ist eindeutig als Framework Studio V1.38.39 / `BASELINE_V1_38_39` dokumentiert. PC Backup Vault verwendet Adapter für bestehende Framework-Studio-Verträge und erzeugt keine Ersatz-Cores.

Der Framework-Studio-Kandidat bleibt formal **YELLOW**, da Browser- und Geräteevidenz für die Studio-Freigabe noch extern zu erbringen ist. Diese offene Evidenz wird nicht als GREEN umdeklariert.

## Noch extern abzunehmen

Die verbleibenden Punkte sind keine weitere Feature-Entwicklung:

1. Installation/Start auf einem realen Windows-PC.
2. Kurzer visueller Smoke-Test der wichtigsten Fenster und Assistenten auf echter Hardware.
3. Bei Bedarf Framework-Studio-Browser-/Geräteevidenz.
4. Erst danach ausdrückliche Freigabe für Merge/Release.

## Release-Regel

`main` darf erst nach ausdrücklicher Freigabe verändert werden. Der Release-Gate erzeugt nur einen Kandidatenstatus und führt niemals selbst einen Merge aus.
