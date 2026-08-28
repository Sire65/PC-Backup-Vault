from project_finder.integration_gate import BLOCKED, PASS, default_checks, evaluate_integration, merge_gate_from_evidence


def test_default_gate_blocks_merge():
    result = evaluate_integration(default_checks())
    assert result["state"] == "MERGE_BLOCKED"
    assert result["safety"]["main_may_change"] is False


def test_green_project_finder_alone_does_not_open_main():
    result = merge_gate_from_evidence({"PROJECT_FINDER": (PASS, "Actions run #52 success")})
    assert result["state"] == "MERGE_BLOCKED"
    assert "SOURCE" in result["unchecked"]
    assert "B2" in result["unchecked"]


def test_pass_without_evidence_is_not_accepted():
    evidence = {cid: (PASS, "proof") for cid, _ in [(x.check_id, x.title) for x in default_checks()]}
    evidence["B2"] = (PASS, "")
    result = merge_gate_from_evidence(evidence)
    assert result["state"] == "MERGE_BLOCKED"
    assert result["pass_without_evidence"] == ["B2"]


def test_explicit_failure_blocks_merge():
    evidence = {x.check_id: (PASS, "proof") for x in default_checks()}
    evidence["BACKUP_PAUSE"] = (BLOCKED, "Pause regression failed")
    result = merge_gate_from_evidence(evidence)
    assert result["state"] == "MERGE_BLOCKED"
    assert result["failed"] == ["BACKUP_PAUSE"]


def test_all_required_evidence_opens_only_merge_review():
    evidence = {x.check_id: (PASS, "verified proof") for x in default_checks()}
    result = merge_gate_from_evidence(evidence)
    assert result["state"] == "READY_FOR_MERGE_REVIEW"
    assert result["safety"]["main_may_change"] is True
    assert result["safety"]["merge_automatic"] is False
    assert result["safety"]["release_automatic"] is False
    assert result["safety"]["backup_core_may_change"] is False
