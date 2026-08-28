from project_finder.update_distribution import UpdateTarget, build_update_plan, evaluate_target


def test_update_ready_only_with_all_safety_gates():
    row = UpdateTarget(
        project="DP2",
        repository="Sire65/Dienstplan",
        head_sha="abc123",
        test_state="PASS",
        local_state="MATCH",
        update_mode="CHECK_AND_INSTALL",
    )
    assert evaluate_target(row)["distribution_state"] == "READY"


def test_local_newer_blocks_automatic_update():
    row = UpdateTarget(
        project="Backup",
        repository="Sire65/PC-Backup-Vault",
        head_sha="abc123",
        test_state="PASS",
        local_state="LOCAL_NEWER",
        update_mode="AUTO",
    )
    result = evaluate_target(row)
    assert result["distribution_state"] == "BLOCKED"
    assert "lokal" in result["reason"].lower()


def test_failed_or_unchecked_tests_block_update():
    for state in ("FAIL", "NOT_CHECKED"):
        row = UpdateTarget(
            project="Kasse",
            repository="Sire65/Kasse",
            head_sha="abc123",
            test_state=state,
            local_state="MATCH",
            update_mode="AUTO",
        )
        assert evaluate_target(row)["distribution_state"] == "BLOCKED"


def test_plan_separates_ready_and_blocked():
    plan = build_update_plan([
        UpdateTarget("A", "repo/a", head_sha="1", test_state="PASS", local_state="MATCH", update_mode="AUTO"),
        UpdateTarget("B", "repo/b", head_sha="2", test_state="FAIL", local_state="MATCH", update_mode="AUTO"),
    ])
    assert len(plan["ready"]) == 1
    assert len(plan["blocked"]) == 1
