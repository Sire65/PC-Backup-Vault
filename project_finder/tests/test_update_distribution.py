from project_finder.update_distribution import UpdateTarget, build_update_plan, evaluate_target, recovery_decision


def safe_target(**overrides):
    data = dict(project="DP2", repository="Sire65/Dienstplan", head_sha="abc123", test_state="PASS", local_state="MATCH", update_mode="CHECK_AND_INSTALL", download_url="https://example.invalid/releases/v1/app.zip", rollback_available=True)
    data.update(overrides); return UpdateTarget(**data)


def test_update_ready_only_with_all_safety_gates(): assert evaluate_target(safe_target())["distribution_state"] == "READY"

def test_local_newer_blocks_automatic_update_and_protects_local():
    row=safe_target(local_state="LOCAL_NEWER", update_mode="AUTO"); result=evaluate_target(row)
    assert result["distribution_state"] == "BLOCKED"; assert "lokal" in result["reason"].lower(); assert recovery_decision(row)["state"] == "PROTECT_LOCAL"

def test_diverged_blocks_and_requires_compare():
    row=safe_target(local_state="DIVERGED"); assert evaluate_target(row)["distribution_state"] == "BLOCKED"; assert recovery_decision(row)["state"] == "COMPARE_REQUIRED"

def test_failed_or_unchecked_tests_block_update():
    for state in ("FAIL","NOT_CHECKED"): assert evaluate_target(safe_target(test_state=state))["distribution_state"] == "BLOCKED"

def test_unchecked_local_state_blocks_update(): assert evaluate_target(safe_target(local_state="NOT_CHECKED"))["distribution_state"] == "BLOCKED"

def test_missing_release_source_blocks_update(): assert evaluate_target(safe_target(download_url=""))["distribution_state"] == "BLOCKED"

def test_same_commit_is_current_not_ready(): assert evaluate_target(safe_target(current_sha="abc123"))["distribution_state"] == "CURRENT"

def test_git_newer_can_be_candidate_after_all_gates():
    row=safe_target(local_state="GIT_NEWER",current_sha="old123"); assert evaluate_target(row)["distribution_state"] == "READY"; assert recovery_decision(row)["state"] == "UPDATE_CANDIDATE"

def test_plan_separates_ready_current_blocked_and_recovery():
    plan=build_update_plan([safe_target(project="A",repository="repo/a",current_sha="old"),safe_target(project="B",repository="repo/b",current_sha="abc123"),safe_target(project="C",repository="repo/c",test_state="FAIL")])
    assert plan["schema"] == "pc-backup-vault.update-plan.v2"; assert len(plan["ready"]) == 1; assert len(plan["current"]) == 1; assert len(plan["blocked"]) == 1; assert len(plan["recovery"]) == 3
    assert plan["safety"]["automatic_install"] is False; assert plan["safety"]["overwrite_local_newer"] is False; assert plan["safety"]["overwrite_diverged"] is False

def test_one_shot_generator_keeps_recovery_rows():
    rows=(safe_target(project=f"P{i}",repository=f"repo/{i}") for i in range(3))
    plan=build_update_plan(rows)
    assert len(plan["ready"]) == 3
    assert len(plan["recovery"]) == 3
    assert {x["project"] for x in plan["recovery"]} == {"P0","P1","P2"}
