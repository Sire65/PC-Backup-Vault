from pathlib import Path


def test_all_windows_build_paths_package_core_jobs_schema():
    bat = Path("BUILD_EXE.bat").read_text(encoding="utf-8")
    build = Path(".github/workflows/build-windows.yml").read_text(encoding="utf-8")
    release = Path(".github/workflows/release-windows.yml").read_text(encoding="utf-8")
    marker = '--add-data "schema_core_jobs.sql;."'
    assert marker in bat
    assert marker in build
    assert marker in release
