from project_finder.core_job_bridge import _as_core_job


def test_inventory_mapping_is_metadata_only_and_counts_warnings():
    row = {
        "id": "local-1",
        "job_type": "INVENTORY",
        "status": "SUCCESS",
        "started_at": "2026-08-29T12:00:00+0200",
        "finished_at": "2026-08-29T12:01:00+0200",
        "duration_seconds": 60,
        "files": 100,
        "bytes": 2048,
        "to_git": 20,
        "git_review": 3,
        "review": 2,
        "duplicates": 4,
        "roots": ["C:/KC"],
    }
    out = _as_core_job(row)
    assert out["job_type"] == "INVENTORY"
    assert out["source_job_id"] == "local-1"
    assert out["item_count"] == 100
    assert out["byte_count"] == 2048
    assert out["warning_count"] == 5
    assert out["error_count"] == 0
    assert "20 zu Git" in out["summary"]
    assert "roots" in out["metrics"]


def test_github_mapping_marks_problem_findings_as_warnings():
    out = _as_core_job({
        "id": "gh-1", "job_type": "GITHUB_COMPARE", "status": "SUCCESS", "files": 50,
        "identical": 40, "local_only": 5, "divergent": 3, "unavailable": 2,
    })
    assert out["warning_count"] == 10
    assert out["item_count"] == 50
    assert "40 identisch" in out["summary"]


def test_failed_job_has_error_count():
    out = _as_core_job({"id": "x", "job_type": "INVENTORY", "status": "FAILED"})
    assert out["error_count"] == 1
