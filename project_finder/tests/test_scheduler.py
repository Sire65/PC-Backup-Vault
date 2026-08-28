from pathlib import Path
from unittest.mock import patch

import pytest

from project_finder.scheduler import resolve_runner_command


def test_source_mode_uses_python_module_runner():
    cmd = resolve_runner_command(r"C:\Jobs\nacht.json", frozen=False)
    assert "-m project_finder.job_runner" in cmd
    assert "nacht.json" in cmd


def test_explicit_runner_is_used_in_packaged_mode():
    cmd = resolve_runner_command(
        r"C:\Jobs\nacht.json",
        r"C:\Program Files\PC Backup Vault\ProjectFinderRunner.exe",
        frozen=True,
    )
    assert "ProjectFinderRunner.exe" in cmd
    assert "--profile" in cmd


def test_packaged_mode_never_falls_back_to_backup_gui():
    with patch.object(Path, "exists", return_value=False):
        with pytest.raises(RuntimeError):
            resolve_runner_command(r"C:\Jobs\nacht.json", frozen=True)
