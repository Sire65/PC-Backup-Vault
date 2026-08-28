from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from typing import Iterable


@dataclass
class ExportCheckpoint:
    export_id: str
    conversation_id: str
    last_timestamp: float = 0.0
    last_message_fingerprint: str = ""


def message_fingerprint(conversation_id: str, timestamp: object, text: str) -> str:
    raw = f"{conversation_id}|{timestamp}|{text.strip()}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def build_checkpoints(export_id: str, conversations: Iterable[dict]) -> list[dict]:
    rows: list[dict] = []
    for conv in conversations:
        cid = str(conv.get("id") or conv.get("conversation_id") or "")
        findings = list(conv.get("findings") or [])
        last = findings[-1] if findings else {}
        ts = float(last.get("timestamp") or conv.get("timestamp") or 0.0)
        text = str(last.get("text") or "")
        rows.append(asdict(ExportCheckpoint(
            export_id=export_id,
            conversation_id=cid,
            last_timestamp=ts,
            last_message_fingerprint=message_fingerprint(cid, ts, text) if cid else "",
        )))
    return rows


def merge_findings(previous: Iterable[dict], current: Iterable[dict]) -> dict:
    """Merge repeated ChatGPT exports without double counting old findings.

    A later export may contain all earlier conversations plus new messages.  We keep
    a stable fingerprint per finding and return only genuinely new evidence as
    delta, while retaining a complete merged inventory locally.
    """
    merged: dict[str, dict] = {}
    old_keys: set[str] = set()

    def key(row: dict) -> str:
        cid = str(row.get("conversation_id") or "")
        ts = row.get("timestamp") or ""
        text = str(row.get("text") or "")
        return message_fingerprint(cid, ts, text)

    for row in previous:
        k = key(row)
        old_keys.add(k)
        merged[k] = dict(row)
    for row in current:
        merged[key(row)] = dict(row)

    delta = [row for k, row in merged.items() if k not in old_keys]
    return {
        "schema": "pc-backup-vault.chat-merge.v1",
        "merged_findings": list(merged.values()),
        "new_findings": delta,
        "counts": {
            "previous": len(old_keys),
            "current": len(list(current)) if isinstance(current, list) else None,
            "merged": len(merged),
            "new": len(delta),
        },
        "rule": "Wiederholte Exporte werden lokal zusammengeführt; alte Chat-Funde werden nicht doppelt gezählt.",
    }
