from __future__ import annotations

import csv
import io
import json
import posixpath
import stat as statmod
import threading
from datetime import datetime
from pathlib import Path, PurePosixPath
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import psycopg
from psycopg import sql

from context_progress_v1917 import OperationProgressDialog, _copy_stream, _ensure_remote_dir, format_bytes
from hidrive_account_list_fix_v1918 import eligible_hidrive_accounts
from hidrive_hidden_items_v1916 import list_remote_all
from hidrive_live_explorer_v1914 import RemoteFolderPicker
from hidrive_sftp_v192 import sftp_connection
from object_store import make_b2_store


DB_PROVIDERS = {"neon": "Neon", "supabase": "Supabase", "postgresql": "PostgreSQL"}
PROTECTED_HIDRIVE = ".pc-backup-vault"


def _label_target(kind: str, name: str, detail: str = "") -> str:
    head = {"HIDRIVE": "HiDrive", "B2": "Backblaze B2", "POSTGRES": "Datenbank"}.get(kind, kind)
    return f"{head} · {name}" + (f" · {detail}" if detail else "")


def collect_storage_targets(store) -> list[dict]:
    """Collect configured storage/database targets without copying any secrets."""
    out: list[dict] = []
    for account in eligible_hidrive_accounts(store, __import__("cloud_targets_v191").cloud_accounts):
        name = str(account.get("name") or account.get("username") or "STRATO HiDrive")
        out.append({
            "id": f"hidrive:{account.get('id')}", "kind": "HIDRIVE", "name": name,
            "label": _label_target("HIDRIVE", name), "account_id": str(account.get("id") or ""),
            "username": str(account.get("username") or ""),
        })

    b2 = store.get_b2_runtime_config()
    if b2.get("configured"):
        bucket = str(b2.get("bucket") or "B2")
        out.append({
            "id": "b2:default", "kind": "B2", "name": bucket,
            "label": _label_target("B2", bucket), "prefix": str(b2.get("prefix") or "pc-backup-vault").strip("/"),
        })

    for profile in list(store.data.get("profiles") or []):
        if profile.get("enabled", True) is False:
            continue
        provider = str(profile.get("provider") or "").lower()
        if provider not in DB_PROVIDERS:
            continue
        pid = str(profile.get("id") or "")
        if not pid or not store.get_dsn(pid):
            continue
        name = str(profile.get("name") or profile.get("database") or pid)
        provider_name = DB_PROVIDERS[provider]
        out.append({
            "id": f"db:{pid}", "kind": "POSTGRES", "name": name,
            "label": f"{provider_name} · {name}", "profile_id": pid, "provider": provider,
            "database": str(profile.get("database") or ""), "project_ref": str(profile.get("project_ref") or ""),
        })
    return out


def _hidrive_home(target: dict) -> str:
    user = str(target.get("username") or "").strip()
    return f"/users/{user}" if user else "/"


def _hidrive_protected(path: str) -> bool:
    try:
        return PROTECTED_HIDRIVE in PurePosixPath(str(path or "")).parts
    except Exception:
        return PROTECTED_HIDRIVE in str(path or "")


def _b2_prefix(value: str) -> str:
    clean = str(value or "").strip("/")
    return clean + "/" if clean else ""


def _collapse_nested(rows: list[dict], key_field: str = "path") -> list[dict]:
    """If a selected folder contains another selected item, keep only the folder."""
    ordered = sorted(rows, key=lambda r: len(str(r.get(key_field) or "")))
    kept: list[dict] = []
    for row in ordered:
        key = str(row.get(key_field) or "")
        nested = False
        for parent in kept:
            if not parent.get("is_dir"):
                continue
            p = str(parent.get(key_field) or "")
            if key != p and key.startswith(p.rstrip("/") + "/"):
                nested = True; break
        if not nested:
            kept.append(row)
    return kept


def _safe_name(name: str) -> str:
    name = str(name or "").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Bitte nur einen Namen ohne Pfadtrenner eingeben.")
    return name


def _b2_list(client, bucket: str, prefix: str) -> list[dict]:
    prefix = _b2_prefix(prefix)
    response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter="/", MaxKeys=1000)
    rows: list[dict] = []
    for p in response.get("CommonPrefixes", []) or []:
        key = str(p.get("Prefix") or "")
        if key:
            rows.append({"name": key.rstrip("/").rsplit("/", 1)[-1], "key": key, "is_dir": True, "size": 0, "modified": None})
    for item in response.get("Contents", []) or []:
        key = str(item.get("Key") or "")
        if not key or key == prefix or key.endswith("/"):
            continue
        # Delimiter guarantees only direct children in Contents.
        rows.append({
            "name": key.rsplit("/", 1)[-1], "key": key, "is_dir": False,
            "size": int(item.get("Size") or 0), "modified": item.get("LastModified"),
        })
    rows.sort(key=lambda r: (not r["is_dir"], r["name"].casefold()))
    return rows


def _b2_recursive(client, bucket: str, rows: list[dict]) -> list[dict]:
    out: dict[str, dict] = {}
    for row in _collapse_nested(rows, "key"):
        key = str(row.get("key") or "")
        if row.get("is_dir"):
            token = None
            while True:
                kw = {"Bucket": bucket, "Prefix": _b2_prefix(key), "MaxKeys": 1000}
                if token: kw["ContinuationToken"] = token
                response = client.list_objects_v2(**kw)
                for item in response.get("Contents", []) or []:
                    k = str(item.get("Key") or "")
                    if k and not k.endswith("/"):
                        out[k] = {"key": k, "size": int(item.get("Size") or 0), "modified": item.get("LastModified")}
                if not response.get("IsTruncated"): break
                token = response.get("NextContinuationToken")
                if not token: break
        elif key:
            out[key] = {"key": key, "size": int(row.get("size") or 0), "modified": row.get("modified")}
    return list(out.values())


def _sql_user_schemas(conn) -> list[str]:
    rows = conn.execute(
        """SELECT schema_name FROM information_schema.schemata
           WHERE schema_name NOT IN ('pg_catalog','information_schema')
             AND schema_name NOT LIKE 'pg_toast%'
             AND schema_name NOT LIKE 'pg_temp_%'
           ORDER BY schema_name"""
    ).fetchall()
    return [str(r[0]) for r in rows]


def _sql_relations(conn, schema: str) -> list[tuple[str, str]]:
    rows = conn.execute(
        """SELECT table_name, table_type FROM information_schema.tables
           WHERE table_schema=%s ORDER BY table_name""", (schema,)
    ).fetchall()
    return [(str(r[0]), str(r[1])) for r in rows]


