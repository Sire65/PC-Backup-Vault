from pathlib import Path

from vault_db import unified_job_kpis


def test_core_jobs_schema_contains_safe_unified_control_plane():
    sql = Path("schema_core_jobs.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS backup_vault.core_jobs" in sql
    assert "CREATE OR REPLACE VIEW backup_vault.unified_jobs" in sql
    assert "FROM backup_vault.backup_jobs b" in sql
    assert "UNION ALL" in sql
    assert "FROM backup_vault.core_jobs c" in sql
    assert "UPDATE backup_vault.core" in sql
    assert "schema_version='1.8.0'" in sql


def test_unified_job_kpis_aggregate_types_and_statuses():
    rows = [
        {"job_type": "BACKUP", "status": "SUCCESS", "item_count": 10, "byte_count": 100, "warning_count": 0, "error_count": 0},
        {"job_type": "INVENTORY", "status": "SUCCESS", "item_count": 20, "byte_count": 200, "warning_count": 2, "error_count": 0},
        {"job_type": "GITHUB_COMPARE", "status": "FAILED", "item_count": 5, "byte_count": 0, "warning_count": 1, "error_count": 1},
    ]
    k = unified_job_kpis(rows)
    assert k["runs"] == 3
    assert k["success"] == 2
    assert k["failed"] == 1
    assert k["success_percent"] == 66.7
    assert k["warnings"] == 3
    assert k["errors"] == 1
    assert k["items"] == 35
    assert k["bytes"] == 300
    assert k["by_type"] == {"BACKUP": 1, "INVENTORY": 1, "GITHUB_COMPARE": 1}
