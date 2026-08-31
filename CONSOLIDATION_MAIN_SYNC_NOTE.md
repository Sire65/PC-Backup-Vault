# Abschlusskonsolidierung gegen main

Stand: 2026-08-31

Vor dem finalen Release-Candidate-Gate wurde festgestellt, dass `feature/modular-control-center` historisch von `main` abgezweigt war, während auf `main` danach 22 Commits zur vereinheitlichten Core-Job-/Project-Finder-Infrastruktur und Windows-Paketierung hinzugekommen waren.

Diese Abschlussstufe übernimmt deshalb die **aktuellen Inhalte** der ausschließlich auf `main` weiterentwickelten Dateien in den Entwicklungsbranch, ohne `main` zu verändern. Danach werden Regression, TÜV, Studio-/Core-Regeln und Release-Gates erneut ausgeführt.

Verbindlich:
- `main` bleibt unverändert.
- Keine automatische Freigabe und kein automatischer Merge.
- Bei Konflikten gilt fail-closed; keine Datei wird stillschweigend verworfen.
- Framework Studio bleibt Quelle der Core-Semantik; diese Konsolidierung erzeugt keinen neuen Core.
