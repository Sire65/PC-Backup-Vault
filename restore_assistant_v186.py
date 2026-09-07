from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path, PureWindowsPath
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from vault_db import all_files
from backup_engine import restore_file
from crypto_box import decrypt_text


def _safe_rel(original_path: str, file_name: str) -> Path:
    p = PureWindowsPath(original_path or "")
    parts = []
    if p.drive:
        parts.append(p.drive.replace(":", ""))
    for x in p.parts:
        if x not in (p.drive, "\\", "/"):
            parts.append(x)
    return Path(*parts) / file_name


def _keep_both(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        candidate = path.with_name(f"{stem} (wiederhergestellt {i}){suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def _fmt_size(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024


def _file_group(ext: str) -> str:
    ext = (ext or "").lower()
    if ext in {".doc", ".docx", ".pdf", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp", ".csv"}:
        return "Dokumente"
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic"}:
        return "Bilder"
    if ext in {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".mp3", ".wav", ".flac", ".m4a", ".aac"}:
        return "Medien"
    return "Andere"


class RestoreAssistant(tk.Toplevel):
    """Four-step restore workflow with locally decrypted, human-readable metadata."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.store = app.store
        self.dsn = app.active_dsn()
        self.key = app.master_key()
        self.title("PC Backup Vault – Wiederherstellen")
        self.geometry("1060x760")
        self.minsize(900, 650)
        self.transient(app)
        self.grab_set()

        self.step = 0
        self.records = []
        self.decoded = {}
        self.selected_ids = set()
        self.destination_mode = "OTHER"
        self.destination = str(Path.home() / "Desktop" / "PC Backup Vault Wiederherstellung")
        self.conflict = "KEEP_BOTH"

        if not self.dsn:
            messagebox.showwarning("Wiederherstellung", "Keine Neon-Datenbankverbindung eingerichtet.", parent=self)
            self.destroy(); return
        if not self.key:
            messagebox.showwarning("Wiederherstellung", "Der lokale Wiederherstellungsschlüssel ist nicht verfügbar.", parent=self)
            self.destroy(); return

        head = ttk.Frame(self, padding=(18, 16, 18, 8)); head.pack(fill="x")
        ttk.Label(head, text="♻ Wiederherstellen", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        self.subtitle = ttk.Label(head, text="Einfach und sicher in vier Schritten.")
        self.subtitle.pack(anchor="w", pady=(3, 0))
        self.body = ttk.Frame(self, padding=(18, 8)); self.body.pack(fill="both", expand=True)
        foot = ttk.Frame(self, padding=(18, 8, 18, 16)); foot.pack(fill="x")
        ttk.Button(foot, text="Abbrechen", command=self.destroy).pack(side="left")
        self.btn_back = ttk.Button(foot, text="← Zurück", command=self.back); self.btn_back.pack(side="right", padx=(6, 0))
        self.btn_next = ttk.Button(foot, text="Weiter →", command=self.next); self.btn_next.pack(side="right")

        self._load_records()
        self.render()

    def _decode(self, value):
        try:
            return decrypt_text(self.key, str(value or ""))
        except Exception:
            return "[Metadaten nicht lesbar]"

    def _load_records(self):
        try:
            self.records = list(all_files(self.dsn, 5000))
            for r in self.records:
                fid = str(r[0])
                self.decoded[fid] = {
                    "name": self._decode(r[2]),
                    "path": self._decode(r[3]),
                    "ext": str(r[4] or "").lower(),
                }
        except Exception as e:
            messagebox.showerror("Wiederherstellung", f"Sicherungen konnten nicht geladen werden:\n\n{e}", parent=self)
            self.records = []

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def render(self):
        self._clear()
        self.btn_back.configure(state="disabled" if self.step == 0 else "normal")
        self.btn_next.configure(text="Weiter →", state="normal")
        [self.step_what, self.step_when, self.step_where, self.step_summary][self.step]()

    def step_what(self):
        self.subtitle.configure(text="Schritt 1 von 4 – Welche Datei möchten Sie zurückholen?")
        ttk.Label(self.body, text="Dateien auswählen", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(
            self.body,
            text="Hier sehen Sie jede gesicherte Datei nur einmal. Es wird zunächst die neueste Version angezeigt. Ältere Versionen wählen Sie im nächsten Schritt.",
            wraplength=980,
        ).pack(anchor="w", pady=(4, 10))

        controls = ttk.Frame(self.body); controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="Suche:").pack(side="left")
        self.search = tk.StringVar()
        ent = ttk.Entry(controls, textvariable=self.search, width=42)
        ent.pack(side="left", fill="x", expand=True, padx=(6, 14))
        ttk.Label(controls, text="Anzeigen:").pack(side="left")
        self.filter_var = tk.StringVar(value="Alle Dateien")
        filt = ttk.Combobox(
            controls, textvariable=self.filter_var, state="readonly", width=18,
            values=("Alle Dateien", "Dokumente", "Bilder", "Medien", "Andere"),
        )
        filt.pack(side="left")

        table = ttk.Frame(self.body); table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            table, columns=("file", "folder", "date", "size"), show="headings", selectmode="extended"
        )
        for c, t, w in [
            ("file", "Dateiname", 300),
            ("folder", "Ordner", 430),
            ("date", "Letzte Sicherung", 160),
            ("size", "Größe", 100),
        ]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="e" if c == "size" else "w")
        y = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        x = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1); table.columnconfigure(0, weight=1)

        self.info_lbl = ttk.Label(self.body, text="", padding=(0, 7, 0, 0))
        self.info_lbl.pack(anchor="w")
        self.search.trace_add("write", lambda *_: self._refresh_files())
        self.filter_var.trace_add("write", lambda *_: self._refresh_files())
        self.tree.bind("<Double-1>", lambda _e: self.next())
        self._refresh_files()
        ent.focus_set()

    def _refresh_files(self):
        if not hasattr(self, "tree"):
            return
        q = self.search.get().strip().casefold() if hasattr(self, "search") else ""
        group = self.filter_var.get() if hasattr(self, "filter_var") else "Alle Dateien"
        previous_selection = set(self.tree.selection())
        for item in self.tree.get_children():
            self.tree.delete(item)

        # all_files() is newest first. Decrypted path+name identifies one logical file for the user.
        shown = 0
        seen = set()
        for r in self.records:
            fid = str(r[0])
            meta = self.decoded.get(fid, {})
            name = meta.get("name", "")
            folder = meta.get("path", "")
            ext = meta.get("ext", "")
            key = (folder.casefold(), name.casefold())
            if key in seen:
                continue
            seen.add(key)
            if group != "Alle Dateien" and _file_group(ext) != group:
                continue
            if q and q not in f"{name} {folder} {r[13] or ''}".casefold():
                continue
            stamp = r[10].strftime("%d.%m.%Y %H:%M") if hasattr(r[10], "strftime") else str(r[10])
            self.tree.insert("", "end", iid=fid, values=(name, folder, stamp, _fmt_size(r[5])))
            if fid in previous_selection or fid in self.selected_ids:
                self.tree.selection_add(fid)
            shown += 1
        self.info_lbl.configure(text=f"{shown} Dateien angezeigt · Mehrfach gesicherte Versionen sind hier zusammengefasst.")

    def step_when(self):
        self.subtitle.configure(text="Schritt 2 von 4 – Welche Version möchten Sie?")
        ttk.Label(self.body, text="Sicherungsstand auswählen", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(
            self.body,
            text="Die neueste Version ist vorausgewählt. Nur wenn Sie einen älteren Stand benötigen, ändern Sie die Auswahl.",
            wraplength=980,
        ).pack(anchor="w", pady=(4, 12))

        canvas = tk.Canvas(self.body, highlightthickness=0)
        scroll = ttk.Scrollbar(self.body, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        chosen = [r for r in self.records if str(r[0]) in self.selected_ids]
        for r in chosen:
            current_id = str(r[0])
            meta = self.decoded[current_id]
            name, folder = meta["name"], meta["path"]
            box = ttk.LabelFrame(inner, text=name, padding=10); box.pack(fill="x", pady=5, padx=(0, 8))
            ttk.Label(box, text=folder, wraplength=850).pack(anchor="w", pady=(0, 5))
            versions = []
            for x in self.records:
                xm = self.decoded.get(str(x[0]), {})
                if xm.get("name") == name and xm.get("path") == folder:
                    versions.append(x)
            labels, mapping = [], {}
            for x in versions:
                stamp = x[10].strftime("%d.%m.%Y %H:%M") if hasattr(x[10], "strftime") else str(x[10])
                backend = {"B2": "Backblaze B2", "NEON": "Neon"}.get(str(x[14] or ""), str(x[14] or ""))
                label = f"{stamp}   ·   {backend}   ·   {_fmt_size(x[5])}"
                labels.append(label); mapping[label] = x
            current_label = next((lab for lab, x in mapping.items() if str(x[0]) == current_id), labels[0] if labels else "")
            var = tk.StringVar(value=current_label)
            cb = ttk.Combobox(box, textvariable=var, state="readonly", values=labels, width=78)
            cb.pack(anchor="w")
            def setver(*_, v=var, m=mapping, old=current_id):
                x = m.get(v.get())
                if x:
                    self.selected_ids.discard(old)
                    self.selected_ids.add(str(x[0]))
            var.trace_add("write", setver)

    def step_where(self):
        self.subtitle.configure(text="Schritt 3 von 4 – Wohin soll wiederhergestellt werden?")
        ttk.Label(self.body, text="Ziel auswählen", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(self.body, text="Der sichere Wiederherstellungsordner ist die empfohlene Einstellung.", wraplength=940).pack(anchor="w", pady=(4, 10))

        mode = tk.StringVar(value=self.destination_mode)
        ttk.Radiobutton(
            self.body, text="In einen separaten Wiederherstellungsordner (empfohlen)",
            variable=mode, value="OTHER", command=lambda: self._set_mode(mode.get())
        ).pack(anchor="w", pady=(8, 4))
        ttk.Radiobutton(
            self.body, text="An den ursprünglichen Speicherort zurückschreiben",
            variable=mode, value="ORIGINAL", command=lambda: self._set_mode(mode.get())
        ).pack(anchor="w", pady=4)

        row = ttk.Frame(self.body); row.pack(fill="x", pady=(14, 4))
        self.dest_var = tk.StringVar(value=self.destination)
        ttk.Entry(row, textvariable=self.dest_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Ordner wählen …", command=self._choose_dest).pack(side="left", padx=(6, 0))

        sep = ttk.Separator(self.body); sep.pack(fill="x", pady=18)
        ttk.Label(self.body, text="Falls am Ziel bereits eine Datei mit gleichem Namen vorhanden ist:", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        cv = tk.StringVar(value=self.conflict)
        choices = [
            ("KEEP_BOTH", "Beide behalten (empfohlen)", "Die vorhandene Datei bleibt unverändert; die zurückgeholte Datei erhält einen Zusatz im Namen."),
            ("REPLACE", "Vorhandene Datei ersetzen", "Erst nach erfolgreicher Entschlüsselung und Hashprüfung wird die vorhandene Datei ersetzt."),
            ("SKIP", "Vorhandene Datei überspringen", "Bereits vorhandene Dateien werden nicht verändert."),
        ]
        for code, label, desc in choices:
            line = ttk.Frame(self.body); line.pack(fill="x", pady=5)
            ttk.Radiobutton(line, text=label, variable=cv, value=code, command=lambda: self._set_conflict(cv.get())).pack(anchor="w")
            ttk.Label(line, text=desc, wraplength=900).pack(anchor="w", padx=(22, 0))

    def _set_mode(self, value):
        self.destination_mode = value

    def _set_conflict(self, value):
        self.conflict = value

    def _choose_dest(self):
        p = filedialog.askdirectory(parent=self, title="Zielordner für Wiederherstellung")
        if p:
            self.destination = p
            self.dest_var.set(p)

    def step_summary(self):
        self.subtitle.configure(text="Schritt 4 von 4 – Prüfen und wiederherstellen")
        ttk.Label(self.body, text="Bereit zur Wiederherstellung", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        rows = [r for r in self.records if str(r[0]) in self.selected_ids]
        total = sum(int(r[5] or 0) for r in rows)
        target = "Ursprünglicher Speicherort" if self.destination_mode == "ORIGINAL" else self.destination
        conflict = {"KEEP_BOTH": "Beide behalten", "REPLACE": "Ersetzen nach erfolgreicher Prüfung", "SKIP": "Überspringen"}[self.conflict]

        card = ttk.LabelFrame(self.body, text="Zusammenfassung", padding=14); card.pack(fill="x", pady=(14, 10))
        ttk.Label(card, text=f"Dateien: {len(rows)}").pack(anchor="w", pady=2)
        ttk.Label(card, text=f"Datenmenge: {_fmt_size(total)}").pack(anchor="w", pady=2)
        ttk.Label(card, text=f"Ziel: {target}", wraplength=900).pack(anchor="w", pady=2)
        ttk.Label(card, text=f"Bei Namenskonflikten: {conflict}").pack(anchor="w", pady=2)
        ttk.Label(
            self.body,
            text="Die Datei wird entschlüsselt und per SHA-256 geprüft. Erst ein erfolgreich geprüfter Stand gilt als wiederhergestellt.",
            wraplength=940,
        ).pack(anchor="w", pady=(4, 0))
        self.btn_next.configure(text="♻ Jetzt wiederherstellen")

    def next(self):
        if self.step == 0:
            sel = self.tree.selection()
            if not sel:
                messagebox.showwarning("Wiederherstellung", "Bitte mindestens eine Datei auswählen.", parent=self)
                return
            self.selected_ids = set(sel)
        if self.step == 2 and self.destination_mode == "OTHER":
            self.destination = self.dest_var.get().strip()
            if not self.destination:
                messagebox.showwarning("Wiederherstellung", "Bitte einen Zielordner auswählen.", parent=self)
                return
        if self.step < 3:
            self.step += 1
            self.render()
            return
        self._restore_now()

    def back(self):
        if self.step > 0:
            self.step -= 1
            self.render()

    def _target_for(self, row):
        fid = str(row[0])
        meta = self.decoded[fid]
        name, folder = meta["name"], meta["path"]
        if self.destination_mode == "ORIGINAL":
            root = Path(folder)
            rel = Path(name)
        else:
            root = Path(self.destination)
            rel = _safe_rel(folder, name)
        return root, rel, root / rel

    def _restore_replace_safely(self, fid: str, final: Path) -> Path:
        """Restore to a verified same-volume temp file, then atomically replace destination."""
        final.parent.mkdir(parents=True, exist_ok=True)
        temp_root = Path(tempfile.mkdtemp(prefix=".pbv_restore_", dir=str(final.parent)))
        try:
            restored = restore_file(
                self.dsn, self.key, fid, temp_root, relative_path=Path(final.name),
                object_store_config=self.store.get_b2_runtime_config(),
            )
            os.replace(restored, final)
            return final
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def _restore_now(self):
        rows = [r for r in self.records if str(r[0]) in self.selected_ids]
        if not rows:
            return
        self.btn_next.configure(state="disabled", text="Wiederherstellung läuft …")

        def worker():
            ok, skipped, errors = [], [], []
            for r in rows:
                fid = str(r[0])
                name = self.decoded.get(fid, {}).get("name", "Datei")
                try:
                    root, rel, final = self._target_for(r)
                    if final.exists():
                        if self.conflict == "SKIP":
                            skipped.append(str(final)); continue
                        if self.conflict == "KEEP_BOTH":
                            final = _keep_both(final)
                            rel = final.relative_to(root)
                    if self.conflict == "REPLACE" and final.exists():
                        restored = self._restore_replace_safely(fid, final)
                    else:
                        restored = restore_file(
                            self.dsn, self.key, fid, root, relative_path=rel,
                            object_store_config=self.store.get_b2_runtime_config(),
                        )
                    ok.append(str(restored))
                except Exception as e:
                    errors.append(f"{name}: {e}")

            def done():
                self.btn_next.configure(state="normal", text="♻ Jetzt wiederherstellen")
                if errors:
                    messagebox.showwarning(
                        "Wiederherstellung",
                        f"Wiederhergestellt: {len(ok)}\nÜbersprungen: {len(skipped)}\nFehler: {len(errors)}\n\n" + "\n".join(errors[:8]),
                        parent=self,
                    )
                else:
                    messagebox.showinfo(
                        "Wiederherstellung",
                        f"Wiederherstellung erfolgreich ✓\n\nWiederhergestellt: {len(ok)}\nÜbersprungen: {len(skipped)}",
                        parent=self,
                    )
                    self.destroy()
            self.after(0, done)
        threading.Thread(target=worker, daemon=True).start()


def apply_restore_assistant_v186(AppClass, BackupAssistantClass):
    original_build = AppClass._build
    def _build(self):
        original_build(self)
        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, ttk.LabelFrame) and str(c.cget("text")) == "Übersicht / Wiederherstellung":
                    before = c.winfo_children()[1] if len(c.winfo_children()) > 1 else None
                    ttk.Button(c, text="♻ Wiederherstellen", command=lambda: RestoreAssistant(self)).pack(side="left", padx=(0, 6), before=before)
                    return True
                if walk(c):
                    return True
            return False
        try:
            walk(self)
        except Exception:
            pass
        self.open_restore_assistant = lambda: RestoreAssistant(self)
    AppClass._build = _build

    def finish_restore(self):
        self.destroy()
        try:
            RestoreAssistant(self.app)
        except Exception as e:
            messagebox.showerror("Wiederherstellung", str(e), parent=self.app)
    BackupAssistantClass.finish_restore = finish_restore
