# PC Backup Vault – Produktive Inventur – Konsolidierungsstand 2026-08-29

## Freigegebener Einsatzumfang

Der isolierte Windows-Runner ist für produktive **Inventur und Analyse** freigegeben. Er ersetzt die PC-Backup-Vault-Hauptanwendung noch nicht und verändert deren Backup-/B2-Konfiguration nicht.

Freigegeben sind:

- read-only Scan ausgewählter Laufwerke und Verzeichnisse;
- Erfassung von Pfad, Dateiname, Erweiterung, Größe, Änderungsdatum, Typ, Projekt-/Versionshinweisen;
- SHA-256-Ermittlung für Dateien bis 64 MB im produktiven Inventurmodus;
- Erkennung bit-identischer Dubletten;
- konservative kanonische Auswahl zugunsten normaler Quell-/Assetpfade gegenüber Build-/Cache-/Venv-Pfaden;
- Einbeziehung von PNG/JPG/JPEG/WEBP/GIF/SVG/ICO als Bild-/Assettypen;
- Empfehlungen `Zu Git`, `Git prüfen`, `Lokal behalten`, `Prüfen`, `Quarantäne-Kandidat`, `NIE Git`;
- JSON-/CSV-Export der vollständigen Inventur inklusive Begründung und Sicherheit;
- reversible Quarantäne ausschließlich für explizit ausgewählte, bit-identische SHA-256-Dubletten.

Nicht freigegeben/absichtlich gesperrt:

- kein automatisches Git-Pushen oder Überschreiben eines Repository-Stands;
- keine automatische endgültige Löschung;
- keine automatische Entfernung aufgrund von Namen wie `alt`, `neu`, `final`, `test` oder `backup`;
- keine Integration in den führenden Backup-Core, solange dessen lokaler Führungsstand und die Core-Regressionskette nicht vollständig verifiziert sind.

## Sicherheitsinvarianten

1. Der Scan verändert keine Quelldatei.
2. Quarantäne ist reversibel und schreibt ein Manifest mit Originalpfad und SHA-256.
3. Endgültiges Löschen bleibt hinter separatem Alters-Gate und ausdrücklicher Bestätigung.
4. Secret-/Zugangsdatenverdacht wird als `NIE Git` eingestuft.
5. Ein `Zu Git`-Hinweis ist nur eine Prüfempfehlung; vor Übernahme ist ein Abgleich gegen den führenden Repository-Stand erforderlich.

## Regression / Build

Branch: `feature/project-finder-productive-inventory`

Freigabe-Commit: `7c7d5b7c02efa8f7021be04308fe46e81f912aa4`

- Project Finder Regression, Run **#91**, Run-ID `33252693453`: **SUCCESS**.
- Compile Project Finder: **SUCCESS**.
- Project Finder Unit Tests: **SUCCESS**.
- Cloud Contract Regression: **SUCCESS**.
- Windows Inventory Build, Run **#23**, Run-ID `33252693426`: **SUCCESS**.
- Windows-Unit-Tests im Build: **SUCCESS**.
- PyInstaller-Build: **SUCCESS**.
- Artefakt-Upload: **SUCCESS**.

Windows-Artefakt:

- Name: `PC-Backup-Vault-Inventur-Windows`
- Artefakt-ID: `9714851090`
- ZIP-Größe: `11,741,185` Byte
- ZIP SHA-256: `35843c0bdab241d57e9553bd0f63874522940542fffc537ce14fef988a8a427b`
- Inhalt geprüft: `PC-Backup-Vault-Inventur.exe`, `LESE_MICH.txt` und erforderliche PyInstaller-Runtime vorhanden.

## Branch-Isolation

Vergleich gegen `feature/project-finder-safe-cleanup` vor dieser Konsolidierungsdatei:

- Status: ahead;
- keine Änderungen an `backup_engine.py`, `ui.py`, `config_store.py`, `kc_communication.py` oder sonstigem bestehenden Backup-Core;
- Änderungen beschränken sich auf Project-Finder/Inventur, dessen Tests, den isolierten Runner und seine beiden Workflows;
- zwei obsolete Trigger-/Preview-Marker wurden entfernt, beide hatten ausdrücklich keinen Runtime-Effekt.

## Ergebnis

Die produktive Inventur-Stufe ist als **isolierter Scanner/Entscheidungshelfer** einsatzbereit. Die vollständige Zusammenführung in die PC-Backup-Vault-Hauptanwendung bleibt ein separater späterer Release-Schritt mit Core-Regression und wird durch diese Freigabe nicht vorweggenommen.
