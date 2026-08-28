from project_finder.release_readiness import ReadinessInput, build_release_readiness


def test_preview_only_never_marks_release_ready():
    report = build_release_readiness(ReadinessInput(project_finder_passed=True), {"PROJECT_FINDER": "regression green"})
    assert report["release_state"] == "RELEASE_BLOCKED"
    assert report["release_ready"] is False
    assert "SOURCE" in report["gate"]["unchecked"]
    assert "LOCAL_GIT" in report["gate"]["unchecked"]


def test_all_flags_without_evidence_still_block():
    report = build_release_readiness(ReadinessInput(**{field: True for field in ReadinessInput.__dataclass_fields__}))
    assert report["release_state"] == "RELEASE_BLOCKED"
    assert report["gate"]["pass_without_evidence"]
    assert report["release_review_candidate"] is False


def test_all_measured_checks_only_open_release_review():
    inp = ReadinessInput(**{field: True for field in ReadinessInput.__dataclass_fields__})
    ids = ("SOURCE","LOCAL_GIT","BACKUP_START","BACKUP_PAUSE","B2","DASHBOARD","COMMUNICATION","RUNNER","QUARANTINE","PROJECT_FINDER")
    report = build_release_readiness(inp, {cid: f"proof:{cid}" for cid in ids})
    assert report["gate"]["state"] == "READY_FOR_MERGE_REVIEW"
    assert report["release_state"] == "READY_FOR_RELEASE_REVIEW"
    assert report["release_review_candidate"] is True
    assert report["release_ready"] is False
    assert report["automatic_release"] is False
