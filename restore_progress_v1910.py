from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk


def format_bytes(value: int | float) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "–"
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class RestoreProgressDialog(tk.Toplevel):
    """Non-cancellable live monitor for an already running restore operation."""

    def __init__(self, parent, job_id: str = "", total_files: int = 0, total_bytes: int = 0):
        super().__init__(parent)
        self.parent = parent
        self.job_id = str(job_id or "")
        self.started = time.monotonic()
        self.total_files = int(total_files or 0)
        self.total_bytes = int(total_bytes or 0)
        self._last_bytes = 0
        self._last_tick = self.started
        self._instant_bps = 0.0
        self._finished = False

        self.title("PC Backup Vault – Wiederherstellung läuft")
        self.geometry("760x390")
        self.minsize(680, 350)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._ignore_close)

        head = ttk.Frame(self, padding=(18, 16, 18, 8)); head.pack(fill="x")
        ttk.Label(head, text="♻ Wiederherstellung läuft", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        sub = "Die Daten werden gelesen, entschlüsselt und per SHA-256 geprüft."
        if self.job_id:
            sub += f"  Job: {self.job_id}"
        ttk.Label(head, text=sub, wraplength=710).pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(self, padding=(18, 8, 18, 12)); body.pack(fill="both", expand=True)
        self.phase_var = tk.StringVar(value="Vorbereitung …")
        ttk.Label(body, textvariable=self.phase_var, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.file_var = tk.StringVar(value="Aktuelle Datei: –")
        ttk.Label(body, textvariable=self.file_var, wraplength=710).pack(anchor="w", pady=(4, 10))

        progress_row = ttk.Frame(body); progress_row.pack(fill="x")
        self.progress = ttk.Progressbar(progress_row, mode="determinate", maximum=100.0)
        self.progress.pack(side="left", fill="x", expand=True)
        self.percent_var = tk.StringVar(value="0.0 %")
        ttk.Label(progress_row, textvariable=self.percent_var, width=9, anchor="e", font=("Segoe UI", 11, "bold")).pack(side="right", padx=(10, 0))

        stats = ttk.LabelFrame(body, text="Live-Status", padding=12); stats.pack(fill="x", pady=(14, 0))
        stats.columnconfigure(1, weight=1); stats.columnconfigure(3, weight=1)
        self.files_var = tk.StringVar(value="0 / ?")
        self.data_var = tk.StringVar(value="0 B / ?")
        self.elapsed_var = tk.StringVar(value="00:00")
        self.eta_var = tk.StringVar(value="–")
        self.speed_var = tk.StringVar(value="–")
        self.avg_var = tk.StringVar(value="–")
        rows = (
            (0, "Dateien", self.files_var, "Daten", self.data_var),
            (1, "Bisherige Dauer", self.elapsed_var, "Restdauer", self.eta_var),
            (2, "Geschwindigkeit", self.speed_var, "Ø Geschwindigkeit", self.avg_var),
        )
        for r, l1, v1, l2, v2 in rows:
            ttk.Label(stats, text=l1 + ":").grid(row=r, column=0, sticky="w", padx=(0, 6), pady=4)
            ttk.Label(stats, textvariable=v1).grid(row=r, column=1, sticky="w", padx=(0, 18), pady=4)
            ttk.Label(stats, text=l2 + ":").grid(row=r, column=2, sticky="w", padx=(0, 6), pady=4)
            ttk.Label(stats, textvariable=v2).grid(row=r, column=3, sticky="w", pady=4)

        self.note_var = tk.StringVar(value="Bitte das Fenster während der Wiederherstellung geöffnet lassen.")
        ttk.Label(body, textvariable=self.note_var, wraplength=710).pack(anchor="w", pady=(12, 0))
        self.after(500, self._tick_clock)

    def _ignore_close(self):
        if not self._finished:
            self.note_var.set("Die Wiederherstellung läuft noch. Das Fenster wird nach Abschluss automatisch freigegeben.")
        else:
            self.destroy()

    def _tick_clock(self):
        if not self.winfo_exists():
            return
        elapsed = max(0.0, time.monotonic() - self.started)
        self.elapsed_var.set(format_duration(elapsed))
        if not self._finished:
            self.after(500, self._tick_clock)

    def update_progress(self, info: dict):
        if not self.winfo_exists():
            return
        now = time.monotonic()
        files_done = int(info.get("files_done") or 0)
        total_files = int(info.get("files_total") or self.total_files or 0)
        bytes_done = int(info.get("bytes_done") or 0)
        total_bytes = int(info.get("bytes_total") or self.total_bytes or 0)
        self.total_files = max(self.total_files, total_files)
        self.total_bytes = max(self.total_bytes, total_bytes)

        delta_t = max(0.001, now - self._last_tick)
        delta_b = max(0, bytes_done - self._last_bytes)
        if delta_b > 0:
            sample = delta_b / delta_t
            self._instant_bps = sample if self._instant_bps <= 0 else (self._instant_bps * 0.65 + sample * 0.35)
        self._last_tick = now
        self._last_bytes = max(self._last_bytes, bytes_done)

        elapsed = max(0.001, now - self.started)
        avg_bps = bytes_done / elapsed if bytes_done > 0 else 0.0
        if self.total_bytes > 0:
            pct = min(100.0, max(0.0, bytes_done * 100.0 / self.total_bytes))
            remaining = max(0, self.total_bytes - bytes_done)
            eta = remaining / avg_bps if avg_bps > 0 else None
        elif self.total_files > 0:
            pct = min(100.0, max(0.0, files_done * 100.0 / self.total_files))
            eta = None
        else:
            pct = 0.0
            eta = None

        self.progress["value"] = pct
        self.percent_var.set(f"{pct:.1f} %")
        self.phase_var.set(str(info.get("phase") or "Wiederherstellung läuft …"))
        current = str(info.get("current_file") or "–")
        self.file_var.set(f"Aktuelle Datei: {current}")
        self.files_var.set(f"{files_done} / {self.total_files or '?'}")
        self.data_var.set(f"{format_bytes(bytes_done)} / {format_bytes(self.total_bytes) if self.total_bytes else '?'}")
        self.elapsed_var.set(format_duration(elapsed))
        self.eta_var.set(format_duration(eta))
        self.speed_var.set(f"{format_bytes(self._instant_bps)}/s" if self._instant_bps > 0 else "–")
        self.avg_var.set(f"{format_bytes(avg_bps)}/s" if avg_bps > 0 else "–")

    def finish(self, success: bool, message: str = ""):
        if not self.winfo_exists():
            return
        self._finished = True
        if success:
            self.progress["value"] = 100.0
            self.percent_var.set("100.0 %")
            self.phase_var.set("Wiederherstellung abgeschlossen ✓")
        else:
            self.phase_var.set("Wiederherstellung abgebrochen / fehlgeschlagen")
        self.note_var.set(message or ("SHA-256-Prüfung abgeschlossen." if success else "Bitte Fehlermeldung prüfen."))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
