from project_finder.source_baseline import baseline_manifest


def test_verified_git_reference_does_not_claim_local_leadership():
    row = baseline_manifest()
    assert row["version"] == "1.7.3"
    assert row["commit_sha"] == "bb7e6b51e13bb0f60c54508befb53239f221e4c9"
    assert row["source_archive_sha256"] == "7224d7cf3aacc104036d9aec70f236a03cac6d7a56328c3911d186314e4dfc62"
    assert row["expected_file_count"] == 59
    assert "backup_engine.py" in row["required_files"]
    assert row["trust"]["git_reference_verified"] is True
    assert row["trust"]["leading_local_source_known"] is False
    assert row["trust"]["safe_to_merge_without_local_scan"] is False
