from __future__ import annotations

import ctypes
import json
import os
import shutil
import string
import threading
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from tkinter import filedialog, messagebox, simpledialog


DB_PROVIDERS = {"neon": "Neon", "supabase": "Supabase", "postgresql": "PostgreSQL"}
_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def _fs_attributes(path: str | Path) -> tuple[bool, bool]:
    """Return Windows hidden/system flags without hiding dot-files on other systems."""
    p = Path(path)
    hidden = p.name.startswith(".")
    system = False
    if os.name == "nt":
        try:
            attrs = int(ctypes.windll.kernel32.GetFileAttributesW(str(p)))
            if attrs != _INVALID_FILE_ATTRIBUTES:
                hidden = hidden or bool(attrs & _FILE_ATTRIBUTE_HIDDEN)
                system = bool(attrs & _FILE_ATTRIBUTE_SYSTEM)
        except Exception:
            pass
    return hidden, system


def _fs_list(path: str | Path) -> list[dict]:
    root = Path(path)
    rows: list[dict] = []
    for child in root.iterdir():
        try:
            st = child.stat()
            is_dir = child.is_dir()
            size = 0 if is_dir else int(st.st_size)
            mtime = float(st.st_mtime)
        except Exception:
            is_dir = False
            size = 0
            mtime = 0.0
        hidden, system = _fs_attributes(child)
        rows.append({
            "name": child.name,
            "path": str(child),
            "is_dir": bool(is_dir),
            "size": size,
            "mtime": mtime,
            "hidden": hidden,
            "system": system,
        })
    rows.sort(key=lambda r: (not r["is_dir"], str(r["name"]).casefold()))
    return rows


def _windows_drives() -> list[str]:
    if hasattr(os, "listdrives"):
        try:
            return sorted(str(x) for x in os.listdrives())
        except Exception:
            pass
    if os.name == "nt":
        return [f"{letter}:\\" for letter in string.ascii_uppercase if Path(f"{letter}:\\").exists()]
    return [str(Path.home().anchor or "/")]


def _sql_databases(conn) -> list[str]:
    rows = conn.execute(
        """SELECT datname FROM pg_database
           WHERE datallowconn AND NOT datistemplate
           ORDER BY datname"""
    ).fetchall()
    return [str(r[0]) for r in rows]


def _dsn_database(dsn: str, database: str | None) -> str:
    return make_conninfo(dsn, dbname=database) if database else dsn


def _configured_filesystem_targets(store) -> list[dict]:
    out = []
    for target in list(store.data.get("filesystem_targets") or []):
        tid = str(target.get("id") or "")
        path = str(target.get("path") or "")
        if not tid or not path:
            continue
        fs_kind = str(target.get("kind") or "ORDNER").upper()
        name = str(target.get("name") or Path(path).name or path)
        prefix = "NAS" if fs_kind == "NAS" or path.startswith("\\\\") else "PC / Laufwerk"
        out.append({
            "id": f"fs:{tid}", "kind": "FILESYSTEM", "name": name,
            "label": f"{prefix} · {name}", "path": path, "fs_kind": fs_kind,
            "ready": Path(path).exists(),
        })
    return out


