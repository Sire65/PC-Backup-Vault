from __future__ import annotations

import json
from pathlib import Path


def read_job_history(output_root: str, limit: int = 100) -> list[dict]:
    root = Path(output_root).expanduser()
    if not root.exists():
        return []
    rows: list[dict] = []
    for summary in root.glob("*/summary.json"):
        try:
            payload = json.loads(summary.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload["summary_file"] = str(summary)
        payload["mtime"] = summary.stat().st_mtime
        rows.append(payload)
    rows.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    return rows[: max(1, int(limit))]


def history_kpis(rows: list[dict]) -> dict:
    return {
        "runs": len(rows),
        "success": sum(1 for x in rows if x.get("status") == "SUCCESS"),
        "failed": sum(1 for x in rows if x.get("status") == "FAILED"),
        "files_scanned": sum(int(x.get("files") or 0) for x in rows),
        "duplicates_found": sum(int(x.get("duplicates") or 0) for x in rows),
        "latest_status": rows[0].get("status", "UNKNOWN") if rows else "NO_RUNS",
        "latest_run_dir": rows[0].get("run_dir", "") if rows else "",
    }
