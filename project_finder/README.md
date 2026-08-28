# PC Backup Vault – Projekt-Finder / Festplatten-Analyse

Status: isoliertes Erweiterungsmodul auf Feature-Branch. Die bestehende Backup-Logik und bestehende GUI wurden nicht verändert.

## Ziel

Große Datenträger/USB-Sticks mit vielen Entwicklungsständen inventarisieren, relevante KC-Projekte hervorheben, Dubletten erkennen, Versionen/Archive markieren und eine kompakte Übergabe als JSON/CSV oder Zwischenablage ermöglichen.

## Sicherheitsregeln

1. Der Scan ist read-only: keine Datei wird beim Scannen verändert, gelöscht, verschoben oder umbenannt.
2. Automatische Bereinigung bedeutet zunächst nur: sichere, markierte Kandidaten in eine Quarantäne verschieben.
3. Keine endgültige Löschung ohne separaten, späteren Freigabeschritt.
4. Quarantäne erhält pro Lauf ein `manifest.json`, sodass Dateien an den Ursprungsort zurückverschoben werden können.
5. Bit-identische Dubletten (SHA-256) sind der einzige Kandidatentyp mit hoher automatischer Sicherheit. Namen wie `alt`, `neu`, `final`, `test`, `backup` führen nur zu `REVIEW`, niemals zu automatischer Entfernung.
6. Verzeichnisse werden nicht automatisch gelöscht.
7. Systemverzeichnisse und versteckte Bereiche werden standardmäßig ausgelassen.

## Ampeln

- 🟢 hoher Projekt-/Versionsbezug
- 🟡 interessanter Fund, Vergleich erforderlich
- 🔵 bit-identische Dublette
- ⚪ normaler Inventarfund
- 🔴 für spätere Fehler-/Unlesbar-Anzeige reserviert

## Geplante Einbindung

`ProjectFinderTab` ist ein eigenständiger `ttk.Frame` für eine vorhandene `ttk.Notebook`-Oberfläche. Erst wenn der tatsächlich führende PC-Backup-Vault-GUI-Quellstand eindeutig verfügbar ist, wird der Frame als neue Registerkarte eingebunden. Damit wird kein bestehender Backup-Code blind verändert.

Beispiel der späteren Host-Einbindung:

```python
from project_finder.ui_tab import ProjectFinderTab
finder = ProjectFinderTab(notebook)
notebook.add(finder, text='Festplatten-Analyse')
```

Vor der Integration sind Regression, Starttest, Backup-Start/Pause/Fortsetzen, Dashboard und vorhandene Kommunikations-/TÜV-Funktionen gegen den unveränderten Referenzstand zu prüfen.
