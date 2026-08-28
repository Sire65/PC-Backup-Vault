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


def message_fingerprint(conversation_id: str, timestamp: object, text: str, message_id: str = "") -> str:
    """Stable local evidence key.

    Newer inventories expose the ChatGPT message id. Prefer it when available so
    text formatting/redaction changes do not create false deltas. Older v1
    inventories remain compatible through the timestamp/text fallback.
    """
    cid = str(conversation_id or "")
    mid = str(message_id or "")
    if cid and mid:
        raw = f"{cid}|message:{mid}".encode("utf-8", errors="replace")
    else:
        raw = f"{cid}|{timestamp}|{str(text or '').strip()}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def build_checkpoints(export_id: str, conversations: Iterable[dict]) -> list[dict]:
    rows: list[dict] = []
    for conv in conversations:
        cid = str(conv.get("id") or conv.get("conversation_id") or "")
        findings = list(conv.get("findings") or [])
        last = findings[-1] if findings else {}
        raw_ts = last.get("timestamp") or conv.get("timestamp") or 0.0
        try:
            ts = float(raw_ts)
        except (TypeError, ValueError):
            ts = 0.0
        text = str(last.get("text") or "")
        mid = str(last.get("message_id") or "")
        rows.append(asdict(ExportCheckpoint(
            export_id=export_id,
            conversation_id=cid,
            last_timestamp=ts,
            last_message_fingerprint=message_fingerprint(cid, ts, text, mid) if cid else "",
        )))
    return rows


def merge_findings(previous: Iterable[dict], current: Iterable[dict]) -> dict:
    """Merge repeated ChatGPT exports without double counting old findings."""
    previous_rows = [dict(x) for x in previous]
    current_rows = [dict(x) for x in current]
    merged: dict[str, dict] = {}
    old_keys: set[str] = set()

    def key(row: dict) -> str:
        cid = str(row.get("conversation_id") or "")
        ts = row.get("timestamp") or ""
        text = str(row.get("text") or "")
        mid = str(row.get("message_id") or "")
        kind = str(row.get("kind") or "")
        base = message_fingerprint(cid, ts, text, mid)
        # One source message may intentionally produce more than one evidence kind.
        return hashlib.sha256(f"{base}|{kind}".encode("utf-8")).hexdigest()

    for row in previous_rows:
        k = key(row)
        old_keys.add(k)
        merged[k] = row
    for row in current_rows:
        merged[key(row)] = row

    delta = [row for k, row in merged.items() if k not in old_keys]
    return {
        "schema": "pc-backup-vault.chat-merge.v2",
        "merged_findings": list(merged.values()),
        "new_findings": delta,
        "counts": {
            "previous": len(previous_rows),
            "current": len(current_rows),
            "merged": len(merged),
            "new": len(delta),
        },
        "rule": "Wiederholte Exporte werden lokal zusammengeführt; Message-ID + Fundart verhindern Doppelzählungen und erhalten Mehrfachbefunde.",
    }
