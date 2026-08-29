from __future__ import annotations

import time

from .decision_engine import inventory_summary
from .inventory_job_history import append_job
from .ui_tab import ProjectFinderTab


class HistoryProjectFinderTab(ProjectFinderTab):
    """Project Finder with append-only local audit history.

    History writes only metadata/KPIs. Source files and GitHub are never changed by this adapter.
    """

    def __init__(self, master, **kwargs):
        self._inventory_started_wall = 0.0
        self._github_started_wall = 0.0
        self._last_failure_marker = ""
        super().__init__(master, **kwargs)
        self.status_var.trace_add("write", self._status_changed)

    def start_scan(self):
        self._inventory_started_wall = time.time()
        return super().start_scan()

    def _render(self):
        super()._render()
        if not self.items:
            return
        summary = inventory_summary(self.items)["counts"]
        status = "CANCELLED" if self.stop_flag and self.scan_total and len(self.items) < self.scan_total else "SUCCESS"
        append_job({
            "job_type": "INVENTORY",
            "status": status,
            "started_at": self._iso(self._inventory_started_wall),
            "finished_at": self._iso(time.time()),
            "duration_seconds": round(max(0.0, time.time() - self._inventory_started_wall), 3) if self._inventory_started_wall else 0.0,
            "roots": list(self.roots),
            "files": int(summary.get("files", len(self.items)) or 0),
            "bytes": sum(int(getattr(x, "size", 0) or 0) for x in self.items),
            "duplicates": sum(1 for x in self.items if getattr(x, "duplicate_of", "")),
            "to_git": int(summary.get("to_git", 0) or 0),
            "git_review": int(summary.get("git_review", 0) or 0),
            "keep_local": int(summary.get("keep_local", 0) or 0),
            "review": int(summary.get("review", 0) or 0),
            "quarantine_candidates": int(summary.get("quarantine_candidates", 0) or 0),
            "automatic_deletion_performed": False,
            "automatic_main_write": False,
        })
        self._inventory_started_wall = 0.0

    def start_github_compare(self):
        self._github_started_wall = time.time()
        return super().start_github_compare()

    def _render_github_compare(self):
        super()._render_github_compare()
        counts = (self.github_report or {}).get("counts", {})
        append_job({
            "job_type": "GITHUB_COMPARE",
            "status": "SUCCESS",
            "started_at": self._iso(self._github_started_wall),
            "finished_at": self._iso(time.time()),
            "duration_seconds": round(max(0.0, time.time() - self._github_started_wall), 3) if self._github_started_wall else 0.0,
            "files": len((self.github_report or {}).get("items", [])),
            "identical": int(counts.get("IDENTICAL", 0) or 0),
            "local_only": int(counts.get("LOCAL_ONLY", 0) or 0),
            "divergent": int(counts.get("DIVERGENT", 0) or 0),
            "possible": int(counts.get("POSSIBLE_MATCH", 0) or 0),
            "unavailable": int(counts.get("REPO_UNAVAILABLE", 0) or 0),
            "unassigned": int(counts.get("UNASSIGNED", 0) or 0),
            "read_only": True,
            "automatic_main_write": False,
        })
        self._github_started_wall = 0.0

    def _status_changed(self, *_args):
        text = str(self.status_var.get() or "")
        if text == self._last_failure_marker:
            return
        if text.startswith("Fehler bei Inventur"):
            self._last_failure_marker = text
            append_job({
                "job_type": "INVENTORY", "status": "FAILED",
                "started_at": self._iso(self._inventory_started_wall), "finished_at": self._iso(time.time()),
                "roots": list(self.roots), "automatic_main_write": False,
            })
            self._inventory_started_wall = 0.0
        elif text.startswith("GitHub-Vergleich: Fehler"):
            self._last_failure_marker = text
            append_job({
                "job_type": "GITHUB_COMPARE", "status": "FAILED",
                "started_at": self._iso(self._github_started_wall), "finished_at": self._iso(time.time()),
                "read_only": True, "automatic_main_write": False,
            })
            self._github_started_wall = 0.0

    @staticmethod
    def _iso(value: float) -> str:
        if not value:
            return ""
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(value))
