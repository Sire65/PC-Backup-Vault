from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import json
import time

SCHEMA = 'kc.project-finder.job.v1'
MAX_DETAIL_FINDINGS = 50


@dataclass
class CloudJob:
    job_id: str
    device_id: str
    profile_name: str
    roots: list[str]
    requested_at: str
    requested_start: str | None = None
    status: str = 'QUEUED'
    allow_cleanup: bool = False

    def validate(self) -> None:
        if not self.job_id or len(self.job_id) > 120:
            raise ValueError('Ungültige job_id')
        if not self.device_id or len(self.device_id) > 120:
            raise ValueError('Ungültige device_id')
        if not self.roots:
            raise ValueError('Mindestens ein Suchbereich ist erforderlich')
        # Cloud-Jobs dürfen niemals unbeaufsichtigtes Löschen freischalten.
        if self.allow_cleanup:
            raise ValueError('Cloud-Jobs dürfen keine automatische Bereinigung aktivieren')

    def to_payload(self) -> dict[str, Any]:
        self.validate()
        return {'schema': SCHEMA, **asdict(self)}



def compact_result(summary: dict[str, Any], *, findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return only compact control/status data for Supabase/Neon.

    Full inventories, file lists and hashes remain local. At most a small set of
    explicitly interesting findings is attached.
    """
    allowed = {
        'status', 'profile', 'files', 'bytes', 'duplicates', 'review_candidates',
        'quarantine_candidates', 'duration_seconds', 'automatic_deletion_performed'
    }
    payload = {k: summary.get(k) for k in allowed if k in summary}
    payload['schema'] = SCHEMA
    payload['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    if findings:
        trimmed = []
        for row in findings[:MAX_DETAIL_FINDINGS]:
            trimmed.append({
                'name': str(row.get('name', ''))[:240],
                'version_hint': str(row.get('version_hint', ''))[:80],
                'category': str(row.get('category', ''))[:80],
                'size': int(row.get('size', 0) or 0),
                'status': str(row.get('status', ''))[:20],
                'proposed_action': str(row.get('proposed_action', ''))[:40],
                'confidence': int(row.get('confidence', 0) or 0),
            })
        payload['findings'] = trimmed
    return payload


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
