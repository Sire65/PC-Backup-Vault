from project_finder.git_inventory import RepoSnapshot, summarize_repositories, update_readiness


def test_chat_claims_are_not_update_readiness():
    row = RepoSnapshot(project="DP2", repository="Sire65/Dienstplan", head_sha="abc", latest_test="NOT_CHECKED", update_mode="AUTO")
    status, _ = update_readiness(row)
    assert status == "YELLOW"


def test_green_requires_tested_update_path():
    row = RepoSnapshot(project="DP2", repository="Sire65/Dienstplan", head_sha="abc", latest_test="PASS", update_mode="CHECK_AND_INSTALL")
    status, _ = update_readiness(row)
    assert status == "GREEN"


def test_local_newer_blocks_automatic_update():
    row = RepoSnapshot(project="Backup", repository="Sire65/PC-Backup-Vault", head_sha="abc", latest_test="PASS", update_mode="AUTO", local_state="LOCAL_NEWER")
    status, _ = update_readiness(row)
    assert status == "YELLOW"


def test_summary_counts_states():
    data = summarize_repositories([
        RepoSnapshot(project="A", repository="a", latest_test="PASS", update_mode="AUTO"),
        RepoSnapshot(project="B", repository="b", latest_test="FAIL", local_state="DIVERGED"),
    ])
    assert data["counts"]["total"] == 2
    assert data["counts"]["tests_pass"] == 1
    assert data["counts"]["diverged"] == 1
