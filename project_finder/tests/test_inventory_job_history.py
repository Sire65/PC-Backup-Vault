import json
from pathlib import Path

from project_finder.inventory_job_history import append_job, history_kpis, read_jobs


def test_append_and_read_jobs(tmp_path):
    path = tmp_path / "jobs.jsonl"
    append_job({"job_type": "INVENTORY", "status": "SUCCESS", "files": 10, "bytes": 1000, "to_git": 3, "duplicates": 2}, path)
    append_job({"job_type": "GITHUB_COMPARE", "status": "SUCCESS", "files": 3, "identical": 2, "local_only": 1, "divergent": 0, "unavailable": 0}, path)
    rows = read_jobs(path)
    assert len(rows) == 2
    assert all(row["schema"] == "pc-backup-vault.project-finder-job.v1" for row in rows)


def test_history_kpis_aggregate_status_and_metrics():
    rows = [
        {"job_type": "INVENTORY", "status": "SUCCESS", "files": 10, "bytes": 1000, "to_git": 3, "duplicates": 2},
        {"job_type": "INVENTORY", "status": "CANCELLED", "files": 5, "bytes": 500, "to_git": 1, "duplicates": 1},
        {"job_type": "GITHUB_COMPARE", "status": "SUCCESS", "identical": 4, "local_only": 2, "divergent": 1, "unavailable": 1},
        {"job_type": "GITHUB_COMPARE", "status": "FAILED"},
    ]
    k = history_kpis(rows)
    assert k["runs"] == 4
    assert k["inventory_runs"] == 2
    assert k["github_runs"] == 2
    assert k["success"] == 2
    assert k["failed"] == 1
    assert k["cancelled"] == 1
    assert k["success_percent"] == 50.0
    assert k["files_scanned"] == 15
    assert k["bytes_scanned"] == 1500
    assert k["to_git"] == 4
    assert k["duplicates"] == 3
    assert k["github_identical"] == 4
    assert k["github_local_only"] == 2
    assert k["github_divergent"] == 1
    assert k["github_unavailable"] == 1


def test_read_jobs_skips_broken_lines(tmp_path):
    path = tmp_path / "jobs.jsonl"
    path.write_text('{"job_type":"INVENTORY","status":"SUCCESS"}\nnot-json\n', encoding="utf-8")
    rows = read_jobs(path)
    assert len(rows) == 1
    assert rows[0]["status"] == "SUCCESS"
