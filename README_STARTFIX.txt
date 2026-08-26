PC Backup Vault 1.6.2 – Startfix 2
==================================

Behoben:
- Hauptfenster konnte auf bestimmten Tk/Windows-Konfigurationen beim Zeichnen
  des Live-Fortschrittskreises sofort mit TclError beendet werden.
- Ursache: nicht überall verfügbare Tk-Systemfarbe "SystemButtonShadow".
- Lösung: plattformfeste Farbauflösung mit sicheren Fallback-Farben.
- STARTEN.bat bleibt bei Python-/GUI-Startfehlern offen und schreibt STARTFEHLER.log.
- requirements.txt enthält qrcode für den Notfall-/Backup-Pass.

Regression:
- Python-Kompilierung: PASS
- ui import: PASS
- App-Initialisierung: PASS
- Tk-Mainloop-Kurztest: PASS
