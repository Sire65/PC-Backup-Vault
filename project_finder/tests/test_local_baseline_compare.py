from pathlib import Path

from project_finder.local_baseline_compare import compare_local_root, summarize_candidates
from project_finder.source_baseline import PC_BACKUP_VAULT_173


def make_required(root: Path):
    for name in PC_BACKUP_VAULT_173.required_files:
        p = root / name
        p.write_text("x", encoding="utf-8")


def test_missing_required_files_is_incomplete(tmp_path):
    (tmp_path / "app.py").write_text("x", encoding="utf-8")
    row = compare_local_root(tmp_path)
    assert row.state == "INCOMPLETE"
    assert row.evidence_strength == "STRONG"


def test_complete_structure_without_hashes_does_not_claim_match(tmp_path):
    make_required(tmp_path)
    row = compare_local_root(tmp_path)
    assert row.state == "COMPARE_REQUIRED"
    assert row.required_found == len(PC_BACKUP_VAULT_173.required_files)


def test_hash_mismatch_marks_diverged(tmp_path):
    make_required(tmp_path)
    hashes = {name: "0" * 64 for name in PC_BACKUP_VAULT_173.required_files}
    row = compare_local_root(tmp_path, baseline_hashes=hashes)
    assert row.state == "DIVERGED"
    assert row.required_changed


def test_summary_never_declares_safe_merge(tmp_path):
    make_required(tmp_path)
    row = compare_local_root(tmp_path)
    summary = summarize_candidates([row])
    assert summary["safe_to_merge"] is False
    assert len(summary["possible_leaders"]) == 1
