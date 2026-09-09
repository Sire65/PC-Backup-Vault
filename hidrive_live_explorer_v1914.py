from __future__ import annotations

import posixpath
import stat as statmod
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from cloud_targets_v191 import cloud_accounts
from hidrive_sftp_v192 import sftp_connection


PROTECTED_VAULT = ".pc-backup-vault"


def _norm_remote(path: str) -> str:
    value = posixpath.normpath("/" + str(path or "").replace("\\", "/").lstrip("/"))
    return value if value.startswith("/") else "/" + value


def _home(account: dict) -> str:
    user = str(account.get("username") or "").strip()
    return _norm_remote(f"/users/{user}") if user else "/"


def _within(path: str, root: str) -> bool:
    path = _norm_remote(path)
    root = _norm_remote(root)
    return path == root or path.startswith(root.rstrip("/") + "/")


def _is_protected(path: str, home: str) -> bool:
    path = _norm_remote(path)
    home = _norm_remote(home)
    vault = posixpath.join(home, PROTECTED_VAULT)
    return path == vault or path.startswith(vault.rstrip("/") + "/")


def _format_size(value: int) -> str:
    size = max(0, int(value or 0))
    units = ("B", "KB", "MB", "GB", "TB")
    n = float(size)
    for unit in units:
        if n < 1024.0 or unit == units[-1]:
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{size} B"


def _is_dir_attr(attr) -> bool:
    return statmod.S_ISDIR(int(getattr(attr, "st_mode", 0) or 0))


def _list_remote(sftp, path: str) -> list[dict]:
    rows = []
    for attr in sftp.listdir_attr(path):
        name = str(getattr(attr, "filename", "") or "")
        if not name:
            continue
        is_dir = _is_dir_attr(attr)
        rows.append({
            "name": name,
            "path": posixpath.join(path, name),
            "is_dir": is_dir,
            "size": 0 if is_dir else int(getattr(attr, "st_size", 0) or 0),
            "mtime": int(getattr(attr, "st_mtime", 0) or 0),
        })
    rows.sort(key=lambda x: (not x["is_dir"], x["name"].casefold()))
    return rows


def _remote_exists(sftp, path: str) -> bool:
    try:
        sftp.stat(path)
        return True
    except OSError:
        return False


def _delete_remote(sftp, path: str) -> None:
    info = sftp.stat(path)
    if statmod.S_ISDIR(int(getattr(info, "st_mode", 0) or 0)):
        for attr in sftp.listdir_attr(path):
            _delete_remote(sftp, posixpath.join(path, str(attr.filename)))
        sftp.rmdir(path)
    else:
        sftp.remove(path)


def _download_remote(sftp, remote: str, local: Path) -> None:
    info = sftp.stat(remote)
    if statmod.S_ISDIR(int(getattr(info, "st_mode", 0) or 0)):
        local.mkdir(parents=True, exist_ok=True)
        for attr in sftp.listdir_attr(remote):
            _download_remote(sftp, posixpath.join(remote, str(attr.filename)), local / str(attr.filename))
    else:
        local.parent.mkdir(parents=True, exist_ok=True)
        sftp.get(remote, str(local))


def _hidrive_accounts(store) -> list[dict]:
    out = []
    for account in cloud_accounts(store):
        provider = str(account.get("provider_code") or "").upper()
        methods = {str(x).upper() for x in (account.get("methods") or [])}
        preferred = str(account.get("preferred_method") or "").upper()
        if provider == "STRATO_HIDRIVE" and ("SFTP" in methods or preferred == "SFTP"):
            out.append(account)
    return out


