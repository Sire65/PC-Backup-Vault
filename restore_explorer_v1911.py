from __future__ import annotations

import threading
from pathlib import PureWindowsPath, Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from crypto_box import decrypt_text
from job_archive_v198 import (
    get_job,
    index_hidrive_job,
    list_job_files,
)
from restore_progress_v1910 import RestoreProgressDialog
from archive_restore_selective_v1911 import restore_archived_selection
from unified_reporting_v193 import human_size


CHECK_OFF = "☐"
CHECK_ON = "☑"
CHECK_PART = "◩"


def manifest_index_from_file_key(file_key: str):
    text = str(file_key or "")
    if not text.startswith("MANIFEST:"):
        return None
    parts = text.split(":", 3)
    if len(parts) < 4:
        return None
    try:
        return int(parts[2])
    except (TypeError, ValueError):
        return None


def _safe_decrypt(key, value):
    text = str(value or "")
    if not key:
        return text
    try:
        return decrypt_text(key, text)
    except Exception:
        return text


def _folder_parts(path: str):
    p = PureWindowsPath(str(path or ""))
    parts = []
    if p.drive:
        parts.append(p.drive)
    for value in p.parts:
        clean = str(value).strip("\\/")
        if not clean or value == p.drive:
            continue
        parts.append(clean)
    return parts or ["(ohne Ordner)"]


