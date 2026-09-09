from __future__ import annotations

import os
import posixpath
import stat as statmod
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog


CHUNK_SIZE = 256 * 1024


def format_bytes(value: int | float) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "–"
    sec = max(0, int(seconds or 0))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class OperationProgressDialog(tk.Toplevel):
    """Visible activity window for long and short file operations."""

    def __init__(self, parent, title: str, phase: str = "Vorbereitung …"):
        super().__init__(parent)
        self.started = time.monotonic()
        self._finished = False
        self._indeterminate = True
        self._last_bytes = 0
        self._last_tick = self.started
        self._instant_bps = 0.0
        self.title(f"PC Backup Vault – {title}")
        self.geometry("760x390")
        self.minsize(680, 350)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._ignore_close)

        head = ttk.Frame(self, padding=(18, 16, 18, 8)); head.pack(fill="x")
        self.head_var = tk.StringVar(value=title)
        ttk.Label(head, textvariable=self.head_var, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(head, text="PC Backup Vault zeigt den Arbeitsfortschritt live an.").pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(self, padding=(18, 8, 18, 12)); body.pack(fill="both", expand=True)
        self.phase_var = tk.StringVar(value=phase)
        ttk.Label(body, textvariable=self.phase_var, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.file_var = tk.StringVar(value="Aktuelle Datei: –")
        ttk.Label(body, textvariable=self.file_var, wraplength=710).pack(anchor="w", pady=(4, 10))

        row = ttk.Frame(body); row.pack(fill="x")
        self.progress = ttk.Progressbar(row, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress.start(12)
        self.percent_var = tk.StringVar(value="läuft …")
        ttk.Label(row, textvariable=self.percent_var, width=10, anchor="e", font=("Segoe UI", 11, "bold")).pack(side="right", padx=(10, 0))

        stats = ttk.LabelFrame(body, text="Live-Status", padding=12); stats.pack(fill="x", pady=(14, 0))
        stats.columnconfigure(1, weight=1); stats.columnconfigure(3, weight=1)
        self.files_var = tk.StringVar(value="–")
        self.data_var = tk.StringVar(value="–")
        self.elapsed_var = tk.StringVar(value="00:00")
        self.eta_var = tk.StringVar(value="–")
        self.speed_var = tk.StringVar(value="–")
        self.avg_var = tk.StringVar(value="–")
        for r, l1, v1, l2, v2 in (
            (0, "Dateien", self.files_var, "Daten", self.data_var),
            (1, "Laufzeit", self.elapsed_var, "Restdauer", self.eta_var),
            (2, "Geschwindigkeit", self.speed_var, "Ø Geschwindigkeit", self.avg_var),
        ):
            ttk.Label(stats, text=l1 + ":").grid(row=r, column=0, sticky="w", padx=(0, 6), pady=4)
            ttk.Label(stats, textvariable=v1).grid(row=r, column=1, sticky="w", padx=(0, 18), pady=4)
            ttk.Label(stats, text=l2 + ":").grid(row=r, column=2, sticky="w", padx=(0, 6), pady=4)
            ttk.Label(stats, textvariable=v2).grid(row=r, column=3, sticky="w", pady=4)

        self.note_var = tk.StringVar(value="Das Fenster bleibt sichtbar, solange der Vorgang arbeitet.")
        ttk.Label(body, textvariable=self.note_var, wraplength=710).pack(anchor="w", pady=(12, 0))
        self.after(500, self._tick)

    def _ignore_close(self):
        if self._finished:
            self.destroy()
        else:
            self.note_var.set("Der Vorgang läuft noch. Das Fortschrittsfenster wird nach Abschluss freigegeben.")

    def _tick(self):
        if not self.winfo_exists():
            return
        self.elapsed_var.set(format_duration(time.monotonic() - self.started))
        if not self._finished:
            self.after(500, self._tick)

    def set_phase(self, phase: str, current_file: str = ""):
        self.phase_var.set(str(phase or "Arbeite …"))
        if current_file:
            self.file_var.set(f"Aktuelle Datei: {current_file}")

    def update_progress(self, *, phase: str = "", current_file: str = "", files_done: int = 0,
                        files_total: int = 0, bytes_done: int = 0, bytes_total: int = 0):
        if not self.winfo_exists():
            return
        now = time.monotonic()
        elapsed = max(0.001, now - self.started)
        files_done = max(0, int(files_done or 0)); files_total = max(0, int(files_total or 0))
        bytes_done = max(0, int(bytes_done or 0)); bytes_total = max(0, int(bytes_total or 0))
        if phase:
            self.phase_var.set(phase)
        if current_file:
            self.file_var.set(f"Aktuelle Datei: {current_file}")

        delta_t = max(0.001, now - self._last_tick)
        delta_b = max(0, bytes_done - self._last_bytes)
        if delta_b:
            sample = delta_b / delta_t
            self._instant_bps = sample if self._instant_bps <= 0 else self._instant_bps * 0.65 + sample * 0.35
        self._last_tick = now; self._last_bytes = max(self._last_bytes, bytes_done)
        avg = bytes_done / elapsed if bytes_done else 0.0

        if bytes_total > 0:
            pct = min(100.0, bytes_done * 100.0 / bytes_total)
            eta = (bytes_total - bytes_done) / avg if avg > 0 else None
        elif files_total > 0:
            pct = min(100.0, files_done * 100.0 / files_total)
            eta = (files_total - files_done) * elapsed / files_done if files_done > 0 else None
        else:
            pct = None; eta = None

        if pct is not None:
            if self._indeterminate:
                self.progress.stop(); self.progress.configure(mode="determinate", maximum=100.0); self._indeterminate = False
            self.progress["value"] = pct
            self.percent_var.set(f"{pct:.1f} %")
        self.files_var.set(f"{files_done} / {files_total or '?'}")
        self.data_var.set(f"{format_bytes(bytes_done)} / {format_bytes(bytes_total) if bytes_total else '?'}")
        self.elapsed_var.set(format_duration(elapsed))
        self.eta_var.set(format_duration(eta))
        self.speed_var.set(f"{format_bytes(self._instant_bps)}/s" if self._instant_bps > 0 else "–")
        self.avg_var.set(f"{format_bytes(avg)}/s" if avg > 0 else "–")

    def finish(self, success: bool, message: str = ""):
        if not self.winfo_exists():
            return
        self._finished = True
        if self._indeterminate:
            self.progress.stop(); self.progress.configure(mode="determinate", maximum=100.0); self._indeterminate = False
        if success:
            self.progress["value"] = 100.0; self.percent_var.set("100.0 %")
            self.phase_var.set("Abgeschlossen ✓")
        else:
            self.phase_var.set("Fehlgeschlagen")
        self.note_var.set(message or ("Vorgang erfolgreich abgeschlossen." if success else "Bitte Fehlermeldung prüfen."))
        self.protocol("WM_DELETE_WINDOW", self.destroy)


def _ensure_remote_dir(sftp, path: str):
    path = posixpath.normpath(path)
    if path in ("", "/"):
        return
    parts = path.strip("/").split("/")
    current = ""
    for part in parts:
        current += "/" + part
        try:
            info = sftp.stat(current)
            if not statmod.S_ISDIR(int(getattr(info, "st_mode", 0) or 0)):
                raise NotADirectoryError(current)
        except OSError:
            sftp.mkdir(current)


def _remote_manifest(sftp, rows: list[dict]) -> tuple[list[dict], list[str], int]:
    files: list[dict] = []
    dirs: list[str] = []

    def walk(remote: str, rel: str, is_dir: bool, size: int = 0):
        if is_dir:
            dirs.append(rel)
            for attr in sftp.listdir_attr(remote):
                name = str(getattr(attr, "filename", "") or "")
                if not name or name in {".", ".."}:
                    continue
                child_remote = posixpath.join(remote, name)
                child_rel = posixpath.join(rel, name)
                child_is_dir = statmod.S_ISDIR(int(getattr(attr, "st_mode", 0) or 0))
                walk(child_remote, child_rel, child_is_dir, int(getattr(attr, "st_size", 0) or 0))
        else:
            files.append({"remote": remote, "rel": rel, "size": int(size or 0)})

    for row in rows:
        walk(str(row.get("path") or ""), str(row.get("name") or ""), bool(row.get("is_dir")), int(row.get("size") or 0))
    return files, dirs, sum(int(x["size"]) for x in files)


def _copy_stream(reader, writer, total: int, on_chunk):
    done = 0
    while True:
        chunk = reader.read(CHUNK_SIZE)
        if not chunk:
            break
        writer.write(chunk)
        done += len(chunk)
        on_chunk(done, total)
    return done


def _clipboard(widget, text: str):
    try:
        widget.clipboard_clear(); widget.clipboard_append(str(text)); widget.update_idletasks()
    except Exception:
        pass


def install_global_context_menus(root):
    """Install standard right-click behaviour for all present/future widgets in this Tk interpreter."""
    if getattr(root, "_pbv_context_classes_v1917", False):
        return
    root._pbv_context_classes_v1917 = True

    def text_menu(event):
        w = event.widget
        menu = tk.Menu(w, tearoff=False)
        menu.add_command(label="Rückgängig", command=lambda: w.event_generate("<<Undo>>"))
        menu.add_separator()
        menu.add_command(label="Ausschneiden", command=lambda: w.event_generate("<<Cut>>"))
        menu.add_command(label="Kopieren", command=lambda: w.event_generate("<<Copy>>"))
        menu.add_command(label="Einfügen", command=lambda: w.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Alles auswählen", command=lambda: w.event_generate("<<SelectAll>>"))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def tree_menu(event):
        tree = event.widget
        row = tree.identify_row(event.y)
        if row and row not in tree.selection():
            tree.selection_set(row); tree.focus(row)
        selected = list(tree.selection())
        if not selected:
            return
        menu = tk.Menu(tree, tearoff=False)

        def copy_rows():
            lines = []
            for iid in tree.selection():
                vals = list(tree.item(iid, "values") or ())
                text = str(tree.item(iid, "text") or "").strip()
                if text:
                    vals.insert(0, text)
                lines.append("\t".join(str(x) for x in vals))
            _clipboard(tree, "\n".join(lines))

        def copy_cell():
            col = tree.identify_column(event.x)
            iid = tree.identify_row(event.y)
            if not iid:
                return
            if col == "#0":
                value = tree.item(iid, "text")
            else:
                try: value = tree.set(iid, col)
                except Exception: value = ""
            _clipboard(tree, value)

        menu.add_command(label="Zelle kopieren", command=copy_cell)
        menu.add_command(label="Auswahl kopieren", command=copy_rows)
        menu.add_separator()
        menu.add_command(label="Alles auswählen", command=lambda: tree.selection_set(tree.get_children("")))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    for cls in ("Entry", "TEntry", "Text", "TCombobox"):
        root.bind_class(cls, "<Button-3>", text_menu, add="+")
    root.bind_class("Treeview", "<Button-3>", tree_menu, add="+")


def _confirm(parent, title: str, text: str) -> bool:
    return bool(messagebox.askyesno(title, text, parent=parent, default="no"))


def apply_context_progress_v1917(AppClass, live_module, JobArchiveWindow=None, JobFilesWindow=None):
    """Global context menus plus full HiDrive context/actions/progress."""
    if getattr(AppClass, "_context_progress_v1917", False):
        return

    original_app_build = AppClass._build
    def app_build(self):
        original_app_build(self)
        install_global_context_menus(self)
    AppClass._build = app_build

    Explorer = live_module.HiDriveLiveExplorer
    original_init = Explorer.__init__
    original_run_operation = Explorer._run_operation

    def explorer_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._pbv_domain_context = True
        self.tree.bind("<Button-3>", lambda e: self._pbv_context_menu_v1917(e), add="+")
        self.tree.bind("<Shift-F10>", lambda e: self._pbv_context_menu_v1917(e), add="+")

    def _progress_ui(self, progress, data: dict):
        try:
            self.after(0, lambda d=dict(data): progress.update_progress(**d))
        except Exception:
            pass

    def run_operation(self, title: str, worker, done_text: str):
        if self.busy:
            return
        self._set_busy(True, title + " …")
        progress = OperationProgressDialog(self, title, title + " …")
        try: progress.grab_set()
        except Exception: pass
        def work():
            try:
                worker()
                self.after(0, lambda: _done(self, progress, done_text))
            except Exception as exc:
                self.after(0, lambda e=exc: _failed(self, progress, title, e))
        import threading
        threading.Thread(target=work, name="pbv-hidrive-live-op-v1917", daemon=True).start()

    def _done(self, progress, text):
        try: progress.finish(True, text); progress.grab_release()
        except Exception: pass
        self._set_busy(False, text)
        self.refresh()
        try: progress.after(900, progress.destroy)
        except Exception: pass

    def _failed(self, progress, title, exc):
        try: progress.finish(False, str(exc)); progress.grab_release()
        except Exception: pass
        self._set_busy(False, f"{title} fehlgeschlagen")
        messagebox.showerror("HiDrive Live-Explorer", f"{title} fehlgeschlagen.\n\n{exc}", parent=progress if progress.winfo_exists() else self)
        try: progress.destroy()
        except Exception: pass

    def progress_operation(self, title: str, worker, done_text: str):
        if self.busy:
            return
        self._set_busy(True, title + " …")
        progress = OperationProgressDialog(self, title, "Umfang wird ermittelt …")
        try: progress.grab_set()
        except Exception: pass
        def report(**data): _progress_ui(self, progress, data)
        def work():
            try:
                worker(report)
                self.after(0, lambda: _done(self, progress, done_text))
            except Exception as exc:
                self.after(0, lambda e=exc: _failed(self, progress, title, e))
        import threading
        threading.Thread(target=work, name="pbv-hidrive-transfer-v1917", daemon=True).start()

    def download_selected(self):
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("Herunterladen", "Bitte Dateien oder Ordner auswählen.", parent=self); return
        dest = filedialog.askdirectory(parent=self, title="Lokalen Zielordner auswählen")
        if not dest: return
        if not _confirm(self, "Download starten", f"{len(rows)} Auswahl(en) von HiDrive herunterladen?\n\nZiel: {dest}"):
            return
        account = self._account(); base = Path(dest)
        def worker(report):
            with live_module.sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                files, dirs, total = _remote_manifest(sftp, rows)
                for rel in dirs:
                    (base / Path(rel)).mkdir(parents=True, exist_ok=True)
                bytes_done = 0; files_done = 0
                report(phase="Download läuft", files_done=0, files_total=len(files), bytes_done=0, bytes_total=total)
                for item in files:
                    local = base / Path(item["rel"]); local.parent.mkdir(parents=True, exist_ok=True)
                    before = bytes_done
                    with sftp.open(item["remote"], "rb") as src, open(local, "wb") as dst:
                        def chunk(done, _total):
                            report(phase="Download läuft", current_file=item["remote"], files_done=files_done,
                                   files_total=len(files), bytes_done=before + done, bytes_total=total)
                        copied = _copy_stream(src, dst, item["size"], chunk)
                    bytes_done += copied; files_done += 1
                    report(phase="Download läuft", current_file=item["remote"], files_done=files_done,
                           files_total=len(files), bytes_done=bytes_done, bytes_total=total)
        self._pbv_progress_operation_v1917("HiDrive-Download", worker, f"{len(rows)} Auswahl(en) heruntergeladen")

    def upload_files(self):
        rows = self.selected_rows()
        target = self.current_path
        if len(rows) == 1 and rows[0].get("is_dir"):
            target = str(rows[0]["path"])
        files = filedialog.askopenfilenames(parent=self, title="Dateien für HiDrive auswählen")
        if not files: return
        remotes = [posixpath.join(target, Path(x).name) for x in files]
        if not self._confirm_protected(remotes, "Hochladen"):
            return
        total = sum(Path(x).stat().st_size for x in files)
        if not _confirm(self, "Upload starten", f"{len(files)} Datei(en) nach HiDrive hochladen?\n\nZiel: {target}\nDaten: {format_bytes(total)}\n\nVorhandene Dateien gleichen Namens würden überschrieben."):
            return
        account = self._account()
        def worker(report):
            bytes_done = 0; files_done = 0
            with live_module.sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                _ensure_remote_dir(sftp, target)
                report(phase="Upload läuft", files_done=0, files_total=len(files), bytes_done=0, bytes_total=total)
                for local_name, remote in zip(files, remotes):
                    local = Path(local_name); before = bytes_done; size = local.stat().st_size
                    with open(local, "rb") as src, sftp.open(remote, "wb") as dst:
                        def chunk(done, _total):
                            report(phase="Upload läuft", current_file=str(local), files_done=files_done,
                                   files_total=len(files), bytes_done=before + done, bytes_total=total)
                        copied = _copy_stream(src, dst, size, chunk)
                    bytes_done += copied; files_done += 1
                    report(phase="Upload läuft", current_file=str(local), files_done=files_done,
                           files_total=len(files), bytes_done=bytes_done, bytes_total=total)
        self._pbv_progress_operation_v1917("HiDrive-Upload", worker, f"{len(files)} Datei(en) hochgeladen")

    def copy_selected(self):
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("Kopieren", "Bitte Dateien oder Ordner auswählen.", parent=self); return
        picker = live_module.RemoteFolderPicker(self, self.store, self._account(), self.current_path)
        self.wait_window(picker); dest_dir = picker.result
        if not dest_dir: return
        dests = [posixpath.join(dest_dir, str(r["name"])) for r in rows]
        if not self._confirm_protected(dests, "Kopieren"):
            return
        for row in rows:
            if row.get("is_dir") and live_module._within(dest_dir, str(row["path"])):
                messagebox.showwarning("Kopieren", f"Ordner kann nicht in sich selbst kopiert werden:\n{row['name']}", parent=self); return
        if not _confirm(self, "HiDrive kopieren", f"{len(rows)} Auswahl(en) nach\n{dest_dir}\nkopieren?\n\nExistierende Ziele werden aus Sicherheitsgründen nicht überschrieben."):
            return
        account = self._account()
        def worker(report):
            with live_module.sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                files, dirs, total = _remote_manifest(sftp, rows)
                for dest in dests:
                    try: sftp.stat(dest); raise FileExistsError(f"Ziel existiert bereits: {dest}")
                    except FileExistsError: raise
                    except OSError: pass
                for rel in dirs:
                    _ensure_remote_dir(sftp, posixpath.join(dest_dir, rel))
                bytes_done = 0; files_done = 0
                report(phase="HiDrive-Kopie läuft", files_done=0, files_total=len(files), bytes_done=0, bytes_total=total)
                for item in files:
                    remote_dest = posixpath.join(dest_dir, item["rel"]); _ensure_remote_dir(sftp, posixpath.dirname(remote_dest))
                    before = bytes_done
                    with sftp.open(item["remote"], "rb") as src, sftp.open(remote_dest, "wb") as dst:
                        def chunk(done, _total):
                            report(phase="HiDrive-Kopie läuft", current_file=item["remote"], files_done=files_done,
                                   files_total=len(files), bytes_done=before + done, bytes_total=total)
                        copied = _copy_stream(src, dst, item["size"], chunk)
                    bytes_done += copied; files_done += 1
                    report(phase="HiDrive-Kopie läuft", current_file=item["remote"], files_done=files_done,
                           files_total=len(files), bytes_done=bytes_done, bytes_total=total)
        self._pbv_progress_operation_v1917("HiDrive kopieren", worker, f"{len(rows)} Auswahl(en) kopiert")

    def delete_selected(self):
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("Löschen", "Bitte Dateien oder Ordner auswählen.", parent=self); return
        paths = [str(r["path"]) for r in rows]
        if not self._confirm_protected(paths, "Löschen"):
            return
        names = "\n".join("• " + str(r["name"]) for r in rows[:12])
        if len(rows) > 12: names += f"\n… und {len(rows)-12} weitere"
        if not _confirm(self, "HiDrive löschen", f"Diese {len(rows)} Auswahl(en) wirklich dauerhaft auf HiDrive löschen?\n\n{names}\n\nOrdner werden einschließlich ihres Inhalts gelöscht. Diese Aktion kann nicht rückgängig gemacht werden."):
            return
        account = self._account()
        def worker(report):
            with live_module.sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                files, dirs, total = _remote_manifest(sftp, rows)
                bytes_done = 0; files_done = 0; total_entries = len(files) + len(dirs)
                report(phase="Löschen läuft", files_done=0, files_total=total_entries, bytes_done=0, bytes_total=total)
                for item in files:
                    if item["remote"] == self.home: raise RuntimeError("HiDrive-Benutzerordner darf nicht gelöscht werden")
                    sftp.remove(item["remote"]); bytes_done += item["size"]; files_done += 1
                    report(phase="Löschen läuft", current_file=item["remote"], files_done=files_done,
                           files_total=total_entries, bytes_done=bytes_done, bytes_total=total)
                for rel in sorted(dirs, key=lambda p: p.count("/"), reverse=True):
                    remote = None
                    for row in rows:
                        name = str(row["name"])
                        if rel == name or rel.startswith(name + "/"):
                            remote = posixpath.join(posixpath.dirname(str(row["path"])), rel); break
                    if remote and remote != self.home:
                        sftp.rmdir(remote); files_done += 1
                        report(phase="Löschen läuft", current_file=remote, files_done=files_done,
                               files_total=total_entries, bytes_done=bytes_done, bytes_total=total)
        self._pbv_progress_operation_v1917("HiDrive löschen", worker, f"{len(rows)} Auswahl(en) gelöscht")

    def rename_selected(self):
        rows = self.selected_rows()
        if len(rows) != 1:
            messagebox.showinfo("Umbenennen", "Bitte genau eine Datei oder einen Ordner auswählen.", parent=self); return
        row = rows[0]
        if not self._confirm_protected([row["path"]], "Umbenennen"): return
        new_name = simpledialog.askstring("Umbenennen", "Neuer Name:", initialvalue=row["name"], parent=self)
        new_name = str(new_name or "").strip()
        if not new_name or new_name == row["name"]: return
        if "/" in new_name or "\\" in new_name or new_name in (".", ".."):
            messagebox.showwarning("HiDrive", "Bitte nur einen Namen ohne Pfadtrenner eingeben.", parent=self); return
        parent_remote = posixpath.dirname(str(row["path"]).rstrip("/")) or self.home
        dest = posixpath.join(parent_remote, new_name)
        if not self._confirm_protected([dest], "Umbenennen"): return
        if not _confirm(self, "Umbenennen bestätigen", f"„{row['name']}“ wirklich umbenennen in\n„{new_name}“?"):
            return
        account = self._account()
        self._run_operation("Umbenennen", lambda: self._rename(account, row["path"], dest), f"{row['name']} wurde umbenannt")

    def new_folder(self):
        rows = self.selected_rows(); target = self.current_path
        if len(rows) == 1 and rows[0].get("is_dir"): target = str(rows[0]["path"])
        name = simpledialog.askstring("Neuer HiDrive-Ordner", f"Neuer Ordner in:\n{target}\n\nName:", parent=self)
        name = str(name or "").strip()
        if not name: return
        if "/" in name or "\\" in name or name in (".", ".."):
            messagebox.showwarning("HiDrive", "Bitte nur einen Ordnernamen ohne Pfadtrenner eingeben.", parent=self); return
        remote = posixpath.join(target, name)
        if not self._confirm_protected([remote], "Ordner anlegen"): return
        if not _confirm(self, "Ordner anlegen", f"Ordner „{name}“ wirklich anlegen in\n{target}?"):
            return
        account = self._account(); self._run_operation("Ordner anlegen", lambda: self._mkdir(account, remote), f"Ordner {name} angelegt")

    def properties_selected(self):
        rows = self.selected_rows()
        if len(rows) != 1:
            messagebox.showinfo("Eigenschaften", "Bitte genau einen Eintrag auswählen.", parent=self); return
        r = rows[0]
        hidden = "Ja" if r.get("hidden") else "Nein"
        protected = "Ja" if live_module._is_protected(str(r["path"]), self.home) else "Nein"
        kind = "Ordner" if r.get("is_dir") else "Datei"
        messagebox.showinfo("HiDrive Eigenschaften", f"Name: {r['name']}\nTyp: {kind}\nGröße: {'–' if r.get('is_dir') else format_bytes(r.get('size', 0))}\nPfad: {r['path']}\nVersteckt: {hidden}\nBackup-geschützt: {protected}", parent=self)

    def copy_path(self):
        rows = self.selected_rows()
        if rows: _clipboard(self, "\n".join(str(r["path"]) for r in rows))

    def context_menu(self, event):
        tree = self.tree
        iid = tree.identify_row(getattr(event, "y", 0)) if hasattr(event, "y") else tree.focus()
        if iid and iid in getattr(self, "_tree_rows", {}):
            if iid not in tree.selection(): tree.selection_set(iid)
            tree.focus(iid)
        rows = self.selected_rows()
        menu = tk.Menu(tree, tearoff=False)
        if len(rows) == 1 and rows[0].get("is_dir"):
            menu.add_command(label="📂 Öffnen / aufklappen", command=self.open_selected)
        menu.add_command(label="⬇ Herunterladen …", command=self.download_selected, state="normal" if rows else "disabled")
        menu.add_command(label="⬆ Dateien hochladen …", command=self.upload_files)
        menu.add_separator()
        menu.add_command(label="📋 Kopieren nach …", command=self.copy_selected, state="normal" if rows else "disabled")
        menu.add_command(label="↪ Verschieben nach …", command=self.move_selected, state="normal" if rows else "disabled")
        menu.add_command(label="✏ Umbenennen …", command=self.rename_selected, state="normal" if len(rows) == 1 else "disabled")
        menu.add_command(label="🗑 Löschen …", command=self.delete_selected, state="normal" if rows else "disabled")
        menu.add_separator()
        menu.add_command(label="📁 Neuer Ordner …", command=self.new_folder)
        menu.add_command(label="Pfad kopieren", command=self._pbv_copy_path_v1917, state="normal" if rows else "disabled")
        menu.add_command(label="Eigenschaften", command=self._pbv_properties_v1917, state="normal" if len(rows) == 1 else "disabled")
        menu.add_separator(); menu.add_command(label="↻ Aktualisieren", command=self.refresh)
        x = getattr(event, "x_root", tree.winfo_rootx() + 40); y = getattr(event, "y_root", tree.winfo_rooty() + 40)
        menu.tk_popup(x, y)
        return "break"

    Explorer.__init__ = explorer_init
    Explorer._run_operation = run_operation
    Explorer._pbv_progress_operation_v1917 = progress_operation
    Explorer.download_selected = download_selected
    Explorer.upload_files = upload_files
    Explorer.copy_selected = copy_selected
    Explorer.delete_selected = delete_selected
    Explorer.rename_selected = rename_selected
    Explorer.new_folder = new_folder
    Explorer._pbv_properties_v1917 = properties_selected
    Explorer._pbv_copy_path_v1917 = copy_path
    Explorer._pbv_context_menu_v1917 = context_menu

    # Job archive: domain-specific right click, while restore itself keeps its
    # existing progress dialog and SHA verification.
    if JobArchiveWindow is not None and not getattr(JobArchiveWindow, "_context_v1917", False):
        old_init = JobArchiveWindow.__init__
        def archive_init(self, *args, **kwargs):
            old_init(self, *args, **kwargs)
            def menu(event):
                iid = self.tree.identify_row(event.y)
                if iid: self.tree.selection_set(iid); self.tree.focus(iid); self._show_details()
                if not self.tree.selection(): return
                m = tk.Menu(self.tree, tearoff=False)
                m.add_command(label="🔎 Backup-Explorer / Dateien öffnen", command=self.show_files)
                m.add_command(label="♻ Wiederherstellen …", command=self.restore_selected)
                m.add_separator()
                m.add_command(label="Job-ID kopieren", command=lambda: _clipboard(self.tree, self._selected_job_id() or ""))
                m.add_command(label="↻ Aktualisieren", command=self.refresh)
                m.tk_popup(event.x_root, event.y_root); return "break"
            self.tree.bind("<Button-3>", menu, add="+")
        JobArchiveWindow.__init__ = archive_init
        JobArchiveWindow._context_v1917 = True

    if JobFilesWindow is not None and not getattr(JobFilesWindow, "_context_v1917", False):
        old_files_init = JobFilesWindow.__init__
        def files_init(self, *args, **kwargs):
            old_files_init(self, *args, **kwargs)
            def menu(event):
                iid = self.tree.identify_row(event.y)
                if iid: self.tree.selection_set(iid); self.tree.focus(iid)
                if not self.tree.selection(): return
                values = self.tree.item(self.tree.selection()[0], "values")
                m = tk.Menu(self.tree, tearoff=False)
                m.add_command(label="Dateiname kopieren", command=lambda: _clipboard(self.tree, values[0] if values else ""))
                m.add_command(label="Ordner/Pfad kopieren", command=lambda: _clipboard(self.tree, values[1] if len(values) > 1 else ""))
                m.add_command(label="Komplette Zeile kopieren", command=lambda: _clipboard(self.tree, "\t".join(str(x) for x in values)))
                m.tk_popup(event.x_root, event.y_root); return "break"
            self.tree.bind("<Button-3>", menu, add="+")
        JobFilesWindow.__init__ = files_init
        JobFilesWindow._context_v1917 = True

    AppClass._context_progress_v1917 = True
