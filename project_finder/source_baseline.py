from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SourceBaseline:
    repository: str
    ref: str
    commit_sha: str
    version: str
    source_archive_sha256: str
    expected_file_count: int
    required_files: tuple[str, ...]
    state: str = "VERIFIED_GIT_REFERENCE"


PC_BACKUP_VAULT_173 = SourceBaseline(
    repository="Sire65/PC-Backup-Vault",
    ref="import-1.7.3-clean",
    commit_sha="bb7e6b51e13bb0f60c54508befb53239f221e4c9",
    version="1.7.3",
    source_archive_sha256="7224d7cf3aacc104036d9aec70f236a03cac6d7a56328c3911d186314e4dfc62",
    expected_file_count=59,
    required_files=(
        "app.py",
        "ui.py",
        "backup_engine.py",
        "config_store.py",
        "kc_communication.py",
        "requirements.txt",
        "schema.sql",
        "NEU_IN_VERSION_1.7.3.txt",
    ),
)


def baseline_manifest() -> dict:
    data = asdict(PC_BACKUP_VAULT_173)
    data["required_files"] = list(PC_BACKUP_VAULT_173.required_files)
    data["trust"] = {
        "git_reference_verified": True,
        "leading_local_source_known": False,
        "safe_to_merge_without_local_scan": False,
    }
    return data