class RestoreExplorerWindow(tk.Toplevel):
    """Explorer-like logical view over the encrypted backup catalog."""

    def __init__(self, archive_window, job_id: str):
        super().__init__(archive_window)
        self.archive_window = archive_window
        self.app = archive_window.app
        self.job_id = str(job_id)
        self.key = self.app.master_key()
        self.selected_keys = set()
        self.file_by_iid = {}
        self.folder_iids = set()
        self._iid_counter = 0

        job = get_job(self.app.store, self.job_id) or {}
        self.job = job
        self.title(f"PC Backup Vault – Wiederherstellungs-Explorer · {self.job_id}")
        self.geometry("1180x760")
        self.minsize(900, 580)
        self.transient(archive_window)

        head = ttk.Frame(self, padding=(16, 14, 16, 8))
        head.pack(fill="x")
        ttk.Label(
            head, text="🔎 Wiederherstellungs-Explorer",
            font=("Segoe UI", 18, "bold")
        ).pack(side="left")
        ttk.Button(head, text="Schließen", command=self.destroy).pack(side="right")

        target = str(job.get("target_label") or job.get("backend_label") or "–")
        ttk.Label(
            self,
            text=f"Job {self.job_id} · Speicher: {target}\n"
                 "Ordner aufklappen und Dateien oder ganze Ordner auswählen. "
                 "Es werden nur die ausgewählten Daten zurückgeholt.",
            wraplength=1120,
            padding=(16, 0, 16, 10),
        ).pack(anchor="w")

        toolbar = ttk.Frame(self, padding=(16, 0, 16, 8))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="☑ Alles auswählen", command=self.select_all).pack(side="left")
        ttk.Button(toolbar, text="☐ Auswahl aufheben", command=self.clear_selection).pack(side="left", padx=(6, 0))
        ttk.Label(
            toolbar,
            text="Doppelklick oder Leertaste schaltet Datei/Ordner um.",
        ).pack(side="left", padx=(18, 0))
        self.selection_var = tk.StringVar(value="0 Dateien ausgewählt")
        ttk.Label(toolbar, textvariable=self.selection_var, font=("Segoe UI", 10, "bold")).pack(side="right")

        box = ttk.Frame(self, padding=(16, 0, 16, 8))
        box.pack(fill="both", expand=True)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            box,
            columns=("size", "modified", "backend"),
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="Ordner / Datei")
        self.tree.column("#0", width=610, minwidth=320, anchor="w")
        for col, text, width in (
            ("size", "Größe", 110),
            ("modified", "Geändert", 165),
            ("backend", "Speicher", 150),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w")

        sy = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(box, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Double-1>", self._toggle_current)
        self.tree.bind("<space>", self._toggle_current)

        foot = ttk.Frame(self, padding=(16, 8, 16, 16))
        foot.pack(fill="x")
        ttk.Label(
            foot,
            text="Sicherheit: Originale werden nicht überschrieben; die bestehende Restore-Logik "
                 "entschlüsselt und prüft jede zurückgeholte Datei per SHA-256.",
            wraplength=780,
        ).pack(side="left", fill="x", expand=True)
        self.restore_btn = ttk.Button(
            foot, text="♻ Auswahl wiederherstellen …", command=self.restore_selection,
            state="disabled",
        )
        self.restore_btn.pack(side="right")

        self._load_entries()

    def _new_iid(self, prefix):
        self._iid_counter += 1
        return f"{prefix}:{self._iid_counter}"

    def _load_entries(self):
        rows = list_job_files(self.app.store, self.job_id)
        if not rows:
            kind = str((self.job.get("locator") or {}).get("kind") or "").upper()
            if kind == "HIDRIVE":
                try:
                    index_hidrive_job(self.app, self.job_id)
                    rows = list_job_files(self.app.store, self.job_id)
                except Exception:
                    rows = []

        if not rows:
            messagebox.showinfo(
                "Wiederherstellungs-Explorer",
                "Für diesen Job ist noch kein Dateikatalog verfügbar.\n\n"
                "Bei HiDrive bitte die Verbindung prüfen und das Job-Archiv anschließend aktualisieren.",
                parent=self,
            )
            self.destroy()
            return

        folders = {}
        for row in rows:
            entry = dict(row)
            entry["name"] = _safe_decrypt(self.key, row.get("name_cipher"))
            entry["path"] = _safe_decrypt(self.key, row.get("path_cipher"))
            entry["manifest_index"] = manifest_index_from_file_key(row.get("file_key"))
            parts = _folder_parts(entry["path"])

            parent = ""
            cumulative = []
            for part in parts:
                cumulative.append(part)
                key = tuple(cumulative)
                if key not in folders:
                    iid = self._new_iid("folder")
                    self.tree.insert(parent, "end", iid=iid, text=f"{CHECK_OFF} {part}", open=False)
                    folders[key] = iid
                    self.folder_iids.add(iid)
                parent = folders[key]

            file_iid = self._new_iid("file")
            self.tree.insert(
                parent,
                "end",
                iid=file_iid,
                text=f"{CHECK_OFF} {entry['name'] or '–'}",
                values=(
                    human_size(entry.get("original_size")),
                    str(entry.get("modified_at") or "–"),
                    str(entry.get("backend") or "–"),
                ),
            )
            self.file_by_iid[file_iid] = entry

        self._update_selection_summary()

    def _toggle_current(self, _event=None):
        iid = self.tree.focus()
        if not iid:
            return "break"
        if iid in self.file_by_iid:
            key = str(self.file_by_iid[iid].get("file_key") or iid)
            if key in self.selected_keys:
                self.selected_keys.remove(key)
            else:
                self.selected_keys.add(key)
        else:
            descendants = self._descendant_file_iids(iid)
            keys = {str(self.file_by_iid[x].get("file_key") or x) for x in descendants}
            if keys and keys.issubset(self.selected_keys):
                self.selected_keys.difference_update(keys)
            else:
                self.selected_keys.update(keys)
        self._refresh_marks()
        self._update_selection_summary()
        return "break"

    def _descendant_file_iids(self, iid):
        out = []
        for child in self.tree.get_children(iid):
            if child in self.file_by_iid:
                out.append(child)
            else:
                out.extend(self._descendant_file_iids(child))
        return out

    def _refresh_marks(self):
        for iid, entry in self.file_by_iid.items():
            key = str(entry.get("file_key") or iid)
            mark = CHECK_ON if key in self.selected_keys else CHECK_OFF
            self.tree.item(iid, text=f"{mark} {entry.get('name') or '–'}")

        for iid in reversed(list(self.folder_iids)):
            file_iids = self._descendant_file_iids(iid)
            keys = {str(self.file_by_iid[x].get("file_key") or x) for x in file_iids}
            count = len(keys & self.selected_keys)
            mark = CHECK_OFF if count == 0 else (CHECK_ON if count == len(keys) else CHECK_PART)
            text = str(self.tree.item(iid, "text") or "")
            label = text[2:] if len(text) >= 2 and text[0] in {CHECK_OFF, CHECK_ON, CHECK_PART} else text
            self.tree.item(iid, text=f"{mark} {label}")

    def _update_selection_summary(self):
        selected = [
            entry for entry in self.file_by_iid.values()
            if str(entry.get("file_key") or "") in self.selected_keys
        ]
        total = sum(max(0, int(x.get("original_size") or 0)) for x in selected)
        self.selection_var.set(f"{len(selected)} Datei(en) · {human_size(total)} ausgewählt")
        self.restore_btn.configure(state="normal" if selected else "disabled")

    def select_all(self):
        self.selected_keys = {
            str(entry.get("file_key") or "")
            for entry in self.file_by_iid.values()
            if entry.get("file_key")
        }
        self._refresh_marks()
        self._update_selection_summary()

    def clear_selection(self):
        self.selected_keys.clear()
        self._refresh_marks()
        self._update_selection_summary()

    def selected_entries(self):
        return [
            entry for entry in self.file_by_iid.values()
            if str(entry.get("file_key") or "") in self.selected_keys
        ]

    def restore_selection(self):
        entries = self.selected_entries()
        if not entries:
            return
        self.archive_window._restore_explorer_entries_v1911(self.job_id, entries, self)


def apply_restore_explorer_v1911(JobArchiveWindow, RestoreAssistantClass):
    """Patch the existing archive UI additively; existing backup paths stay untouched."""
    if getattr(JobArchiveWindow, "_restore_explorer_v1911", False):
        return

    def open_explorer(self):
        if self._restore_progress is not None:
            try:
                if self._restore_progress.winfo_exists():
                    self._restore_progress.lift()
                    return
            except Exception:
                self._restore_progress = None
        jid = self._selected_job_id()
        if not jid:
            messagebox.showinfo("Job-Archiv", "Bitte zuerst einen Job auswählen.", parent=self)
            return
        RestoreExplorerWindow(self, jid)

    def restore_entries(self, jid, entries, explorer=None):
        job = get_job(self.app.store, jid) or {}
        kind = str((job.get("locator") or {}).get("kind") or "").upper()
        backend = str(job.get("backend_label") or "").lower()

        if kind == "NEON" or backend in {"neon", "backblaze b2"}:
            ids = {
                str(entry.get("source_file_id") or "")
                for entry in entries if entry.get("source_file_id")
            }
            if not ids:
                messagebox.showerror(
                    "Wiederherstellung",
                    "Die ausgewählten Datenbankdateien konnten nicht eindeutig zugeordnet werden.",
                    parent=explorer or self,
                )
                return
            self.app._archive_restore_job_id = jid
            self.app._archive_restore_selected_ids = ids
            if explorer:
                explorer.destroy()
            self.app.open_restore_assistant()
            return

        indices = {
            int(entry["manifest_index"])
            for entry in entries if entry.get("manifest_index") is not None
        }
        if not indices:
            messagebox.showerror(
                "Wiederherstellung",
                "Für die Auswahl fehlen die Manifest-Verweise. Bitte das Job-Archiv aktualisieren.",
                parent=explorer or self,
            )
            return

        destination = filedialog.askdirectory(
            parent=explorer or self,
            title=f"Wiederherstellungsziel für {len(entries)} ausgewählte Datei(en)",
        )
        if not destination:
            return

        total_bytes = sum(max(0, int(x.get("original_size") or 0)) for x in entries)
        self.details.config(text=f"Selektive Wiederherstellung von {jid} läuft …")
        self.restore_btn.configure(state="disabled")
        progress = RestoreProgressDialog(self, jid, len(entries), total_bytes)
        self._restore_progress = progress
        try:
            progress.grab_set()
        except Exception:
            pass
        if explorer:
            try:
                explorer.destroy()
            except Exception:
                pass

        def on_progress(info):
            data = dict(info or {})
            try:
                self.after(0, lambda d=data: progress.update_progress(d))
            except Exception:
                pass

        def work():
            try:
                result = restore_archived_selection(
                    self.app, jid, Path(destination), indices, progress=on_progress
                )
                self.after(0, lambda: self._restore_done(jid, result, progress))
            except Exception as exc:
                self.after(0, lambda e=exc: self._restore_failed(jid, e, progress))

        threading.Thread(
            target=work,
            name=f"pbv-selective-restore-{jid[:8]}",
            daemon=True,
        ).start()

    JobArchiveWindow.restore_selected = open_explorer
    JobArchiveWindow.show_files = open_explorer
    JobArchiveWindow._restore_explorer_entries_v1911 = restore_entries

    original_load_records = RestoreAssistantClass._load_records

    def load_records_with_preselection(self):
        original_load_records(self)
        requested = getattr(self.app, "_archive_restore_selected_ids", None)
        if not requested:
            return
        valid = {str(r[0]) for r in self.records}
        self.selected_ids = {str(x) for x in requested if str(x) in valid}
        self.app._archive_restore_selected_ids = None

    RestoreAssistantClass._load_records = load_records_with_preselection
    JobArchiveWindow._restore_explorer_v1911 = True