def _sql_columns(conn, schema: str, table: str) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        """SELECT column_name, data_type, is_nullable FROM information_schema.columns
           WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position""", (schema, table)
    ).fetchall()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


class StorageCenterWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app; self.store = app.store
        self.targets = collect_storage_targets(self.store)
        self.items: dict[str, dict] = {}
        self.loaded_nodes: set[str] = set()
        self.busy = False
        self.current_target: dict | None = None

        self.title("PC Backup Vault – Speicher-Explorer")
        self.geometry("1380x840"); self.minsize(1040, 650); self.transient(app)

        head = ttk.Frame(self, padding=(14, 12, 14, 6)); head.pack(fill="x")
        ttk.Label(head, text="🗂 Speicher-Explorer", font=("Segoe UI", 19, "bold")).pack(side="left")
        ttk.Label(head, text="HiDrive · Backblaze B2 · Neon · Supabase · PostgreSQL", font=("Segoe UI", 10)).pack(side="left", padx=(16, 0))
        ttk.Button(head, text="Schließen", command=self.destroy).pack(side="right")

        choose = ttk.Frame(self, padding=(14, 0, 14, 8)); choose.pack(fill="x")
        ttk.Label(choose, text="Anbieter / Konto / Projekt:").pack(side="left")
        self.target_var = tk.StringVar()
        self.target_combo = ttk.Combobox(choose, textvariable=self.target_var, state="readonly", width=55,
                                         values=[t["label"] for t in self.targets])
        self.target_combo.pack(side="left", padx=(8, 10))
        self.target_combo.bind("<<ComboboxSelected>>", lambda _e: self.switch_target())
        self.status_var = tk.StringVar(value="Bereit.")
        ttk.Label(choose, textvariable=self.status_var).pack(side="left", fill="x", expand=True)

        tools = ttk.Frame(self, padding=(14, 0, 14, 8)); tools.pack(fill="x")
        self.btn_refresh = ttk.Button(tools, text="↻ Aktualisieren", command=self.refresh); self.btn_refresh.pack(side="left")
        self.btn_new = ttk.Button(tools, text="📁 Neuer Ordner", command=self.new_folder); self.btn_new.pack(side="left", padx=(6, 0))
        self.btn_out = ttk.Button(tools, text="⬇ Herunterladen / Export", command=self.download_export); self.btn_out.pack(side="left", padx=(6, 0))
        self.btn_in = ttk.Button(tools, text="⬆ Hochladen / Import", command=self.upload_import); self.btn_in.pack(side="left", padx=(6, 0))
        self.btn_copy = ttk.Button(tools, text="⧉ Kopieren", command=self.copy_selected); self.btn_copy.pack(side="left", padx=(6, 0))
        self.btn_move = ttk.Button(tools, text="↪ Verschieben", command=self.move_selected); self.btn_move.pack(side="left", padx=(6, 0))
        self.btn_rename = ttk.Button(tools, text="✏ Umbenennen", command=self.rename_selected); self.btn_rename.pack(side="left", padx=(6, 0))
        self.btn_delete = ttk.Button(tools, text="🗑 Löschen", command=self.delete_selected); self.btn_delete.pack(side="left", padx=(6, 0))
        self.btn_properties = ttk.Button(tools, text="ℹ Eigenschaften", command=self.properties); self.btn_properties.pack(side="left", padx=(6, 0))

        panes = ttk.Panedwindow(self, orient="vertical"); panes.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        treebox = ttk.Frame(panes); panes.add(treebox, weight=3)
        treebox.rowconfigure(0, weight=1); treebox.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(treebox, columns=("type", "size", "modified", "detail"), show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Name / Struktur"); self.tree.column("#0", width=430, minwidth=250)
        for c, title, width in (("type", "Typ", 170), ("size", "Größe", 110), ("modified", "Geändert", 170), ("detail", "Pfad / Details", 500)):
            self.tree.heading(c, text=title); self.tree.column(c, width=width, anchor="w")
        sy = ttk.Scrollbar(treebox, orient="vertical", command=self.tree.yview); sx = ttk.Scrollbar(treebox, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); sy.grid(row=0, column=1, sticky="ns"); sx.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewOpen>>", self._tree_open)
        self.tree.bind("<Double-1>", self._double_click)
        self.tree.bind("<Button-3>", self._context_menu)

        preview = ttk.LabelFrame(panes, text="Datenvorschau / Details", padding=8); panes.add(preview, weight=2)
        preview.rowconfigure(1, weight=1); preview.columnconfigure(0, weight=1)
        self.preview_info = tk.StringVar(value="Bei Datenbanktabellen erscheinen hier die ersten 200 Datensätze.")
        ttk.Label(preview, textvariable=self.preview_info).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        pbox = ttk.Frame(preview); pbox.grid(row=1, column=0, sticky="nsew"); pbox.rowconfigure(0, weight=1); pbox.columnconfigure(0, weight=1)
        self.preview = ttk.Treeview(pbox, show="headings", selectmode="extended")
        py = ttk.Scrollbar(pbox, orient="vertical", command=self.preview.yview); px = ttk.Scrollbar(pbox, orient="horizontal", command=self.preview.xview)
        self.preview.configure(yscrollcommand=py.set, xscrollcommand=px.set)
        self.preview.grid(row=0, column=0, sticky="nsew"); py.grid(row=0, column=1, sticky="ns"); px.grid(row=1, column=0, sticky="ew")
        self.preview.bind("<Button-3>", self._preview_context)

        note = ttk.Frame(self, padding=(14, 0, 14, 12)); note.pack(fill="x")
        self.note_var = tk.StringVar(value="Datenbanken werden standardmäßig sicher gelesen. Import ist möglich, destruktive Datenbankaktionen sind gesperrt.")
        ttk.Label(note, textvariable=self.note_var, wraplength=1320).pack(anchor="w")

        if self.targets:
            self.target_combo.current(0); self.switch_target()
        else:
            self.target_combo.configure(state="disabled")
            self.status_var.set("Noch kein unterstütztes Speicher-/Datenbankziel vollständig eingerichtet.")
            self._update_actions()

    def _target(self) -> dict | None:
        idx = self.target_combo.current()
        return self.targets[idx] if 0 <= idx < len(self.targets) else None

    def _set_busy(self, value: bool, text: str = ""):
        self.busy = bool(value)
        if text: self.status_var.set(text)
        try: self.btn_refresh.configure(state="disabled" if value else "normal")
        except Exception: pass

    def _run(self, title: str, worker, done_text: str, refresh=True):
        if self.busy: return
        self._set_busy(True, title + " …")
        progress = OperationProgressDialog(self, title, title + " …")
        try: progress.grab_set()
        except Exception: pass
        def report(**kw):
            try: self.after(0, lambda d=dict(kw): progress.update_progress(**d))
            except Exception: pass
        def work():
            try:
                worker(report)
                def done():
                    try: progress.finish(True, done_text); progress.grab_release(); progress.after(700, progress.destroy)
                    except Exception: pass
                    self._set_busy(False, done_text)
                    if refresh: self.refresh()
                self.after(0, done)
            except Exception as exc:
                def failed(e=exc):
                    try: progress.finish(False, str(e)); progress.grab_release()
                    except Exception: pass
                    self._set_busy(False, title + " fehlgeschlagen")
                    messagebox.showerror("Speicher-Explorer", f"{title} fehlgeschlagen.\n\n{e}", parent=self)
                    try: progress.destroy()
                    except Exception: pass
                self.after(0, failed)
        threading.Thread(target=work, daemon=True, name="pbv-storage-center-op").start()

    def switch_target(self):
        self.current_target = self._target(); self.refresh()

    def refresh(self):
        if self.busy: return
        self.items.clear(); self.loaded_nodes.clear(); self.tree.delete(*self.tree.get_children())
        self._clear_preview(); target = self.current_target or self._target()
        if not target: self._update_actions(); return
        self.current_target = target; self._update_actions()
        kind = target["kind"]
        if kind == "HIDRIVE": self._load_hidrive_root(target)
        elif kind == "B2": self._load_b2_root(target)
        elif kind == "POSTGRES": self._load_db_root(target)

    def _update_actions(self):
        kind = (self.current_target or {}).get("kind")
        states = {
            "HIDRIVE": ("normal", "normal", "normal", "normal", "normal", "normal", "normal"),
            "B2": ("normal", "normal", "normal", "normal", "normal", "normal", "normal"),
            "POSTGRES": ("disabled", "normal", "normal", "normal", "disabled", "disabled", "disabled"),
        }.get(kind, ("disabled",)*7)
        for btn, state in zip((self.btn_new, self.btn_out, self.btn_in, self.btn_copy, self.btn_move, self.btn_rename, self.btn_delete), states):
            btn.configure(state=state)
        if kind == "POSTGRES":
            self.btn_out.configure(text="⬇ Export CSV/JSON"); self.btn_in.configure(text="⬆ Import CSV/JSON"); self.btn_copy.configure(text="⧉ Auswahl kopieren")
            self.note_var.set("Datenbankmodus: Lesen, Suchen/Vorschau, Export und bestätigter Import. Löschen/Verschieben/Umbenennen von DB-Objekten bleibt gesperrt.")
        else:
            self.btn_out.configure(text="⬇ Herunterladen"); self.btn_in.configure(text="⬆ Hochladen"); self.btn_copy.configure(text="⧉ Kopieren")
            self.note_var.set("Verändernde Datei-/Objektaktionen benötigen eine Sicherheitsabfrage. Backup-Bereiche sind zusätzlich geschützt.")

    def _insert(self, parent: str, item: dict, text: str, values=(), expandable=False) -> str:
        iid = f"n{len(self.items)+1}"
        self.items[iid] = item
        self.tree.insert(parent, "end", iid=iid, text=text, values=values)
        if expandable:
            ph = iid + ":loading"; self.tree.insert(iid, "end", iid=ph, text="…")
        return iid

    def _replace_children(self, parent: str):
        for child in self.tree.get_children(parent):
            self.tree.delete(child); self.items.pop(child, None)

    def _selected(self) -> list[dict]:
        return [self.items[i] for i in self.tree.selection() if i in self.items]

    def _one_selected(self) -> dict | None:
        rows = self._selected(); return rows[0] if len(rows) == 1 else None

    # ---------- HiDrive ----------
    def _load_hidrive_root(self, target: dict):
        home = _hidrive_home(target)
        root = self._insert("", {"backend":"HIDRIVE","path":home,"name":target["name"],"is_dir":True,"root":True},
                            f"📁 {target['name']}", ("HiDrive Benutzerbereich", "–", "–", home), expandable=True)
        self.tree.item(root, open=True); self._load_hidrive_children(root)

    def _load_hidrive_children(self, iid: str):
        if iid in self.loaded_nodes or self.busy: return
        row = self.items.get(iid); target = self.current_target
        if not row or not target: return
        path = str(row.get("path") or "")
        self._set_busy(True, f"HiDrive lädt {path} …")
        def work():
            try:
                with sftp_connection(self.store, target["account_id"]) as (sftp, _): rows = list_remote_all(sftp, path)
                def done():
                    self._replace_children(iid)
                    for r in rows:
                        hidden = bool(r.get("hidden")); protected = _hidrive_protected(r["path"])
                        badge = "👁 [VERSTECKT] " if hidden else ""
                        icon = "📁" if r["is_dir"] else "📄"
                        kind = "Ordner" if r["is_dir"] else "Datei"
                        if protected: kind = "Geschützt · " + kind
                        mod = datetime.fromtimestamp(r["mtime"]).strftime("%d.%m.%Y %H:%M") if r.get("mtime") else "–"
                        r.update({"backend":"HIDRIVE"})
                        self._insert(iid, r, f"{badge}{icon} {r['name']}", (kind, "–" if r["is_dir"] else format_bytes(r["size"]), mod, r["path"]), expandable=bool(r["is_dir"]))
                    self.loaded_nodes.add(iid); self._set_busy(False, f"{len(rows)} HiDrive-Einträge geladen")
                self.after(0, done)
            except Exception as exc: self.after(0, lambda e=exc: self._load_error(e))
        threading.Thread(target=work, daemon=True).start()

    def _confirm_hidrive(self, paths: list[str], action: str) -> bool:
        if any(_hidrive_protected(p) for p in paths):
            answer = simpledialog.askstring("Backup-Bereich schützen", f"„{action}“ betrifft .pc-backup-vault.\nZum Fortfahren exakt BACKUP eingeben:", parent=self)
            if str(answer or "").strip().upper() != "BACKUP": return False
        return messagebox.askyesno(action, f"Aktion „{action}“ wirklich ausführen?", parent=self, default="no")

    # ---------- B2 ----------
    def _load_b2_root(self, target: dict):
        prefix = _b2_prefix(target.get("prefix") or "")
        root = self._insert("", {"backend":"B2","key":prefix,"name":target["name"],"is_dir":True,"root":True},
                            f"🪣 {target['name']}", ("B2 Bucket/Prefix", "–", "–", prefix or "/"), expandable=True)
        self.tree.item(root, open=True); self._load_b2_children(root)

    def _b2(self):
        store = make_b2_store(self.store.get_b2_runtime_config())
        if not store: raise RuntimeError("Backblaze B2 ist nicht vollständig eingerichtet.")
        return store, store._client()

    def _load_b2_children(self, iid: str):
        if iid in self.loaded_nodes or self.busy: return
        row = self.items.get(iid)
        if not row: return
        prefix = str(row.get("key") or "")
        self._set_busy(True, f"B2 lädt {prefix or '/'} …")
        def work():
            try:
                store, client = self._b2(); rows = _b2_list(client, store.bucket, prefix)
                def done():
                    self._replace_children(iid)
                    for r in rows:
                        r["backend"] = "B2"
                        mod = r.get("modified"); modtxt = mod.astimezone().strftime("%d.%m.%Y %H:%M") if hasattr(mod, "astimezone") else "–"
                        hidden = str(r.get("name") or "").startswith(".")
                        badge = "👁 [VERSTECKT] " if hidden else ""
                        icon = "📁" if r["is_dir"] else "📦"
                        self._insert(iid, r, f"{badge}{icon} {r['name']}", ("Virtueller Ordner" if r["is_dir"] else "B2 Objekt", "–" if r["is_dir"] else format_bytes(r["size"]), modtxt, r["key"]), expandable=bool(r["is_dir"]))
                    self.loaded_nodes.add(iid); self._set_busy(False, f"{len(rows)} B2-Einträge geladen")
                self.after(0, done)
            except Exception as exc: self.after(0, lambda e=exc: self._load_error(e))
        threading.Thread(target=work, daemon=True).start()

    def _confirm_b2_mutation(self, action: str) -> bool:
        answer = simpledialog.askstring("B2 Backup-Bereich schützen", f"„{action}“ verändert Objekte im konfigurierten PC-Backup-Vault-Prefix.\n\nZum Fortfahren exakt BACKUP eingeben:", parent=self)
        if str(answer or "").strip().upper() != "BACKUP": return False
        return messagebox.askyesno(action, f"Aktion „{action}“ auf Backblaze B2 wirklich ausführen?", parent=self, default="no")

    # ---------- PostgreSQL / Neon / Supabase ----------
    def _dsn(self) -> str:
        target = self.current_target or {}
        dsn = self.store.get_dsn(target.get("profile_id"))
        if not dsn: raise RuntimeError("Datenbank-DSN fehlt im Windows-Anmeldetresor.")
        return dsn

    def _load_db_root(self, target: dict):
        root = self._insert("", {"backend":"POSTGRES","node_type":"database","name":target["name"],"is_dir":True},
                            f"🗄 {target['label']}", ("Datenbankprojekt", "–", "–", target.get("database") or target.get("project_ref") or ""), expandable=True)
        self.tree.item(root, open=True); self._load_db_children(root)

    def _load_db_children(self, iid: str):
        if iid in self.loaded_nodes or self.busy: return
        row = self.items.get(iid)
        if not row: return
        node_type = row.get("node_type")
        self._set_busy(True, "Datenbankstruktur wird gelesen …")
        def work():
            try:
                with psycopg.connect(self._dsn(), connect_timeout=10) as conn:
                    if node_type == "database": data = [(s, "schema", "") for s in _sql_user_schemas(conn)]
                    elif node_type == "schema": data = [(n, "relation", t) for n, t in _sql_relations(conn, row["schema"])]
                    elif node_type == "relation": data = [(n, "column", f"{typ} · {'NULL' if null=='YES' else 'NOT NULL'}") for n, typ, null in _sql_columns(conn, row["schema"], row["table"])]
                    else: data = []
                def done():
                    self._replace_children(iid)
                    for name, typ, detail in data:
                        if typ == "schema":
                            item={"backend":"POSTGRES","node_type":"schema","schema":name,"name":name,"is_dir":True}; icon="📂"; kind="Schema"; expandable=True
                        elif typ == "relation":
                            item={"backend":"POSTGRES","node_type":"relation","schema":row["schema"],"table":name,"name":name,"is_dir":True,"relation_type":detail}; icon="📋"; kind=detail.title(); expandable=True
                        else:
                            item={"backend":"POSTGRES","node_type":"column","schema":row["schema"],"table":row["table"],"name":name,"is_dir":False}; icon="▫"; kind="Spalte"; expandable=False
                        self._insert(iid, item, f"{icon} {name}", (kind, "–", "–", detail), expandable=expandable)
                    self.loaded_nodes.add(iid); self._set_busy(False, f"{len(data)} Datenbankobjekte geladen")
                self.after(0, done)
            except Exception as exc: self.after(0, lambda e=exc: self._load_error(e))
        threading.Thread(target=work, daemon=True).start()

    def _preview_relation(self, row: dict):
        schema = row["schema"]; table = row["table"]
        self._set_busy(True, f"Lese {schema}.{table} …")
        def work():
            try:
                with psycopg.connect(self._dsn(), connect_timeout=10) as conn:
                    cur = conn.execute(sql.SQL("SELECT * FROM {}.{} LIMIT 200").format(sql.Identifier(schema), sql.Identifier(table)))
                    records = cur.fetchall(); cols = [d.name for d in cur.description]
                self.after(0, lambda: self._render_preview(schema, table, cols, records))
            except Exception as exc: self.after(0, lambda e=exc: self._load_error(e))
        threading.Thread(target=work, daemon=True).start()

    def _render_preview(self, schema: str, table: str, columns: list[str], rows: list[tuple]):
        self.preview.delete(*self.preview.get_children()); self.preview.configure(columns=columns, displaycolumns=columns)
        for c in columns:
            self.preview.heading(c, text=c); self.preview.column(c, width=max(110, min(260, len(c)*11)), anchor="w")
        for row in rows:
            vals = [(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict,list)) else ("NULL" if v is None else str(v))) for v in row]
            self.preview.insert("", "end", values=vals)
        self.preview_info.set(f"{schema}.{table}: {len(rows)} Datensätze angezeigt (max. 200)")
        self._set_busy(False, f"{len(rows)} Datensätze geladen")

    def _clear_preview(self):
        self.preview.delete(*self.preview.get_children()); self.preview.configure(columns=())
        self.preview_info.set("Bei Datenbanktabellen erscheinen hier die ersten 200 Datensätze.")

    # ---------- Tree events ----------
    def _tree_open(self, _event=None):
        iid = self.tree.focus()
        row = self.items.get(iid)
        if not row: return
        if row.get("backend") == "HIDRIVE": self._load_hidrive_children(iid)
        elif row.get("backend") == "B2": self._load_b2_children(iid)
        elif row.get("backend") == "POSTGRES": self._load_db_children(iid)

    def _double_click(self, event=None):
        iid = self.tree.identify_row(event.y) if event else self.tree.focus()
        row = self.items.get(iid)
        if not row: return
        if row.get("backend") == "POSTGRES" and row.get("node_type") == "relation": self._preview_relation(row)
        elif row.get("is_dir"):
            self.tree.item(iid, open=not bool(self.tree.item(iid, "open"))); self.tree.focus(iid); self._tree_open()

    def _load_error(self, exc):
        self._set_busy(False, "Fehler beim Lesen")
        messagebox.showerror("Speicher-Explorer", str(exc), parent=self)

    # ---------- Common actions ----------
    def new_folder(self):
        target = self.current_target or {}
        if target.get("kind") == "HIDRIVE": self._hidrive_new_folder()
        elif target.get("kind") == "B2": self._b2_new_folder()

    def download_export(self):
        target = self.current_target or {}
        if target.get("kind") == "HIDRIVE": self._hidrive_download()
        elif target.get("kind") == "B2": self._b2_download()
        elif target.get("kind") == "POSTGRES": self._db_export()

    def upload_import(self):
        target = self.current_target or {}
        if target.get("kind") == "HIDRIVE": self._hidrive_upload()
        elif target.get("kind") == "B2": self._b2_upload()
        elif target.get("kind") == "POSTGRES": self._db_import()

    def copy_selected(self):
        target = self.current_target or {}
        if target.get("kind") == "HIDRIVE": self._hidrive_copy(False)
        elif target.get("kind") == "B2": self._b2_copy(False)
        elif target.get("kind") == "POSTGRES": self._copy_preview()

    def move_selected(self):
        target = self.current_target or {}
        if target.get("kind") == "HIDRIVE": self._hidrive_move()
        elif target.get("kind") == "B2": self._b2_copy(True)

    def rename_selected(self):
        target = self.current_target or {}
        if target.get("kind") == "HIDRIVE": self._hidrive_rename()
        elif target.get("kind") == "B2": self._b2_rename()

    def delete_selected(self):
        target = self.current_target or {}
        if target.get("kind") == "HIDRIVE": self._hidrive_delete()
        elif target.get("kind") == "B2": self._b2_delete()

    def properties(self):
        row = self._one_selected()
        if not row: messagebox.showinfo("Eigenschaften", "Bitte genau einen Eintrag auswählen.", parent=self); return
        text = "\n".join(f"{k}: {v}" for k,v in row.items() if k not in {"backend"})
        messagebox.showinfo("Eigenschaften", text or "Keine Details verfügbar.", parent=self)

    # ---------- HiDrive actions ----------
    def _hidrive_target_dir(self) -> str:
        row = self._one_selected()
        if row and row.get("backend") == "HIDRIVE" and row.get("is_dir"): return str(row["path"])
        return _hidrive_home(self.current_target or {})

    def _hidrive_new_folder(self):
        dest = self._hidrive_target_dir(); name = simpledialog.askstring("Neuer Ordner", "Ordnername:", parent=self)
        if not name: return
        remote = posixpath.join(dest, _safe_name(name))
        if not self._confirm_hidrive([remote], "Ordner anlegen"): return
        account_id=(self.current_target or {})["account_id"]
        def worker(report):
            with sftp_connection(self.store, account_id) as (sftp,_): sftp.mkdir(remote)
            report(phase="Ordner angelegt", files_done=1, files_total=1)
        self._run("HiDrive Ordner anlegen", worker, f"Ordner {name} angelegt")

    def _hidrive_download(self):
        rows=[r for r in _collapse_nested(self._selected()) if r.get("backend")=="HIDRIVE" and not r.get("root")]
        if not rows: messagebox.showinfo("Download", "Bitte Datei(en) oder Ordner auswählen.", parent=self); return
        dest=filedialog.askdirectory(parent=self,title="Lokalen Zielordner auswählen")
        if not dest: return
        account_id=(self.current_target or {})["account_id"]; base=Path(dest)
        def worker(report):
            files=[]; dirs=[]
            with sftp_connection(self.store,account_id) as (sftp,_):
                def walk(remote, rel, is_dir, size=0):
                    if is_dir:
                        dirs.append(rel)
                        for a in sftp.listdir_attr(remote):
                            n=str(getattr(a,"filename","") or "");
                            if not n or n in {".",".."}: continue
                            walk(posixpath.join(remote,n),posixpath.join(rel,n),statmod.S_ISDIR(int(getattr(a,"st_mode",0) or 0)),int(getattr(a,"st_size",0) or 0))
                    else: files.append((remote,rel,int(size or 0)))
                for r in rows: walk(r["path"],r["name"],bool(r["is_dir"]),int(r.get("size") or 0))
                total=sum(x[2] for x in files); done=0
                for d in dirs: (base/Path(d)).mkdir(parents=True,exist_ok=True)
                for i,(remote,rel,size) in enumerate(files,1):
                    local=base/Path(rel); local.parent.mkdir(parents=True,exist_ok=True); before=done
                    with sftp.open(remote,"rb") as src, open(local,"wb") as dst:
                        copied=_copy_stream(src,dst,size,lambda n,_t: report(phase="Download läuft",current_file=remote,files_done=i-1,files_total=len(files),bytes_done=before+n,bytes_total=total))
                    done+=copied; report(phase="Download läuft",current_file=remote,files_done=i,files_total=len(files),bytes_done=done,bytes_total=total)
        self._run("HiDrive Download",worker,f"{len(rows)} Auswahl(en) heruntergeladen",refresh=False)

    def _hidrive_upload(self):
        dest=self._hidrive_target_dir(); files=filedialog.askopenfilenames(parent=self,title="Dateien zum Hochladen auswählen")
        if not files: return
        remotes=[posixpath.join(dest,Path(x).name) for x in files]
        if not self._confirm_hidrive(remotes,"Hochladen"): return
        account_id=(self.current_target or {})["account_id"]; total=sum(Path(x).stat().st_size for x in files)
        def worker(report):
            done=0
            with sftp_connection(self.store,account_id) as (sftp,_):
                _ensure_remote_dir(sftp,dest)
                for i,(local_name,remote) in enumerate(zip(files,remotes),1):
                    local=Path(local_name); size=local.stat().st_size; before=done
                    with open(local,"rb") as src, sftp.open(remote,"wb") as dst:
                        copied=_copy_stream(src,dst,size,lambda n,_t: report(phase="Upload läuft",current_file=str(local),files_done=i-1,files_total=len(files),bytes_done=before+n,bytes_total=total))
                    done+=copied; report(phase="Upload läuft",current_file=str(local),files_done=i,files_total=len(files),bytes_done=done,bytes_total=total)
        self._run("HiDrive Upload",worker,f"{len(files)} Datei(en) hochgeladen")

    def _hidrive_rename(self):
        row=self._one_selected()
        if not row or row.get("backend")!="HIDRIVE" or row.get("root"): messagebox.showinfo("Umbenennen","Bitte genau einen Eintrag auswählen.",parent=self); return
        name=simpledialog.askstring("Umbenennen","Neuer Name:",initialvalue=row["name"],parent=self)
        if not name: return
        dest=posixpath.join(posixpath.dirname(row["path"]),_safe_name(name))
        if not self._confirm_hidrive([row["path"],dest],"Umbenennen"): return
        account_id=(self.current_target or {})["account_id"]
        self._run("HiDrive umbenennen",lambda report:self._hidrive_rename_worker(account_id,row["path"],dest,report),f"{row['name']} umbenannt")

    def _hidrive_rename_worker(self,account_id,src,dest,report):
        with sftp_connection(self.store,account_id) as (sftp,_): sftp.rename(src,dest)
        report(phase="Umbenannt",files_done=1,files_total=1)

    def _hidrive_move(self):
        rows=[r for r in _collapse_nested(self._selected()) if r.get("backend")=="HIDRIVE" and not r.get("root")]
        if not rows: return
        picker=RemoteFolderPicker(self,self.store,{"id":(self.current_target or {})["account_id"],"username":(self.current_target or {}).get("username")},self._hidrive_target_dir())
        self.wait_window(picker); dest=picker.result
        if not dest: return
        dests=[posixpath.join(dest,r["name"]) for r in rows]
        if not self._confirm_hidrive([r["path"] for r in rows]+dests,"Verschieben"): return
        account_id=(self.current_target or {})["account_id"]
        def worker(report):
            with sftp_connection(self.store,account_id) as (sftp,_):
                for i,(r,d) in enumerate(zip(rows,dests),1):
                    if r.get("is_dir") and d.startswith(str(r["path"]).rstrip("/")+"/"): raise ValueError("Ordner kann nicht in sich selbst verschoben werden.")
                    sftp.rename(r["path"],d); report(phase="Verschieben läuft",current_file=r["path"],files_done=i,files_total=len(rows))
        self._run("HiDrive verschieben",worker,f"{len(rows)} Eintrag/Einträge verschoben")

    def _hidrive_copy(self,_move=False):
        rows=[r for r in _collapse_nested(self._selected()) if r.get("backend")=="HIDRIVE" and not r.get("root")]
        if not rows: return
        picker=RemoteFolderPicker(self,self.store,{"id":(self.current_target or {})["account_id"],"username":(self.current_target or {}).get("username")},self._hidrive_target_dir())
        self.wait_window(picker); dest=picker.result
        if not dest: return
        if not self._confirm_hidrive([posixpath.join(dest,r["name"]) for r in rows],"Kopieren"): return
        account_id=(self.current_target or {})["account_id"]
        def worker(report):
            files=[]; dirs=[]
            with sftp_connection(self.store,account_id) as (sftp,_):
                def walk(remote,rel,is_dir,size=0):
                    if is_dir:
                        dirs.append(rel)
                        for a in sftp.listdir_attr(remote):
                            n=str(getattr(a,"filename","") or "");
                            if not n or n in {".",".."}: continue
                            walk(posixpath.join(remote,n),posixpath.join(rel,n),statmod.S_ISDIR(int(getattr(a,"st_mode",0) or 0)),int(getattr(a,"st_size",0) or 0))
                    else: files.append((remote,rel,int(size or 0)))
                for r in rows: walk(r["path"],r["name"],bool(r["is_dir"]),int(r.get("size") or 0))
                for d in dirs: _ensure_remote_dir(sftp,posixpath.join(dest,d))
                total=sum(x[2] for x in files); done=0
                for i,(src,rel,size) in enumerate(files,1):
                    target=posixpath.join(dest,rel); _ensure_remote_dir(sftp,posixpath.dirname(target)); before=done
                    with sftp.open(src,"rb") as inp,sftp.open(target,"wb") as out:
                        copied=_copy_stream(inp,out,size,lambda n,_t:report(phase="Kopieren läuft",current_file=src,files_done=i-1,files_total=len(files),bytes_done=before+n,bytes_total=total))
                    done+=copied; report(phase="Kopieren läuft",current_file=src,files_done=i,files_total=len(files),bytes_done=done,bytes_total=total)
        self._run("HiDrive kopieren",worker,f"{len(rows)} Auswahl(en) kopiert")

    def _hidrive_delete(self):
        rows=[r for r in _collapse_nested(self._selected()) if r.get("backend")=="HIDRIVE" and not r.get("root")]
        if not rows: return
        if not self._confirm_hidrive([r["path"] for r in rows],"Löschen"): return
        account_id=(self.current_target or {})["account_id"]
        def worker(report):
            with sftp_connection(self.store,account_id) as (sftp,_):
                def remove(path):
                    info=sftp.stat(path)
                    if statmod.S_ISDIR(int(getattr(info,"st_mode",0) or 0)):
                        for a in sftp.listdir_attr(path): remove(posixpath.join(path,str(a.filename)))
                        sftp.rmdir(path)
                    else: sftp.remove(path)
                for i,r in enumerate(rows,1): remove(r["path"]); report(phase="Löschen läuft",current_file=r["path"],files_done=i,files_total=len(rows))
        self._run("HiDrive löschen",worker,f"{len(rows)} Auswahl(en) gelöscht")

    # ---------- B2 actions ----------
    def _b2_target_prefix(self) -> str:
        row=self._one_selected()
        if row and row.get("backend")=="B2" and row.get("is_dir"): return _b2_prefix(row["key"])
        return _b2_prefix((self.current_target or {}).get("prefix") or "")

    def _b2_new_folder(self):
        name=simpledialog.askstring("B2 Ordner","Name des virtuellen Ordners:",parent=self)
        if not name: return
        if not self._confirm_b2_mutation("Ordner anlegen"): return
        key=self._b2_target_prefix()+_safe_name(name)+"/"
        def worker(report):
            store,client=self._b2(); client.put_object(Bucket=store.bucket,Key=key,Body=b""); report(phase="Ordner angelegt",files_done=1,files_total=1)
        self._run("B2 Ordner anlegen",worker,f"Ordner {name} angelegt")

    def _b2_download(self):
        rows=[r for r in _collapse_nested(self._selected(),"key") if r.get("backend")=="B2" and not r.get("root")]
        if not rows: return
        dest=filedialog.askdirectory(parent=self,title="Lokalen Zielordner auswählen")
        if not dest: return
        base=Path(dest)
        def worker(report):
            store,client=self._b2(); objects=_b2_recursive(client,store.bucket,rows); total=sum(o["size"] for o in objects); done=0
            base_prefix=_b2_prefix((self.current_target or {}).get("prefix") or "")
            for i,o in enumerate(objects,1):
                rel=o["key"][len(base_prefix):] if o["key"].startswith(base_prefix) else o["key"].rsplit("/",1)[-1]
                local=base/Path(rel); local.parent.mkdir(parents=True,exist_ok=True); response=client.get_object(Bucket=store.bucket,Key=o["key"]); body=response["Body"]; before=done
                with open(local,"wb") as fh:
                    while True:
                        chunk=body.read(256*1024)
                        if not chunk: break
                        fh.write(chunk); done+=len(chunk); report(phase="B2 Download",current_file=o["key"],files_done=i-1,files_total=len(objects),bytes_done=done,bytes_total=total)
                report(phase="B2 Download",current_file=o["key"],files_done=i,files_total=len(objects),bytes_done=done,bytes_total=total)
        self._run("B2 Download",worker,f"{len(rows)} Auswahl(en) heruntergeladen",refresh=False)

    def _b2_upload(self):
        files=filedialog.askopenfilenames(parent=self,title="Dateien zu B2 hochladen")
        if not files: return
        if not self._confirm_b2_mutation("Hochladen"): return
        prefix=self._b2_target_prefix(); total=sum(Path(x).stat().st_size for x in files)
        def worker(report):
            store,client=self._b2(); done=0
            for i,name in enumerate(files,1):
                path=Path(name); key=prefix+path.name; before=done
                def cb(n):
                    nonlocal done
                    done += int(n or 0); report(phase="B2 Upload",current_file=str(path),files_done=i-1,files_total=len(files),bytes_done=done,bytes_total=total)
                client.upload_file(str(path),store.bucket,key,Callback=cb)
                report(phase="B2 Upload",current_file=str(path),files_done=i,files_total=len(files),bytes_done=done,bytes_total=total)
        self._run("B2 Upload",worker,f"{len(files)} Datei(en) hochgeladen")

    def _b2_copy(self, move: bool):
        rows=[r for r in _collapse_nested(self._selected(),"key") if r.get("backend")=="B2" and not r.get("root")]
        if not rows: return
        action="Verschieben" if move else "Kopieren"
        if not self._confirm_b2_mutation(action): return
        default=self._b2_target_prefix(); dest=simpledialog.askstring(f"B2 {action}","Ziel-Prefix:",initialvalue=default,parent=self)
        if dest is None: return
        dest=_b2_prefix(dest)
        def worker(report):
            store,client=self._b2(); objects=_b2_recursive(client,store.bucket,rows); total=sum(o["size"] for o in objects)
            roots=[]
            for r in rows: roots.append(str(r["key"]))
            for i,o in enumerate(objects,1):
                src=o["key"]
                root=next((r for r in roots if src==r or src.startswith(_b2_prefix(r))),src)
                base_name=root.rstrip("/").rsplit("/",1)[-1]; suffix=src[len(_b2_prefix(root)):] if src.startswith(_b2_prefix(root)) else ""
                target=dest+base_name+("/"+suffix if suffix else "")
                client.copy_object(Bucket=store.bucket,CopySource={"Bucket":store.bucket,"Key":src},Key=target)
                if move: client.delete_object(Bucket=store.bucket,Key=src)
                report(phase=f"B2 {action}",current_file=src,files_done=i,files_total=len(objects),bytes_done=sum(x["size"] for x in objects[:i]),bytes_total=total)
        self._run(f"B2 {action}",worker,f"{len(rows)} Auswahl(en) {action.lower()}")

    def _b2_rename(self):
        row=self._one_selected()
        if not row or row.get("backend")!="B2" or row.get("root"): return
        name=simpledialog.askstring("B2 umbenennen","Neuer Name:",initialvalue=row["name"],parent=self)
        if not name: return
        name=_safe_name(name)
        if not self._confirm_b2_mutation("Umbenennen"): return
        parent=row["key"].rstrip("/").rsplit("/",1)[0] if "/" in row["key"].rstrip("/") else ""
        dest=_b2_prefix(parent)+name+("/" if row.get("is_dir") else "")
        def worker(report):
            store,client=self._b2(); objects=_b2_recursive(client,store.bucket,[row]); total=sum(o["size"] for o in objects); done=0
            srcroot=_b2_prefix(row["key"]) if row.get("is_dir") else row["key"]
            for i,o in enumerate(objects,1):
                suffix=o["key"][len(srcroot):] if row.get("is_dir") else ""
                target=_b2_prefix(dest)+suffix if row.get("is_dir") else dest
                client.copy_object(Bucket=store.bucket,CopySource={"Bucket":store.bucket,"Key":o["key"]},Key=target); client.delete_object(Bucket=store.bucket,Key=o["key"])
                done+=o["size"]; report(phase="B2 Umbenennen",current_file=o["key"],files_done=i,files_total=len(objects),bytes_done=done,bytes_total=total)
        self._run("B2 umbenennen",worker,f"{row['name']} umbenannt")

    def _b2_delete(self):
        rows=[r for r in _collapse_nested(self._selected(),"key") if r.get("backend")=="B2" and not r.get("root")]
        if not rows: return
        if not self._confirm_b2_mutation("Löschen"): return
        def worker(report):
            store,client=self._b2(); objects=_b2_recursive(client,store.bucket,rows); total=len(objects)
            for start in range(0,total,1000):
                batch=objects[start:start+1000]
                client.delete_objects(Bucket=store.bucket,Delete={"Objects":[{"Key":o["key"]} for o in batch],"Quiet":True})
                report(phase="B2 Löschen",files_done=min(start+len(batch),total),files_total=total)
        self._run("B2 löschen",worker,f"{len(rows)} Auswahl(en) gelöscht")

    # ---------- DB actions ----------
    def _relation_selected(self) -> dict | None:
        row=self._one_selected()
        return row if row and row.get("backend")=="POSTGRES" and row.get("node_type")=="relation" else None

    def _db_export(self):
        row=self._relation_selected()
        if not row: messagebox.showinfo("Export","Bitte genau eine Tabelle oder View auswählen.",parent=self); return
        path=filedialog.asksaveasfilename(parent=self,title="Tabelle exportieren",defaultextension=".csv",filetypes=[("CSV","*.csv"),("JSON","*.json")],initialfile=f"{row['schema']}_{row['table']}.csv")
        if not path: return
        def worker(report):
            with psycopg.connect(self._dsn(),connect_timeout=10) as conn:
                cur=conn.execute(sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(row["schema"]),sql.Identifier(row["table"])))
                columns=[d.name for d in cur.description]; records=cur.fetchall()
            report(phase="Export läuft",files_done=0,files_total=len(records))
            p=Path(path)
            if p.suffix.lower()==".json":
                data=[{c:v for c,v in zip(columns,r)} for r in records]
                p.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
            else:
                with p.open("w",newline="",encoding="utf-8-sig") as fh:
                    w=csv.writer(fh,delimiter=";"); w.writerow(columns)
                    for i,r in enumerate(records,1): w.writerow(r); report(phase="Export läuft",files_done=i,files_total=len(records))
            report(phase="Export abgeschlossen",files_done=len(records),files_total=len(records))
        self._run("Datenbank Export",worker,f"{row['schema']}.{row['table']} exportiert",refresh=False)

    def _db_import(self):
        row=self._relation_selected()
        if not row: messagebox.showinfo("Import","Bitte genau eine Zieltabelle auswählen.",parent=self); return
        path=filedialog.askopenfilename(parent=self,title="CSV/JSON importieren",filetypes=[("CSV/JSON","*.csv *.json"),("CSV","*.csv"),("JSON","*.json")])
        if not path: return
        typed=simpledialog.askstring("Datenbank-Import bestätigen",f"Import fügt Datensätze in {row['schema']}.{row['table']} ein.\nBestehende Datensätze werden nicht automatisch gelöscht.\n\nZum Fortfahren exakt DATENBANK eingeben:",parent=self)
        if str(typed or "").strip().upper()!="DATENBANK": return
        if not messagebox.askyesno("Import starten",f"Datei wirklich in {row['schema']}.{row['table']} importieren?\n\n{path}",parent=self,default="no"): return
        def worker(report):
            p=Path(path)
            if p.suffix.lower()==".json":
                raw=json.loads(p.read_text(encoding="utf-8"));
                if not isinstance(raw,list) or not all(isinstance(x,dict) for x in raw): raise ValueError("JSON muss eine Liste aus Objekten sein.")
                records=raw; columns=list(records[0].keys()) if records else []
            else:
                text=p.read_text(encoding="utf-8-sig"); sample=text[:4096]; delim=";" if sample.count(";")>=sample.count(",") else ","
                reader=csv.DictReader(io.StringIO(text),delimiter=delim); columns=list(reader.fieldnames or []); records=list(reader)
            if not columns: raise ValueError("Keine Spaltenüberschriften gefunden.")
            with psycopg.connect(self._dsn(),connect_timeout=10) as conn:
                known={c[0] for c in _sql_columns(conn,row["schema"],row["table"])}
                unknown=[c for c in columns if c not in known]
                if unknown: raise ValueError("Unbekannte Zielspalten: "+", ".join(unknown))
                stmt=sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(sql.Identifier(row["schema"]),sql.Identifier(row["table"]),sql.SQL(",").join(map(sql.Identifier,columns)),sql.SQL(",").join(sql.Placeholder() for _ in columns))
                vals=[]
                for rec in records:
                    vals.append(tuple(None if rec.get(c)=="" else rec.get(c) for c in columns))
                for start in range(0,len(vals),250):
                    batch=vals[start:start+250]; conn.executemany(stmt,batch); report(phase="Import läuft",files_done=min(start+len(batch),len(vals)),files_total=len(vals))
                conn.commit()
            report(phase="Import abgeschlossen",files_done=len(records),files_total=len(records))
        self._run("Datenbank Import",worker,f"Import in {row['schema']}.{row['table']} abgeschlossen",refresh=False)

    def _copy_preview(self):
        selected=self.preview.selection()
        if not selected: return
        cols=list(self.preview["columns"]); lines=["\t".join(cols)]
        for iid in selected: lines.append("\t".join(str(x) for x in self.preview.item(iid,"values")))
        self.clipboard_clear(); self.clipboard_append("\n".join(lines)); self.update_idletasks(); self.status_var.set(f"{len(selected)} Datenzeile(n) kopiert")

    # ---------- Context menus ----------
    def _context_menu(self,event):
        iid=self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection(): self.tree.selection_set(iid); self.tree.focus(iid)
        if not iid: return
        kind=(self.current_target or {}).get("kind")
        menu=tk.Menu(self,tearoff=False)
        if kind=="POSTGRES":
            row=self._one_selected()
            if row and row.get("node_type")=="relation": menu.add_command(label="Datensätze anzeigen",command=lambda:self._preview_relation(row))
            menu.add_command(label="Export CSV/JSON",command=self._db_export); menu.add_command(label="Import CSV/JSON",command=self._db_import)
            menu.add_separator(); menu.add_command(label="Eigenschaften",command=self.properties)
        else:
            menu.add_command(label="Herunterladen",command=self.download_export); menu.add_command(label="Hochladen",command=self.upload_import)
            menu.add_separator(); menu.add_command(label="Kopieren",command=self.copy_selected); menu.add_command(label="Verschieben",command=self.move_selected); menu.add_command(label="Umbenennen",command=self.rename_selected); menu.add_command(label="Löschen",command=self.delete_selected)
            menu.add_separator(); menu.add_command(label="Neuer Ordner",command=self.new_folder); menu.add_command(label="Eigenschaften",command=self.properties)
        menu.add_separator(); menu.add_command(label="Aktualisieren",command=self.refresh)
        menu.tk_popup(event.x_root,event.y_root); return "break"

    def _preview_context(self,event):
        iid=self.preview.identify_row(event.y)
        if iid and iid not in self.preview.selection(): self.preview.selection_set(iid)
        if not self.preview.selection(): return
        menu=tk.Menu(self,tearoff=False); menu.add_command(label="Auswahl kopieren",command=self._copy_preview); menu.tk_popup(event.x_root,event.y_root); return "break"


def apply_storage_center_v1919(AppClass):
    if getattr(AppClass,"_storage_center_v1919",False): return
    AppClass.open_storage_center_v1919=lambda self: StorageCenterWindow(self)
    AppClass._storage_center_v1919=True