class RemoteFolderPicker(tk.Toplevel):
    def __init__(self, parent, store, account: dict, start_path: str):
        super().__init__(parent)
        self.store = store
        self.account = account
        self.home = _home(account)
        self.current = _norm_remote(start_path)
        if not _within(self.current, self.home):
            self.current = self.home
        self.result = None
        self.title("HiDrive-Zielordner auswählen")
        self.geometry("720x540")
        self.minsize(620, 430)
        self.transient(parent)
        self.grab_set()

        top = ttk.Frame(self, padding=12); top.pack(fill="x")
        ttk.Label(top, text="Zielordner auf HiDrive", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.path_var = tk.StringVar(value=self.current)
        pathrow = ttk.Frame(top); pathrow.pack(fill="x", pady=(8, 0))
        ttk.Button(pathrow, text="⬆", width=4, command=self.up).pack(side="left")
        ttk.Entry(pathrow, textvariable=self.path_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(pathrow, text="Öffnen", command=self.open_typed).pack(side="left")

        box = ttk.Frame(self, padding=(12, 0, 12, 8)); box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(box, columns=("modified",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Ordner"); self.tree.column("#0", width=480)
        self.tree.heading("modified", text="Geändert"); self.tree.column("modified", width=160)
        sy = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sy.set)
        self.tree.pack(side="left", fill="both", expand=True); sy.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self.enter_selected())

        foot = ttk.Frame(self, padding=12); foot.pack(fill="x")
        ttk.Button(foot, text="Abbrechen", command=self.destroy).pack(side="right")
        ttk.Button(foot, text="Diesen Ordner verwenden", command=self.choose).pack(side="right", padx=(0, 8))
        self.load()

    def load(self):
        self.tree.delete(*self.tree.get_children())
        self.path_var.set(self.current)
        try:
            with sftp_connection(self.store, str(self.account.get("id"))) as (sftp, _):
                for row in _list_remote(sftp, self.current):
                    if not row["is_dir"]:
                        continue
                    modified = datetime.fromtimestamp(row["mtime"]).strftime("%d.%m.%Y %H:%M") if row["mtime"] else "–"
                    self.tree.insert("", "end", iid=row["path"], text="📁 " + row["name"], values=(modified,))
        except Exception as exc:
            messagebox.showerror("HiDrive", f"Ordner konnten nicht geladen werden.\n\n{exc}", parent=self)

    def enter_selected(self):
        sel = self.tree.selection()
        if sel:
            self.current = str(sel[0]); self.load()

    def up(self):
        if self.current == self.home:
            return
        parent = posixpath.dirname(self.current.rstrip("/")) or self.home
        self.current = parent if _within(parent, self.home) else self.home
        self.load()

    def open_typed(self):
        path = _norm_remote(self.path_var.get())
        if not _within(path, self.home):
            messagebox.showwarning("HiDrive", "Der Zielordner muss innerhalb des HiDrive-Benutzerbereichs liegen.", parent=self)
            return
        self.current = path; self.load()

    def choose(self):
        self.result = self.current
        self.destroy()


class HiDriveLiveExplorer(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.store = app.store
        self.accounts = _hidrive_accounts(self.store)
        self.current_rows: dict[str, dict] = {}
        self.current_path = "/"
        self.home = "/"
        self.busy = False

        self.title("PC Backup Vault – HiDrive Live-Explorer")
        self.geometry("1280x760")
        self.minsize(980, 600)
        self.transient(app)

        head = ttk.Frame(self, padding=(14, 12, 14, 6)); head.pack(fill="x")
        ttk.Label(head, text="☁ HiDrive Live-Explorer", font=("Segoe UI", 19, "bold")).pack(side="left")
        ttk.Label(head, text="Direkter SFTP-Dateimanager – kompletter HiDrive-Benutzerbereich", font=("Segoe UI", 10)).pack(side="left", padx=(16, 0))
        ttk.Button(head, text="Schließen", command=self.destroy).pack(side="right")

        accountrow = ttk.Frame(self, padding=(14, 0, 14, 6)); accountrow.pack(fill="x")
        ttk.Label(accountrow, text="HiDrive-Konto:").pack(side="left")
        self.account_var = tk.StringVar()
        names = [str(a.get("name") or a.get("username") or a.get("id")) for a in self.accounts]
        self.account_combo = ttk.Combobox(accountrow, textvariable=self.account_var, state="readonly", values=names, width=34)
        self.account_combo.pack(side="left", padx=(6, 12))
        self.account_combo.bind("<<ComboboxSelected>>", lambda _e: self.switch_account())
        self.status_var = tk.StringVar(value="")
        ttk.Label(accountrow, textvariable=self.status_var).pack(side="left", fill="x", expand=True)

        nav = ttk.Frame(self, padding=(14, 0, 14, 8)); nav.pack(fill="x")
        ttk.Button(nav, text="⬆ Hoch", command=self.up).pack(side="left")
        ttk.Button(nav, text="⌂ Start", command=self.go_home).pack(side="left", padx=(6, 0))
        ttk.Button(nav, text="↻ Aktualisieren", command=self.refresh).pack(side="left", padx=(6, 0))
        self.path_var = tk.StringVar()
        path_entry = ttk.Entry(nav, textvariable=self.path_var)
        path_entry.pack(side="left", fill="x", expand=True, padx=8)
        path_entry.bind("<Return>", lambda _e: self.open_typed_path())
        ttk.Button(nav, text="Öffnen", command=self.open_typed_path).pack(side="left")

        tools = ttk.Frame(self, padding=(14, 0, 14, 8)); tools.pack(fill="x")
        ttk.Button(tools, text="📁 Neuer Ordner", command=self.new_folder).pack(side="left")
        ttk.Button(tools, text="✏ Umbenennen", command=self.rename_selected).pack(side="left", padx=(6, 0))
        ttk.Button(tools, text="↪ Verschieben", command=self.move_selected).pack(side="left", padx=(6, 0))
        ttk.Button(tools, text="🗑 Löschen", command=self.delete_selected).pack(side="left", padx=(6, 0))
        ttk.Separator(tools, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(tools, text="⬇ Herunterladen", command=self.download_selected).pack(side="left")
        ttk.Button(tools, text="⬆ Dateien hochladen", command=self.upload_files).pack(side="left", padx=(6, 0))

        box = ttk.Frame(self, padding=(14, 0, 14, 8)); box.pack(fill="both", expand=True)
        box.rowconfigure(0, weight=1); box.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(box, columns=("type", "size", "modified", "path"), show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Name"); self.tree.column("#0", width=360, minwidth=220)
        for c, title, width in (("type", "Typ", 90), ("size", "Größe", 100), ("modified", "Geändert", 160), ("path", "Remote-Pfad", 470)):
            self.tree.heading(c, text=title); self.tree.column(c, width=width, anchor="w")
        sy = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(box, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); sy.grid(row=0, column=1, sticky="ns"); sx.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._selection_status())

        note = ttk.Frame(self, padding=(14, 0, 14, 12)); note.pack(fill="x")
        ttk.Label(note, text="Hinweis: .pc-backup-vault enthält verschlüsselte Sicherungsdaten. Änderungen dort benötigen eine zusätzliche Bestätigung.", wraplength=1180).pack(anchor="w")

        if not self.accounts:
            self.status_var.set("Kein STRATO-HiDrive-Konto mit SFTP eingerichtet.")
            self.account_combo.configure(state="disabled")
        else:
            self.account_combo.current(0)
            self.switch_account()

    def _account(self):
        idx = self.account_combo.current()
        return self.accounts[idx] if 0 <= idx < len(self.accounts) else None

    def switch_account(self):
        account = self._account()
        if not account:
            return
        self.home = _home(account)
        self.current_path = self.home
        self.refresh()

    def _set_busy(self, value: bool, text: str | None = None):
        self.busy = value
        if text is not None:
            self.status_var.set(text)

    def refresh(self):
        if self.busy:
            return
        account = self._account()
        if not account:
            return
        path = _norm_remote(self.current_path)
        if not _within(path, self.home):
            path = self.home
        self.current_path = path
        self.path_var.set(path)
        self._set_busy(True, f"Lade {path} …")

        def work():
            try:
                with sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                    rows = _list_remote(sftp, path)
                self.after(0, lambda: self._render(rows))
            except Exception as exc:
                self.after(0, lambda e=exc: self._load_failed(e))
        threading.Thread(target=work, name="pbv-hidrive-live-list", daemon=True).start()

    def _render(self, rows: list[dict]):
        if not self.winfo_exists():
            return
        self.tree.delete(*self.tree.get_children())
        self.current_rows = {}
        for i, row in enumerate(rows):
            iid = f"r{i}"
            self.current_rows[iid] = row
            modified = datetime.fromtimestamp(row["mtime"]).strftime("%d.%m.%Y %H:%M") if row["mtime"] else "–"
            icon = "📁" if row["is_dir"] else "📄"
            self.tree.insert("", "end", iid=iid, text=f"{icon} {row['name']}", values=("Ordner" if row["is_dir"] else "Datei", "–" if row["is_dir"] else _format_size(row["size"]), modified, row["path"]))
        self._set_busy(False, f"{len(rows)} Einträge · {self.current_path}")

    def _load_failed(self, exc):
        self._set_busy(False, "HiDrive konnte nicht gelesen werden.")
        messagebox.showerror("HiDrive Live-Explorer", str(exc), parent=self)

    def selected_rows(self) -> list[dict]:
        return [self.current_rows[x] for x in self.tree.selection() if x in self.current_rows]

    def _selection_status(self):
        rows = self.selected_rows()
        if rows:
            self.status_var.set(f"{len(rows)} ausgewählt · {self.current_path}")

    def open_selected(self):
        rows = self.selected_rows()
        if len(rows) == 1 and rows[0]["is_dir"]:
            self.current_path = rows[0]["path"]
            self.refresh()

    def up(self):
        if self.current_path == self.home:
            return
        parent = posixpath.dirname(self.current_path.rstrip("/")) or self.home
        self.current_path = parent if _within(parent, self.home) else self.home
        self.refresh()

    def go_home(self):
        self.current_path = self.home
        self.refresh()

    def open_typed_path(self):
        path = _norm_remote(self.path_var.get())
        if not _within(path, self.home):
            messagebox.showwarning("HiDrive Live-Explorer", "Der Pfad liegt außerhalb des HiDrive-Benutzerbereichs.", parent=self)
            return
        self.current_path = path
        self.refresh()

    def _confirm_protected(self, paths: list[str], action: str) -> bool:
        if not any(_is_protected(p, self.home) for p in paths):
            return True
        answer = simpledialog.askstring(
            "Sicherungsarchiv schützen",
            f"Die Aktion „{action}“ betrifft .pc-backup-vault.\n\n"
            "Dort liegen verschlüsselte Backup-Chunks und Manifeste. Eine Änderung kann Wiederherstellungen unbrauchbar machen.\n\n"
            "Zum Fortfahren bitte exakt BACKUP eingeben:",
            parent=self,
        )
        return str(answer or "").strip().upper() == "BACKUP"

    def _run_operation(self, title: str, worker, done_text: str):
        if self.busy:
            return
        self._set_busy(True, title + " …")
        def work():
            try:
                worker()
                self.after(0, lambda: self._operation_done(done_text))
            except Exception as exc:
                self.after(0, lambda e=exc: self._operation_failed(title, e))
        threading.Thread(target=work, name="pbv-hidrive-live-op", daemon=True).start()

    def _operation_done(self, text: str):
        self._set_busy(False, text)
        self.refresh()

    def _operation_failed(self, title: str, exc):
        self._set_busy(False, f"{title} fehlgeschlagen")
        messagebox.showerror("HiDrive Live-Explorer", f"{title} fehlgeschlagen.\n\n{exc}", parent=self)

    def new_folder(self):
        name = simpledialog.askstring("Neuer HiDrive-Ordner", "Name des neuen Ordners:", parent=self)
        name = str(name or "").strip()
        if not name:
            return
        if "/" in name or "\\" in name or name in (".", ".."):
            messagebox.showwarning("HiDrive", "Bitte nur einen Ordnernamen ohne Pfadtrenner eingeben.", parent=self); return
        remote = posixpath.join(self.current_path, name)
        account = self._account()
        self._run_operation("Ordner anlegen", lambda: self._mkdir(account, remote), f"Ordner {name} angelegt")

    def _mkdir(self, account, remote):
        with sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
            if _remote_exists(sftp, remote):
                raise FileExistsError(f"{remote} existiert bereits")
            sftp.mkdir(remote)

    def rename_selected(self):
        rows = self.selected_rows()
        if len(rows) != 1:
            messagebox.showinfo("Umbenennen", "Bitte genau eine Datei oder einen Ordner auswählen.", parent=self); return
        row = rows[0]
        if not self._confirm_protected([row["path"]], "Umbenennen"):
            return
        new_name = simpledialog.askstring("Umbenennen", "Neuer Name:", initialvalue=row["name"], parent=self)
        new_name = str(new_name or "").strip()
        if not new_name or new_name == row["name"]:
            return
        if "/" in new_name or "\\" in new_name or new_name in (".", ".."):
            messagebox.showwarning("HiDrive", "Bitte nur einen Namen ohne Pfadtrenner eingeben.", parent=self); return
        dest = posixpath.join(self.current_path, new_name)
        if not self._confirm_protected([dest], "Umbenennen"):
            return
        account = self._account()
        self._run_operation("Umbenennen", lambda: self._rename(account, row["path"], dest), f"{row['name']} wurde umbenannt")

    def _rename(self, account, src, dest):
        with sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
            if _remote_exists(sftp, dest):
                raise FileExistsError(f"Ziel existiert bereits: {dest}")
            sftp.rename(src, dest)

    def move_selected(self):
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("Verschieben", "Bitte Dateien oder Ordner auswählen.", parent=self); return
        paths = [x["path"] for x in rows]
        if not self._confirm_protected(paths, "Verschieben"):
            return
        picker = RemoteFolderPicker(self, self.store, self._account(), self.current_path)
        self.wait_window(picker)
        dest_dir = picker.result
        if not dest_dir:
            return
        dests = [posixpath.join(dest_dir, x["name"]) for x in rows]
        if not self._confirm_protected(dests, "Verschieben"):
            return
        account = self._account()
        def worker():
            with sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                for row, dest in zip(rows, dests):
                    if row["path"] == dest:
                        continue
                    if row["is_dir"] and _within(dest_dir, row["path"]):
                        raise ValueError(f"Ordner kann nicht in sich selbst verschoben werden: {row['name']}")
                    if _remote_exists(sftp, dest):
                        raise FileExistsError(f"Ziel existiert bereits: {dest}")
                    sftp.rename(row["path"], dest)
        self._run_operation("Verschieben", worker, f"{len(rows)} Eintrag/Einträge verschoben")

    def delete_selected(self):
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("Löschen", "Bitte Dateien oder Ordner auswählen.", parent=self); return
        paths = [x["path"] for x in rows]
        if not self._confirm_protected(paths, "Löschen"):
            return
        names = "\n".join("• " + x["name"] for x in rows[:12])
        if len(rows) > 12:
            names += f"\n… und {len(rows)-12} weitere"
        if not messagebox.askyesno("HiDrive löschen", f"Diese {len(rows)} Auswahl(en) wirklich dauerhaft auf HiDrive löschen?\n\n{names}\n\nOrdner werden einschließlich ihres Inhalts gelöscht.", parent=self):
            return
        account = self._account()
        def worker():
            with sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                for row in rows:
                    if row["path"] == self.home:
                        raise RuntimeError("Der HiDrive-Benutzerordner selbst darf nicht gelöscht werden.")
                    _delete_remote(sftp, row["path"])
        self._run_operation("Löschen", worker, f"{len(rows)} Eintrag/Einträge gelöscht")

    def download_selected(self):
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("Herunterladen", "Bitte Dateien oder Ordner auswählen.", parent=self); return
        dest = filedialog.askdirectory(parent=self, title="Lokalen Zielordner auswählen")
        if not dest:
            return
        account = self._account(); base = Path(dest)
        def worker():
            with sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                for row in rows:
                    _download_remote(sftp, row["path"], base / row["name"])
        self._run_operation("Herunterladen", worker, f"{len(rows)} Eintrag/Einträge heruntergeladen")

    def upload_files(self):
        files = filedialog.askopenfilenames(parent=self, title="Dateien für HiDrive auswählen")
        if not files:
            return
        account = self._account(); remotes = [posixpath.join(self.current_path, Path(x).name) for x in files]
        if not self._confirm_protected(remotes, "Hochladen"):
            return
        if not messagebox.askyesno("HiDrive hochladen", "Ausgewählte Dateien in den aktuellen HiDrive-Ordner hochladen?\n\nExistierende Dateien mit gleichem Namen werden überschrieben.", parent=self):
            return
        def worker():
            with sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                for local, remote in zip(files, remotes):
                    sftp.put(str(local), remote)
        self._run_operation("Hochladen", worker, f"{len(files)} Datei(en) hochgeladen")


def apply_hidrive_live_explorer_v1914(AppClass):
    if getattr(AppClass, "_hidrive_live_explorer_v1914", False):
        return
    original_build = AppClass._build

    def _build(self):
        original_build(self)
        self.open_hidrive_live_explorer = lambda: HiDriveLiveExplorer(self)
        try:
            parent = self.btn_backup.master
            ttk.Button(parent, text="☁ HiDrive Live", command=self.open_hidrive_live_explorer).pack(
                side="left", padx=(0, 8), before=self.btn_backup
            )
        except Exception:
            pass

    AppClass._build = _build
    AppClass._hidrive_live_explorer_v1914 = True