def collect_storage_targets_v1920(store, original_collect) -> list[dict]:
    """Collect every known target and make absence/unreachability visible instead of hiding it."""
    out = [dict(x) for x in original_collect(store)]

    # B2 must show the real whole bucket. Keep the configured backup prefix only
    # as protection metadata instead of using it as the explorer root.
    b2_found = False
    for row in out:
        if row.get("kind") == "B2":
            b2_found = True
            row["backup_prefix"] = str(row.get("prefix") or "").strip("/")
            row["prefix"] = ""
            row["ready"] = True
    if not b2_found:
        b2_meta = dict(store.data.get("b2") or {})
        if b2_meta.get("bucket"):
            cfg = store.get_b2_runtime_config()
            bucket = str(b2_meta.get("bucket"))
            out.append({
                "id": "b2:default", "kind": "B2", "name": bucket,
                "label": f"Backblaze B2 · {bucket} · [nicht verbunden]",
                "prefix": "", "backup_prefix": str(b2_meta.get("prefix") or "pc-backup-vault").strip("/"),
                "ready": bool(cfg.get("configured")),
            })

    # Existing 1.9.19 entries include DB profiles only when a DSN exists.
    # 1.9.20 also shows known profiles with missing credentials explicitly.
    existing_db_ids = {str(r.get("profile_id")) for r in out if r.get("kind") == "POSTGRES"}
    for row in out:
        if row.get("kind") == "POSTGRES":
            row["ready"] = bool(store.get_dsn(str(row.get("profile_id") or "")))
    for profile in list(store.data.get("profiles") or []):
        if profile.get("enabled", True) is False:
            continue
        provider = str(profile.get("provider") or "").lower()
        if provider not in DB_PROVIDERS:
            continue
        pid = str(profile.get("id") or "")
        if not pid or pid in existing_db_ids:
            continue
        name = str(profile.get("name") or profile.get("database") or pid)
        ready = bool(store.get_dsn(pid))
        suffix = "" if ready else " · [Zugang fehlt]"
        out.append({
            "id": f"db:{pid}", "kind": "POSTGRES", "name": name,
            "label": f"{DB_PROVIDERS[provider]} · {name}{suffix}", "profile_id": pid,
            "provider": provider, "database": str(profile.get("database") or ""),
            "project_ref": str(profile.get("project_ref") or ""), "ready": ready,
        })

    # "Dieser PC" gives a truthful top-level view of all currently visible
    # drives. Configured filesystem/NAS targets remain separate named entries.
    out.append({"id": "fs:this-pc", "kind": "THIS_PC", "name": "Dieser PC", "label": "Dieser PC · Laufwerke", "ready": True})
    out.extend(_configured_filesystem_targets(store))
    return out


def _b2_is_protected(target: dict, key: str) -> bool:
    prefix = str(target.get("backup_prefix") or "").strip("/")
    clean = str(key or "").strip("/")
    return bool(prefix and (clean == prefix or clean.startswith(prefix + "/")))


def _relation_dsn(window, row: dict) -> str:
    return _dsn_database(window._dsn(), str(row.get("database") or "") or None)


def _fs_manifest(rows: list[dict]) -> tuple[list[tuple[Path, Path, int]], list[Path], int]:
    """Expand selected paths into files while preserving each selected top-level name."""
    files: list[tuple[Path, Path, int]] = []
    dirs: list[Path] = []
    total = 0
    for row in rows:
        src = Path(str(row["path"]))
        top = Path(src.name)
        if row.get("is_dir"):
            dirs.append(top)
            for root, dirnames, filenames in os.walk(src):
                rootp = Path(root)
                relroot = top / rootp.relative_to(src)
                for d in dirnames:
                    dirs.append(relroot / d)
                for name in filenames:
                    p = rootp / name
                    try: size = int(p.stat().st_size)
                    except Exception: size = 0
                    files.append((p, relroot / name, size)); total += size
        else:
            try: size = int(src.stat().st_size)
            except Exception: size = 0
            files.append((src, top, size)); total += size
    return files, dirs, total


