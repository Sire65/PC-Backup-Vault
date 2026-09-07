from telemetry_snapshot_v193 import build_snapshot, system_check_view


def test_snapshot_redacts_sensitive_keys_recursively():
    snapshot = build_snapshot(
        app_version="1.9.3",
        vault_status="ok",
        last_job={
            "status": "SUCCESS",
            "password": "must-not-leak",
            "nested": {"recovery_key": "must-not-leak", "files": 3},
        },
        targets=[
            {
                "id": "hidrive_1",
                "status": "healthy",
                "token": "must-not-leak",
                "endpoint": "sftp.hidrive.strato.com:22",
            }
        ],
    )

    text = repr(snapshot)
    assert "must-not-leak" not in text
    assert snapshot["lastJob"]["nested"]["files"] == 3
    assert snapshot["targets"][0]["endpoint"] == "sftp.hidrive.strato.com:22"


def test_snapshot_normalises_statuses():
    assert build_snapshot(app_version="x", vault_status="ok")["status"] == "healthy"
    assert build_snapshot(app_version="x", vault_status="error")["status"] == "critical"
    assert build_snapshot(app_version="x", vault_status="unexpected")["status"] == "unknown"


def test_system_check_view_uses_common_shape_and_escalates_target_failure():
    snapshot = build_snapshot(
        app_version="1.9.3",
        vault_status="healthy",
        targets=[
            {"id": "nas_backup", "status": "healthy"},
            {"id": "hidrive_1", "status": "critical"},
        ],
        last_verify={"status": "healthy"},
        last_restore_test={"status": "healthy"},
        capacity={"usage": 42, "label": "42 %"},
        generated_at="2026-09-07T20:00:00Z",
    )

    result = system_check_view(snapshot)
    assert result["id"] == "backup_vault"
    assert result["status"] == "critical"
    assert result["health"] == "critical"
    assert result["usage"] == 42
    assert result["capacityLabel"] == "42 %"
    assert result["metrics"]["generatedAt"] == "2026-09-07T20:00:00Z"
