from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .source_baseline import PC_BACKUP_VAULT_173, SourceBaseline


@dataclass
class LocalBaselineResult:
    root: str
    state: str
    version_hint: str
    required_found: int
    required_missing: list[str]
    required_changed: list[str]
    required_same: list[str]
    extra_files: int
    evidence_strength: str
    reason: str


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _version_hint(root: Path) -> str:
    candidates = (root / "config_store.py", root / "NEU_IN_VERSION_1.7.3.txt", root / "STARTEN.bat")
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for token in ("1.7.3", "1.7.2", "1.7.1", "1.7.0", "1.6.2"):
            if token in text:
                return token
    return ""


def compare_local_root(
    root: str | Path,
    *,
    baseline: SourceBaseline = PC_BACKUP_VAULT_173,
    baseline_hashes: dict[str, str] | None = None,
) -> LocalBaselineResult:
    """Compare one local candidate against a verified Git source baseline.

    Without per-file baseline hashes this function intentionally cannot call a
    candidate IDENTICAL. It can still detect missing/extra structure and produce
    a conservative classification for recovery triage.
    """
    p = Path(root)
    required_missing: list[str] = []
    required_changed: list[str] = []
    required_same: list[str] = []
    required_found = 0

    for name in baseline.required_files:
        local = p / name
        if not local.is_file():
            required_missing.append(name)
            continue
        required_found += 1
        if baseline_hashes and name in baseline_hashes:
            try:
                actual = sha256_file(local)
            except OSError:
                required_changed.append(name)
                continue
            if actual == baseline_hashes[name]:
                required_same.append(name)
            else:
                required_changed.append(name)

    file_count = 0
    try:
        file_count = sum(1 for x in p.rglob("*") if x.is_file())
    except OSError:
        pass
    extra_files = max(0, file_count - baseline.expected_file_count)
    version = _version_hint(p)

    if required_missing:
        state = "INCOMPLETE"
        strength = "STRONG"
        reason = f"Pflichtdateien fehlen: {len(required_missing)}. Kein führender Quellstand."
    elif baseline_hashes and required_changed:
        state = "DIVERGED"
        strength = "STRONG"
        reason = f"Pflichtdateien weichen von der verifizierten {baseline.version}-Referenz ab."
    elif baseline_hashes and len(required_same) == len(baseline.required_files) and file_count == baseline.expected_file_count:
        state = "MATCH_REFERENCE"
        strength = "STRONG"
        reason = f"Pflichtdateien und Dateizahl stimmen mit der verifizierten {baseline.version}-Referenz überein."
    elif version and version != baseline.version:
        state = "VERSION_DIFFERS"
        strength = "MEDIUM"
        reason = f"Lokaler Versionshinweis {version} unterscheidet sich von Referenz {baseline.version}; Inhaltsvergleich erforderlich."
    else:
        state = "COMPARE_REQUIRED"
        strength = "MEDIUM" if required_found == len(baseline.required_files) else "LOW"
        reason = "Struktur ist plausibel, aber ohne vollständige Baseline-Hashes kein Identitätsnachweis."

    return LocalBaselineResult(
        root=str(p),
        state=state,
        version_hint=version,
        required_found=required_found,
        required_missing=required_missing,
        required_changed=required_changed,
        required_same=required_same,
        extra_files=extra_files,
        evidence_strength=strength,
        reason=reason,
    )


def summarize_candidates(candidates: Iterable[LocalBaselineResult]) -> dict:
    rows = list(candidates)
    priority = {
        "DIVERGED": 5,
        "VERSION_DIFFERS": 4,
        "COMPARE_REQUIRED": 3,
        "MATCH_REFERENCE": 2,
        "INCOMPLETE": 1,
    }
    rows.sort(key=lambda x: (priority.get(x.state, 0), x.required_found, x.extra_files), reverse=True)
    possible_leaders = [x for x in rows if x.state in {"DIVERGED", "VERSION_DIFFERS", "COMPARE_REQUIRED", "MATCH_REFERENCE"}]
    return {
        "schema": "pc-backup-vault.local-baseline-compare.v1",
        "reference_version": PC_BACKUP_VAULT_173.version,
        "reference_commit": PC_BACKUP_VAULT_173.commit_sha,
        "candidate_count": len(rows),
        "possible_leaders": [asdict(x) for x in possible_leaders],
        "all": [asdict(x) for x in rows],
        "safe_to_merge": False,
        "rule": "Lokale Kandidaten dürfen erst nach vollständigem Inhaltsvergleich als führend gelten; ein Versionsname oder vollständige Pflichtdateiliste allein reicht nicht.",
    }
