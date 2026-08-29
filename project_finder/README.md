# PC Backup Vault – Produktive Inventur / Projekt-Finder

Status: produktiv nutzbarer, isolierter Inventur-Runner auf Feature-Branch. Die bestehende Backup-Logik und bestehende Haupt-GUI werden nicht verändert.

## Zweck

Große Datenträger, Projektordner und USB-Sticks read-only inventarisieren, relevante KC-/Entwicklungsdateien erkennen, Bild-/Asset-Bestände einbeziehen, SHA-256-Dubletten finden und pro Datei eine konservative Empfehlung erzeugen:

- **Zu Git** – Projektquelltext oder produktiv wirkendes Asset; vor Übernahme gegen den führenden Repository-Stand vergleichen.
- **Git prüfen** – Archive/Dokumentation, die nur bewusst versioniert werden sollen.
- **Lokal behalten** – kein belastbarer Grund für Git oder Entfernung.
- **Prüfen** – Build-/Cache-/Temp- oder anderweitig unklare Datei.
- **Quarantäne-Kandidat** – ausschließlich bit-identische SHA-256-Dublette.
- **NIE Git** – Secret-/Zugangsdatenverdacht.

JSON- und CSV-Exporte enthalten die komplette Inventur plus Git-/Inventurentscheidung, Sicherheit und Begründung.

## Sicherheitsregeln

1. Der Scan ist read-only: keine Quelldatei wird beim Scannen verändert, gelöscht, verschoben oder umbenannt.
2. Im produktiven Inventurmodus werden Dateien bis 64 MB für die Dublettenerkennung per SHA-256 gehasht.
3. Der kanonische Vertreter einer Dublettengruppe wird konservativ gewählt: normale Projektpfade werden gegenüber Temp-/Build-/Cachepfaden bevorzugt.
4. Nur bit-identische SHA-256-Dubletten dürfen als sichere Quarantäne-Kandidaten vorgeschlagen werden.
5. Quarantäne ist reversibel und schreibt pro Lauf ein `manifest.json` mit Originalpfad und Hash.
6. Keine endgültige Löschung ohne separaten Alters-Gate und ausdrückliche Bestätigung.
7. Dateinamen wie `alt`, `neu`, `final`, `test` oder `backup` sind niemals allein ein Löschgrund.
8. Verzeichnisse werden nicht automatisch gelöscht.
9. Systemverzeichnisse und versteckte Bereiche werden standardmäßig ausgelassen.
10. Git-Veröffentlichung erfolgt nicht automatisch. `Zu Git` bedeutet Kandidat zum Abgleich, nicht automatisches Pushen.

## Ampeln

- 🟢 hoher Projekt-/Versionsbezug
- 🟡 interessanter Fund / Vergleich erforderlich
- 🔵 bit-identische Dublette
- ⚪ normaler Inventurfund
- 🔴 für Fehler-/Unlesbarstatus reserviert

## Windows-Runner

Die CI baut einen isolierten Windows-Runner mit dem Namen `PC-Backup-Vault-Inventur.exe`. Er ist für produktive Inventur/Analyse vorgesehen, ersetzt aber die installierte PC-Backup-Vault-Hauptanwendung noch nicht.

Damit können bereits produktiv Verzeichnisse gescannt und Entscheidungen vorbereitet werden, ohne die bestehende Backup-Engine, B2, Dashboard, Pause/Fortsetzen oder KC-Kommunikation anzufassen.

## Spätere Hauptintegration

`ProjectFinderTab` bleibt ein eigenständiger `ttk.Frame`. Die Einbindung in die Haupt-GUI erfolgt erst, wenn der tatsächlich führende lokale PC-Backup-Vault-Quellstand eindeutig identifiziert und die bestehenden Backup-Funktionen gegen diesen Stand regressionsgeprüft sind. Bis dahin ist der isolierte Inventur-Runner die sichere produktive Einsatzform.