def apply_storage_center_exact_v1920(storage_module, WindowClass):
    if getattr(WindowClass, "_storage_center_exact_v1920", False):
        return
    WindowClass._storage_center_exact_v1920 = True

    original_collect = storage_module.collect_storage_targets
    storage_module.collect_storage_targets = lambda store: collect_storage_targets_v1920(store, original_collect)
    original_update_actions = WindowClass._update_actions
    original_refresh = WindowClass.refresh
    original_tree_open = WindowClass._tree_open
    original_double_click = WindowClass._double_click
    original_download = WindowClass.download_export
    original_upload = WindowClass.upload_import
    original_copy = WindowClass.copy_selected
    original_move = WindowClass.move_selected
    original_rename = WindowClass.rename_selected
    original_delete = WindowClass.delete_selected
    original_new = WindowClass.new_folder

    def update_actions(self):
        kind = (self.current_target or {}).get("kind")
        if kind not in {"FILESYSTEM", "THIS_PC"}:
            original_update_actions(self); return
        states = ("normal", "normal", "normal", "normal", "normal", "normal", "normal")
        for btn, state in zip((self.btn_new, self.btn_out, self.btn_in, self.btn_copy, self.btn_move, self.btn_rename, self.btn_delete), states):
            btn.configure(state=state)
        self.btn_out.configure(text="⬇ Kopieren nach …")
        self.btn_in.configure(text="⬆ Hierher kopieren …")
        self.btn_copy.configure(text="⧉ Kopieren nach …")
        self.note_var.set("Lokaler/NAS-Livemodus: Es wird der reale aktuelle Dateibaum angezeigt. Verändern/Löschen nur nach Sicherheitsabfrage; Laufwerkswurzeln bleiben geschützt.")

    def refresh(self):
        if self.busy: return
        target = self.current_target or self._target()
        if not target or target.get("kind") not in {"FILESYSTEM", "THIS_PC"}:
            return original_refresh(self)
        self.items.clear(); self.loaded_nodes.clear(); self.tree.delete(*self.tree.get_children())
        self._clear_preview(); self.current_target = target; self._update_actions()
        self._load_fs_root(target)

    def load_fs_root(self, target):
        if target.get("kind") == "THIS_PC":
            root = self._insert("", {"backend":"FILESYSTEM","node_type":"computer","name":"Dieser PC","is_dir":True,"root":True},
                                "💻 Dieser PC", ("Computer", "–", "–", "Aktuell erreichbare Laufwerke"), expandable=True)
        else:
            path = str(target.get("path") or "")
            reachable = Path(path).exists()
            detail = path if reachable else f"NICHT ERREICHBAR · {path}"
            root = self._insert("", {"backend":"FILESYSTEM","node_type":"folder","path":path,"name":target.get("name"),"is_dir":True,"root":True},
                                f"📁 {target.get('name')}", ("NAS / Dateisystem" if str(target.get('fs_kind')) == "NAS" else "Dateisystem", "–", "–", detail), expandable=reachable)
        self.tree.item(root, open=True); self._load_fs_children(root)

    def load_fs_children(self, iid):
        if iid in self.loaded_nodes or self.busy: return
        row = self.items.get(iid)
        if not row: return
        self._set_busy(True, "Dateisystem wird live gelesen …")
        def work():
            try:
                if row.get("node_type") == "computer":
                    data = [{"name": d, "path": d, "is_dir": True, "size": 0, "mtime": 0, "hidden": False, "system": False, "drive_root": True} for d in _windows_drives()]
                else:
                    data = _fs_list(row["path"])
                def done():
                    self._replace_children(iid)
                    for r in data:
                        r.update({"backend":"FILESYSTEM", "node_type":"folder" if r.get("is_dir") else "file"})
                        badges = []
                        if r.get("hidden"): badges.append("VERSTECKT")
                        if r.get("system"): badges.append("SYSTEM")
                        badge = ("👁 [" + "/".join(badges) + "] ") if badges else ""
                        icon = "💽" if r.get("drive_root") else ("📁" if r.get("is_dir") else "📄")
                        kind = "Laufwerk" if r.get("drive_root") else ("Ordner" if r.get("is_dir") else "Datei")
                        if badges: kind = " / ".join(badges).title() + " · " + kind
                        mod = datetime.fromtimestamp(r["mtime"]).strftime("%d.%m.%Y %H:%M") if r.get("mtime") else "–"
                        self._insert(iid, r, f"{badge}{icon} {r['name']}", (kind, "–" if r.get("is_dir") else storage_module.format_bytes(r.get("size") or 0), mod, r["path"]), expandable=bool(r.get("is_dir")))
                    self.loaded_nodes.add(iid); self._set_busy(False, f"{len(data)} reale Dateisystem-Einträge geladen")
                self.after(0, done)
            except Exception as exc:
                self.after(0, lambda e=exc: self._load_error(e))
        threading.Thread(target=work, daemon=True, name="pbv-fs-live-v1920").start()

    def tree_open(self, event=None):
        iid = self.tree.focus(); row = self.items.get(iid)
        if row and row.get("backend") == "FILESYSTEM": self._load_fs_children(iid); return
        return original_tree_open(self, event)

    def double_click(self, event=None):
        iid = self.tree.identify_row(event.y) if event else self.tree.focus(); row = self.items.get(iid)
        if row and row.get("backend") == "FILESYSTEM" and row.get("is_dir"):
            self.tree.item(iid, open=not bool(self.tree.item(iid, "open"))); self.tree.focus(iid); self._tree_open(); return
        return original_double_click(self, event)

    # B2: use bucket root, not only the configured backup prefix.
    def load_b2_root(self, target):
        root = self._insert("", {"backend":"B2","key":"","name":target["name"],"is_dir":True,"root":True},
                            f"🪣 {target['name']}", ("B2 Bucket – vollständig", "–", "–", "/"), expandable=True)
        self.tree.item(root, open=True); self._load_b2_children(root)

    original_b2_children = WindowClass._load_b2_children
    def load_b2_children(self, iid):
        # Let 1.9.19 perform the real listing, but preserve the bucket-root target.
        return original_b2_children(self, iid)

    # Database: project/server -> actual databases -> schemas -> relations -> columns.
    def dsn_for_database(self, database=None):
        return _dsn_database(self._dsn(), database)

    def load_db_root(self, target):
        ready = bool(target.get("ready", True))
        detail = str(target.get("project_ref") or target.get("database") or "")
        if not ready: detail = "ZUGANGSDATEN FEHLEN · " + detail
        root = self._insert("", {"backend":"POSTGRES","node_type":"server","name":target["name"],"is_dir":True,"configured_database":target.get("database") or ""},
                            f"🗄 {target['label']}", ("Datenbankserver / Projekt", "–", "–", detail), expandable=ready)
        if ready:
            self.tree.item(root, open=True); self._load_db_children(root)
        else:
            self.status_var.set("Datenbankprofil vorhanden, aber DSN/Zugangsdaten fehlen.")

    def load_db_children(self, iid):
        if iid in self.loaded_nodes or self.busy: return
        row = self.items.get(iid)
        if not row: return
        node_type = row.get("node_type")
        self._set_busy(True, "Reale Datenbankstruktur wird gelesen …")
        def work():
            try:
                if node_type == "server":
                    with psycopg.connect(self._dsn(), connect_timeout=10) as conn:
                        current_db, current_user = conn.execute("SELECT current_database(), current_user").fetchone()
                        data = [(d, "database", "") for d in _sql_databases(conn)]
                    configured = str(row.get("configured_database") or "")
                    mismatch = bool(configured and configured != str(current_db))
                else:
                    db = str(row.get("database") or "")
                    with psycopg.connect(self._dsn_for_database(db), connect_timeout=10) as conn:
                        if node_type == "database": data = [(s, "schema", "") for s in storage_module._sql_user_schemas(conn)]
                        elif node_type == "schema": data = [(n, "relation", t) for n, t in storage_module._sql_relations(conn, row["schema"])]
                        elif node_type == "relation": data = [(n, "column", f"{typ} · {'NULL' if null=='YES' else 'NOT NULL'}") for n, typ, null in storage_module._sql_columns(conn, row["schema"], row["table"])]
                        else: data = []
                    current_db = db; current_user = ""; mismatch = False
                def done():
                    self._replace_children(iid)
                    if node_type == "server":
                        configured = str(row.get("configured_database") or "")
                        detail = f"LIVE: {current_db} · Benutzer {current_user}"
                        if mismatch: detail = f"⚠ konfiguriert: {configured} · verbunden: {current_db} · Benutzer {current_user}"
                        vals = list(self.tree.item(iid, "values")); vals = (vals + ["–"]*4)[:4]; vals[3] = detail; self.tree.item(iid, values=vals)
                    for name, typ, detail in data:
                        if typ == "database":
                            item={"backend":"POSTGRES","node_type":"database","database":name,"name":name,"is_dir":True}; icon="🗃"; kind="Datenbank"; expandable=True; shown_detail="LIVE auf Server"
                        elif typ == "schema":
                            item={"backend":"POSTGRES","node_type":"schema","database":row["database"],"schema":name,"name":name,"is_dir":True}; icon="📂"; kind="Schema"; expandable=True; shown_detail=row["database"]
                        elif typ == "relation":
                            item={"backend":"POSTGRES","node_type":"relation","database":row["database"],"schema":row["schema"],"table":name,"name":name,"is_dir":True,"relation_type":detail}; icon="📋"; kind=detail.title(); expandable=True; shown_detail=f"{row['database']} · {row['schema']}"
                        else:
                            item={"backend":"POSTGRES","node_type":"column","database":row["database"],"schema":row["schema"],"table":row["table"],"name":name,"is_dir":False}; icon="▫"; kind="Spalte"; expandable=False; shown_detail=detail
                        self._insert(iid, item, f"{icon} {name}", (kind, "–", "–", shown_detail), expandable=expandable)
                    self.loaded_nodes.add(iid); self._set_busy(False, f"{len(data)} reale Datenbankobjekte geladen")
                self.after(0, done)
            except Exception as exc:
                self.after(0, lambda e=exc: self._load_error(e))
        threading.Thread(target=work, daemon=True, name="pbv-db-live-v1920").start()

    def preview_relation(self, row):
        schema = row["schema"]; table = row["table"]; database = row["database"]
        self._set_busy(True, f"Lese {database} · {schema}.{table} …")
        def work():
            try:
                with psycopg.connect(self._dsn_for_database(database), connect_timeout=10) as conn:
                    cur = conn.execute(sql.SQL("SELECT * FROM {}.{} LIMIT 200").format(sql.Identifier(schema), sql.Identifier(table)))
                    records = cur.fetchall(); cols = [d.name for d in cur.description]
                def done():
                    self._render_preview(schema, table, cols, records)
                    self.preview_info.set(f"{database} · {schema}.{table}: {len(records)} Datensätze angezeigt (max. 200)")
                self.after(0, done)
            except Exception as exc:
                self.after(0, lambda e=exc: self._load_error(e))
        threading.Thread(target=work, daemon=True).start()

    # Reuse the existing database actions but force them to the selected real database.
    def db_export(self):
        row = self._relation_selected()
        if not row: messagebox.showinfo("Export", "Bitte genau eine Tabelle oder View auswählen.", parent=self); return
        path = filedialog.asksaveasfilename(parent=self, title="Tabelle exportieren", defaultextension=".csv", filetypes=[("CSV","*.csv"),("JSON","*.json")], initialfile=f"{row['database']}_{row['schema']}_{row['table']}.csv")
        if not path: return
        def worker(report):
            with psycopg.connect(self._dsn_for_database(row["database"]), connect_timeout=10) as conn:
                cur=conn.execute(sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(row["schema"]),sql.Identifier(row["table"])))
                columns=[d.name for d in cur.description]; records=cur.fetchall()
            p=Path(path)
            if p.suffix.lower()==".json":
                p.write_text(json.dumps([{c:v for c,v in zip(columns,r)} for r in records],ensure_ascii=False,indent=2,default=str),encoding="utf-8")
                report(phase="Export abgeschlossen",files_done=len(records),files_total=len(records))
            else:
                import csv
                with p.open("w",newline="",encoding="utf-8-sig") as fh:
                    w=csv.writer(fh,delimiter=";"); w.writerow(columns)
                    for i,r in enumerate(records,1): w.writerow(r); report(phase="Export läuft",files_done=i,files_total=len(records))
        self._run("Datenbank Export", worker, f"{row['database']} · {row['schema']}.{row['table']} exportiert", refresh=False)

    # Patch only connection selection inside import by temporarily replacing _dsn.
    original_db_import = WindowClass._db_import
    def db_import(self):
        row = self._relation_selected()
        if not row: return original_db_import(self)
        original_dsn_method = self._dsn
        self._dsn = lambda: self._dsn_for_database(row["database"])
        try:
            return original_db_import(self)
        finally:
            self._dsn = original_dsn_method

    def fs_selected(self):
        return [r for r in self._selected() if r.get("backend")=="FILESYSTEM" and not r.get("root") and not r.get("drive_root")]

    def fs_target_dir(self):
        row = self._one_selected()
        if row and row.get("backend")=="FILESYSTEM" and row.get("is_dir"):
            return Path(str(row["path"]))
        target = self.current_target or {}
        if target.get("kind") == "FILESYSTEM": return Path(str(target.get("path") or ""))
        return None

    def confirm_fs(self, action, paths):
        names = "\n".join(str(p) for p in list(paths)[:6])
        more = "\n…" if len(paths) > 6 else ""
        return messagebox.askyesno(action, f"{action} wirklich ausführen?\n\n{names}{more}\n\nDie Aktion wirkt direkt auf PC/NAS.", parent=self, default="no")

    def fs_new_folder(self):
        dest = self._fs_target_dir()
        if not dest: messagebox.showinfo("Neuer Ordner","Bitte zuerst ein Laufwerk oder einen Ordner auswählen.",parent=self); return
        name = simpledialog.askstring("Neuer Ordner","Ordnername:",parent=self)
        if not name: return
        name = storage_module._safe_name(name); new = dest / name
        if not self._confirm_fs("Ordner anlegen", [new]): return
        self._run("Ordner anlegen", lambda report:(new.mkdir(parents=False,exist_ok=False), report(phase="Ordner angelegt",files_done=1,files_total=1)), f"Ordner {name} angelegt")

    def fs_copy(self):
        rows=self._fs_selected()
        if not rows: messagebox.showinfo("Kopieren","Bitte Datei(en) oder Ordner auswählen; Laufwerkswurzeln sind geschützt.",parent=self); return
        dest_name=filedialog.askdirectory(parent=self,title="Zielordner auswählen")
        if not dest_name: return
        dest=Path(dest_name)
        if not self._confirm_fs("Kopieren", [r["path"] for r in rows]): return
        def worker(report):
            files, dirs, total = _fs_manifest(rows); done=0
            for d in dirs:
                out=dest/d
                if out.exists() and not out.is_dir(): raise FileExistsError(f"Ziel existiert bereits: {out}")
                out.mkdir(parents=True,exist_ok=True)
            for i,(src,rel,size) in enumerate(files,1):
                out=dest/rel
                if out.exists(): raise FileExistsError(f"Ziel existiert bereits: {out}")
                out.parent.mkdir(parents=True,exist_ok=True)
                with src.open("rb") as inp, out.open("wb") as dst:
                    before=done
                    copied=storage_module._copy_stream(inp,dst,size,lambda n,_t:report(phase="Kopieren läuft",current_file=str(src),files_done=i-1,files_total=len(files),bytes_done=before+n,bytes_total=total)) if hasattr(storage_module,"_copy_stream") else shutil.copyfileobj(inp,dst)
                    if isinstance(copied,int): done+=copied
                    else: done+=size
                try: shutil.copystat(src,out)
                except Exception: pass
                report(phase="Kopieren läuft",current_file=str(src),files_done=i,files_total=len(files),bytes_done=done,bytes_total=total)
        self._run("PC/NAS kopieren",worker,f"{len(rows)} Auswahl(en) kopiert")

    def fs_import_here(self):
        dest=self._fs_target_dir()
        if not dest: messagebox.showinfo("Hierher kopieren","Bitte zuerst einen Zielordner auswählen.",parent=self); return
        names=filedialog.askopenfilenames(parent=self,title="Dateien auswählen")
        if not names: return
        targets=[dest/Path(n).name for n in names]
        if not self._confirm_fs("Hierher kopieren",targets): return
        def worker(report):
            total=sum(Path(n).stat().st_size for n in names); done=0
            for i,n in enumerate(names,1):
                src=Path(n); out=dest/src.name
                if out.exists(): raise FileExistsError(f"Ziel existiert bereits: {out}")
                size=src.stat().st_size; before=done
                with src.open("rb") as inp,out.open("wb") as dst:
                    while True:
                        chunk=inp.read(256*1024)
                        if not chunk: break
                        dst.write(chunk); done+=len(chunk); report(phase="Kopieren läuft",current_file=str(src),files_done=i-1,files_total=len(names),bytes_done=done,bytes_total=total)
                shutil.copystat(src,out); report(phase="Kopieren läuft",current_file=str(src),files_done=i,files_total=len(names),bytes_done=done,bytes_total=total)
        self._run("Dateien hierher kopieren",worker,f"{len(names)} Datei(en) kopiert")

    def fs_move(self):
        rows=self._fs_selected()
        if not rows: return
        dest_name=filedialog.askdirectory(parent=self,title="Zielordner auswählen")
        if not dest_name: return
        dest=Path(dest_name)
        if not self._confirm_fs("Verschieben",[r["path"] for r in rows]): return
        def worker(report):
            for i,r in enumerate(rows,1):
                src=Path(r["path"]); out=dest/src.name
                if out.exists(): raise FileExistsError(f"Ziel existiert bereits: {out}")
                shutil.move(str(src),str(out)); report(phase="Verschieben läuft",current_file=str(src),files_done=i,files_total=len(rows))
        self._run("PC/NAS verschieben",worker,f"{len(rows)} Eintrag/Einträge verschoben")

    def fs_rename(self):
        row=self._one_selected()
        if not row or row.get("backend")!="FILESYSTEM" or row.get("root") or row.get("drive_root"): return
        name=simpledialog.askstring("Umbenennen","Neuer Name:",initialvalue=row["name"],parent=self)
        if not name: return
        name=storage_module._safe_name(name); src=Path(row["path"]); dest=src.with_name(name)
        if dest.exists(): messagebox.showerror("Umbenennen",f"Ziel existiert bereits:\n{dest}",parent=self); return
        if not self._confirm_fs("Umbenennen",[src,dest]): return
        self._run("PC/NAS umbenennen",lambda report:(src.rename(dest),report(phase="Umbenannt",files_done=1,files_total=1)),f"{row['name']} umbenannt")

    def fs_delete(self):
        rows=self._fs_selected()
        if not rows: return
        if not self._confirm_fs("DAUERHAFT LÖSCHEN",[r["path"] for r in rows]): return
        def worker(report):
            for i,r in enumerate(rows,1):
                p=Path(r["path"])
                if p.is_dir(): shutil.rmtree(p)
                else: p.unlink()
                report(phase="Löschen läuft",current_file=str(p),files_done=i,files_total=len(rows))
        self._run("PC/NAS löschen",worker,f"{len(rows)} Eintrag/Einträge gelöscht")

    def new_folder(self):
        if (self.current_target or {}).get("kind") in {"FILESYSTEM","THIS_PC"}: return self._fs_new_folder()
        return original_new(self)
    def download(self):
        if (self.current_target or {}).get("kind") in {"FILESYSTEM","THIS_PC"}: return self._fs_copy()
        return original_download(self)
    def upload(self):
        if (self.current_target or {}).get("kind") in {"FILESYSTEM","THIS_PC"}: return self._fs_import_here()
        return original_upload(self)
    def copy(self):
        if (self.current_target or {}).get("kind") in {"FILESYSTEM","THIS_PC"}: return self._fs_copy()
        return original_copy(self)
    def move(self):
        if (self.current_target or {}).get("kind") in {"FILESYSTEM","THIS_PC"}: return self._fs_move()
        return original_move(self)
    def rename(self):
        if (self.current_target or {}).get("kind") in {"FILESYSTEM","THIS_PC"}: return self._fs_rename()
        return original_rename(self)
    def delete(self):
        if (self.current_target or {}).get("kind") in {"FILESYSTEM","THIS_PC"}: return self._fs_delete()
        return original_delete(self)

    WindowClass._update_actions = update_actions
    WindowClass.refresh = refresh
    WindowClass._load_fs_root = load_fs_root
    WindowClass._load_fs_children = load_fs_children
    WindowClass._tree_open = tree_open
    WindowClass._double_click = double_click
    WindowClass._load_b2_root = load_b2_root
    WindowClass._load_b2_children = load_b2_children
    WindowClass._dsn_for_database = dsn_for_database
    WindowClass._load_db_root = load_db_root
    WindowClass._load_db_children = load_db_children
    WindowClass._preview_relation = preview_relation
    WindowClass._db_export = db_export
    WindowClass._db_import = db_import
    WindowClass._fs_selected = fs_selected
    WindowClass._fs_target_dir = fs_target_dir
    WindowClass._confirm_fs = confirm_fs
    WindowClass._fs_new_folder = fs_new_folder
    WindowClass._fs_copy = fs_copy
    WindowClass._fs_import_here = fs_import_here
    WindowClass._fs_move = fs_move
    WindowClass._fs_rename = fs_rename
    WindowClass._fs_delete = fs_delete
    WindowClass.new_folder = new_folder
    WindowClass.download_export = download
    WindowClass.upload_import = upload
    WindowClass.copy_selected = copy
    WindowClass.move_selected = move
    WindowClass.rename_selected = rename
    WindowClass.delete_selected = delete
