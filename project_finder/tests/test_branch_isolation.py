import ast
from pathlib import Path

FORBIDDEN_MODULES = {"b2", "backup_engine", "backup_core"}
FORBIDDEN_CALLS = {"start_backup", "pause_backup"}


def _root_name(name: str) -> str:
    return name.split(".", 1)[0].lower()


def test_project_finder_module_does_not_import_or_call_backup_core():
    """Metadata may name backup files; executable coupling to backup core is forbidden."""
    root = Path(__file__).resolve().parents[1]
    violations = []
    for path in root.glob("*.py"):
        if path.name == "integration_gate.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _root_name(alias.name) in FORBIDDEN_MODULES:
                        violations.append((path.name, "import", alias.name))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _root_name(module) in FORBIDDEN_MODULES:
                    violations.append((path.name, "from-import", module))
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id.lower() in FORBIDDEN_CALLS:
                    violations.append((path.name, "call", fn.id))
                elif isinstance(fn, ast.Attribute) and fn.attr.lower() in FORBIDDEN_CALLS:
                    violations.append((path.name, "call", fn.attr))
    assert not violations, f"Project-Finder muss bis zur Integrationsabnahme vom Backupkern isoliert bleiben: {violations}"


def test_source_reference_metadata_may_name_required_backup_files_without_importing_them():
    source = (Path(__file__).resolve().parents[1] / "source_baseline.py").read_text(encoding="utf-8")
    assert "backup_engine.py" in source
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module: imported.append(node.module)
    assert not any(_root_name(x) in FORBIDDEN_MODULES for x in imported)
