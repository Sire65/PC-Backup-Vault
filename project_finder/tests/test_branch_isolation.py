from pathlib import Path


def test_project_finder_module_does_not_import_backup_core_modules():
    root = Path(__file__).resolve().parents[1]
    forbidden = ("b2", "backup_engine", "backup_core", "start_backup", "pause_backup")
    violations = []
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            if token in text and path.name not in {"integration_gate.py"}:
                violations.append((path.name, token))
    assert not violations, f"Project-Finder muss bis zur Integrationsabnahme vom Backupkern isoliert bleiben: {violations}"
