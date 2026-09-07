from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from crypto_box import decrypt_bytes, decrypt_text, sha256_bytes
from storage_v180 import VAULT_DIR, _targets, _target


def _job_dir(target: dict) -> Path:
    return Path(str(target.get("path") or "")) / VAULT_DIR / "jobs"


def _chunk_dir(target: dict) -> Path:
    return Path(str(target.get("path") or "")) / VAULT_DIR / "chunks"


def _parse_dt(value: str | None):
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def list_filesystem_jobs(target: dict) -> list[dict]:
    out = []
    jobs = _job_dir(target)
    if not jobs.exists():
        return out
    for p in jobs.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if doc.get("format") != "PCBV-FS-1":
                continue
            doc["_manifest_path"] = str(p)
            out.append(doc)
        except Exception:
            continue
    out.sort(key=lambda x: _parse_dt(x.get("created_at")), reverse=True)
    return out


def preflight_filesystem_target(target: dict, source_paths=None, expected_bytes: int = 0) -> dict:
    path = Path(str(target.get("path") or ""))
    checks = []
    def add(code, ok, detail): checks.append({"code": code, "ok": bool(ok), "detail": detail})
    add("TARGET_EXISTS", path.exists(), f"Ziel: {path}")
    if not path.exists():
        return {"ok": False, "checks": checks, "free_bytes": 0}
    try:
        usage = shutil.disk_usage(path)
        free = int(usage.free)
        add("FREE_SPACE", free >= max(1, int(expected_bytes * 1.10)), f"Frei: {free} B; erwartet inkl. Reserve: {int(expected_bytes * 1.10)} B")
    except Exception as e:
        free = 0; add("FREE_SPACE", False, str(e))
    try:
        vault = path / VAULT_DIR
        vault.mkdir(parents=True, exist_ok=True)
        probe = vault / f".preflight-{os.getpid()}.tmp"
        probe.write_bytes(b"PCBV-PREFLIGHT"); data = probe.read_bytes(); probe.unlink(missing_ok=True)
        add("READ_WRITE_DELETE", data == b"PCBV-PREFLIGHT", "Schreiben/Lesen/Löschen erfolgreich")
    except Exception as e:
        add("READ_WRITE_DELETE", False, str(e))
    try:
        target_resolved = path.resolve()
        bad = []
        for raw in source_paths or []:
            p = Path(raw)
            try:
                r = p.resolve()
                if r == target_resolved or target_resolved in r.parents or r in target_resolved.parents:
                    bad.append(str(p))
            except Exception:
                pass
        add("SOURCE_TARGET_SEPARATION", not bad, "Quelle und Ziel sauber getrennt" if not bad else "Kritische Überlappung: " + ", ".join(bad[:3]))
    except Exception as e:
        add("SOURCE_TARGET_SEPARATION", False, str(e))
    return {"ok": all(x["ok"] for x in checks), "checks": checks, "free_bytes": free}


def _load_manifest(job_or_path) -> dict:
    if isinstance(job_or_path, dict):
        return job_or_path
    return json.loads(Path(job_or_path).read_text(encoding="utf-8"))


def verify_filesystem_job(target: dict, job_or_path, key_b64: str, full: bool = False) -> dict:
    doc = _load_manifest(job_or_path)
    chunks_root = _chunk_dir(target)
    checked_chunks = 0
    checked_files = 0
    errors = []
    for frec in doc.get("files") or []:
        file_hash = hashlib.sha256()
        for cref in frec.get("chunks") or []:
            rel = Path(str(cref.get("file") or ""))
            p = chunks_root / rel
            if not p.exists():
                errors.append(f"Chunk fehlt: {rel}"); continue
            blob = p.read_bytes()
            if len(blob) < 13:
                errors.append(f"Chunk unvollständig: {rel}"); continue
            nonce, cipher = blob[:12], blob[12:]
            if sha256_bytes(cipher) != str(cref.get("cipher_sha256") or ""):
                errors.append(f"Cipher-Prüfsumme falsch: {rel}"); continue
            checked_chunks += 1
            if full:
                try:
                    aad = f"{frec.get('sha256')}:{int(cref.get('no') or 0)}".encode("ascii")
                    plain = decrypt_bytes(key_b64, nonce, cipher, aad)
                    file_hash.update(plain)
                except Exception as e:
                    errors.append(f"Entschlüsselung fehlgeschlagen {rel}: {e}")
        if full and not errors and file_hash.hexdigest() != str(frec.get("sha256") or ""):
            errors.append("Datei-SHA-256 stimmt nach Rekonstruktion nicht")
        checked_files += 1
    return {"result": "PASS" if not errors else "FAIL", "errors": errors, "checked_files": checked_files, "checked_chunks": checked_chunks, "mode": "FULL" if full else "QUICK"}


def restore_filesystem_job(target: dict, job_or_path, key_b64: str, destination: str | Path, progress=None, selected_indexes=None) -> dict:
    doc = _load_manifest(job_or_path)
    dest = Path(destination); dest.mkdir(parents=True, exist_ok=True)
    chunks_root = _chunk_dir(target)
    files = list(doc.get("files") or [])
    indexes = list(selected_indexes) if selected_indexes is not None else list(range(len(files)))
    restored = 0; errors = []
    for pos, idx in enumerate(indexes, start=1):
        try:
            frec = files[idx]
            parent = decrypt_text(key_b64, str(frec.get("path") or ""))
            name = decrypt_text(key_b64, str(frec.get("name") or ""))
            drive, tail = os.path.splitdrive(parent)
            clean_parts = [x for x in Path(tail).parts if x not in ("/", "\\", ".", "..")]
            if drive:
                clean_parts.insert(0, drive.replace(":", ""))
            out = dest.joinpath(*clean_parts, name)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(out.suffix + ".part")
            h = hashlib.sha256()
            with tmp.open("wb") as fh:
                for cref in frec.get("chunks") or []:
                    p = chunks_root / Path(str(cref.get("file") or ""))
                    blob = p.read_bytes(); nonce, cipher = blob[:12], blob[12:]
                    if sha256_bytes(cipher) != str(cref.get("cipher_sha256") or ""):
                        raise ValueError(f"Chunk-Prüfsumme fehlerhaft: {p.name}")
                    aad = f"{frec.get('sha256')}:{int(cref.get('no') or 0)}".encode("ascii")
                    plain = decrypt_bytes(key_b64, nonce, cipher, aad)
                    fh.write(plain); h.update(plain)
            if h.hexdigest() != str(frec.get("sha256") or ""):
                tmp.unlink(missing_ok=True); raise ValueError("SHA-256 der wiederhergestellten Datei stimmt nicht")
            if out.exists():
                stem, suffix = out.stem, out.suffix; n = 1
                candidate = out
                while candidate.exists():
                    candidate = out.with_name(f"{stem}_restore_{n}{suffix}"); n += 1
                out = candidate
            tmp.replace(out); restored += 1
            if progress: progress(pos, len(indexes), name)
        except Exception as e:
            errors.append(str(e))
    return {"result": "PASS" if not errors else ("WARN" if restored else "FAIL"), "restored": restored, "errors": errors}


def filesystem_restore_selftest(target: dict, key_b64: str, max_kb: int = 256) -> dict:
    jobs = list_filesystem_jobs(target)
    if not jobs:
        return {"status": "WARN", "details": "Noch kein Dateisystem-Backup vorhanden."}
    job = jobs[0]
    files = list(job.get("files") or [])
    if not files:
        return {"status": "WARN", "details": "Letztes Backup enthält keine Dateien."}
    limit = max(1, int(max_kb)) * 1024
    idx = next((i for i, f in enumerate(files) if int(f.get("original_size") or 0) <= limit), 0)
    with tempfile.TemporaryDirectory(prefix="pcbv-restore-test-") as td:
        result = restore_filesystem_job(target, job, key_b64, td, selected_indexes=[idx])
        return {"status": "PASS" if result.get("result") == "PASS" else "FAIL", "details": "Offline-Restore-Probe erfolgreich" if result.get("result") == "PASS" else "; ".join(result.get("errors") or [])[:500]}


def prune_filesystem_retention(target: dict, plan_name: str | None, keep_last: int = 10, retention_days: int = 90) -> dict:
    keep_last = max(1, int(keep_last or 10)); retention_days = max(1, int(retention_days or 90))
    jobs = list_filesystem_jobs(target)
    if plan_name:
        candidates = [j for j in jobs if str(j.get("plan_name") or "") == str(plan_name)]
    else:
        candidates = jobs
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    keep_ids = set()
    for i, job in enumerate(candidates):
        if i < keep_last or _parse_dt(job.get("created_at")) >= cutoff:
            keep_ids.add(str(job.get("job_id") or ""))
    deleted_manifests = 0
    for job in candidates:
        jid = str(job.get("job_id") or "")
        if jid and jid not in keep_ids:
            try: Path(job["_manifest_path"]).unlink(missing_ok=True); deleted_manifests += 1
            except Exception: pass
    remaining = list_filesystem_jobs(target)
    referenced = set()
    for job in remaining:
        for frec in job.get("files") or []:
            for cref in frec.get("chunks") or []:
                referenced.add(str(Path(str(cref.get("file") or ""))).replace("\\", "/"))
    deleted_chunks = 0
    root = _chunk_dir(target)
    if root.exists():
        for p in root.rglob("*.bin"):
            rel = str(p.relative_to(root)).replace("\\", "/")
            if rel not in referenced:
                try: p.unlink(); deleted_chunks += 1
                except Exception: pass
    return {"deleted_manifests": deleted_manifests, "deleted_chunks": deleted_chunks, "remaining_jobs": len(remaining)}


def run_filesystem_lifecycle(store, plan: dict, target: dict, result: dict, key_b64: str) -> dict:
    verify_enabled = bool(plan.get("auto_verify", store.data.get("auto_quick_verify_after_backup", True)))
    restore_test_enabled = bool(plan.get("restore_test", store.data.get("restore_selftest_after_backup", True)))
    keep_last = int(plan.get("keep_last_versions", store.data.get("keep_last_versions", 10)) or 10)
    retention_days = int(plan.get("retention_days", store.data.get("retention_days", 90)) or 90)
    out = {"verification": {"status": "DISABLED"}, "selftest": {"status": "DISABLED"}, "retention": {}}
    job = next((j for j in list_filesystem_jobs(target) if str(j.get("job_id")) == str(result.get("job_id"))), None)
    if verify_enabled and job:
        vr = verify_filesystem_job(target, job, key_b64, full=False)
        out["verification"] = {"status": vr["result"], **vr}
    if restore_test_enabled:
        out["selftest"] = filesystem_restore_selftest(target, key_b64, int(store.data.get("restore_selftest_max_kb", 256)))
    out["retention"] = prune_filesystem_retention(target, plan.get("name"), keep_last, retention_days)
    result.update(out)
    return result


class OfflineRestoreWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app); self.app=app; self.store=app.store
        self.title("Offline-Rücksicherung – USB / NAS"); self.geometry("960x620"); self.minsize(860,560); self.transient(app)
        self.target_var=tk.StringVar(); self.status=tk.StringVar(value="Backup-Ziel auswählen.")
        box=ttk.Frame(self,padding=12); box.pack(fill="both",expand=True)
        ttk.Label(box,text="Offline-Rücksicherung",font=("Segoe UI",17,"bold")).pack(anchor="w")
        ttk.Label(box,text="Wiederherstellung direkt vom USB-/Festplatten-/NAS-Tresor – Neon und Internet sind dafür nicht erforderlich.",wraplength=900).pack(anchor="w",pady=(3,10))
        top=ttk.Frame(box); top.pack(fill="x")
        self.combo=ttk.Combobox(top,textvariable=self.target_var,state="readonly",values=[t.get("name") for t in _targets(self.store)],width=42); self.combo.pack(side="left")
        ttk.Button(top,text="↻ Laden",command=self.load).pack(side="left",padx=6)
        ttk.Button(top,text="📁 Zielverwaltung",command=lambda:__import__('storage_v180').add_or_select_target(self.app)).pack(side="left")
        self.tree=ttk.Treeview(box,columns=("date","plan","files","size"),show="headings",height=16)
        for c,t,w in (("date","Backup-Zeit",180),("plan","Job",300),("files","Dateien",100),("size","Daten",150)):
            self.tree.heading(c,text=t); self.tree.column(c,width=w,anchor="w")
        self.tree.pack(fill="both",expand=True,pady=10)
        ttk.Label(box,textvariable=self.status).pack(anchor="w")
        row=ttk.Frame(box); row.pack(fill="x",pady=(8,0))
        ttk.Button(row,text="Voll prüfen",command=lambda:self.verify(True)).pack(side="left")
        ttk.Button(row,text="Schnell prüfen",command=lambda:self.verify(False)).pack(side="left",padx=6)
        ttk.Button(row,text="▶ Ausgewählten Stand wiederherstellen",command=self.restore).pack(side="right")
        self.jobs=[]; self.combo.bind("<<ComboboxSelected>>",lambda e:self.load())
        if self.combo.cget("values"):
            self.combo.current(0); self.load()

    def current_target(self):
        name=self.target_var.get(); return next((t for t in _targets(self.store) if t.get("name")==name),None)
    def current_job(self):
        sel=self.tree.selection();
        if not sel:return None
        try:return self.jobs[int(sel[0])]
        except Exception:return None
    def load(self):
        t=self.current_target(); self.tree.delete(*self.tree.get_children()); self.jobs=[]
        if not t:return
        self.jobs=list_filesystem_jobs(t)
        for i,j in enumerate(self.jobs):
            dt=_parse_dt(j.get("created_at")); size=int(j.get("original_bytes") or 0)
            self.tree.insert("","end",iid=str(i),values=(dt.astimezone().strftime("%d.%m.%Y %H:%M"),j.get("plan_name") or "Manuelles Backup",j.get("file_count") or len(j.get("files") or []),f"{size/1024/1024:.1f} MB"))
        self.status.set(f"{len(self.jobs)} Backup-Stände gefunden.")
    def verify(self,full):
        t=self.current_target(); j=self.current_job()
        if not t or not j:messagebox.showwarning("Offline-Restore","Bitte zuerst einen Backup-Stand auswählen.",parent=self);return
        self.status.set("Prüfung läuft …"); self.update_idletasks()
        r=verify_filesystem_job(t,j,self.app.master_key(),full=full); self.status.set(f"{r['result']} – {r['checked_files']} Dateien / {r['checked_chunks']} Chunks geprüft")
        (messagebox.showinfo if r['result']=="PASS" else messagebox.showerror)("Backup-Prüfung",self.status.get()+("" if not r['errors'] else "\n\n"+"\n".join(r['errors'][:8])),parent=self)
    def restore(self):
        t=self.current_target(); j=self.current_job()
        if not t or not j:messagebox.showwarning("Offline-Restore","Bitte einen Backup-Stand auswählen.",parent=self);return
        dest=filedialog.askdirectory(parent=self,title="Zielordner für Rücksicherung auswählen")
        if not dest:return
        self.status.set("Rücksicherung läuft …"); self.update_idletasks()
        r=restore_filesystem_job(t,j,self.app.master_key(),dest,progress=lambda d,n,m:self.status.set(f"Rücksicherung {d}/{n}: {m}"))
        self.status.set(f"Fertig: {r['restored']} Datei(en), {len(r['errors'])} Fehler")
        (messagebox.showinfo if not r['errors'] else messagebox.showwarning)("Rücksicherung",self.status.get(),parent=self)


def open_restore_route(app):
    win=tk.Toplevel(app); win.title("Rücksicherung"); win.geometry("620x300"); win.transient(app); win.grab_set()
    box=ttk.Frame(win,padding=18); box.pack(fill="both",expand=True)
    ttk.Label(box,text="Wo liegt das Backup?",font=("Segoe UI",16,"bold")).pack(anchor="w")
    ttk.Label(box,text="Wählen Sie den einfachen passenden Weg. Beide Varianten prüfen die Daten bei der Wiederherstellung.",wraplength=570).pack(anchor="w",pady=(5,14))
    def online(): win.destroy(); app.open_explorer()
    def offline(): win.destroy(); OfflineRestoreWindow(app)
    ttk.Button(box,text="☁ Im normalen Backup-Katalog (Neon / B2)",command=online).pack(fill="x",pady=5,ipady=7)
    ttk.Button(box,text="💾 Direkt von USB / externer Platte / NAS – auch offline",command=offline).pack(fill="x",pady=5,ipady=7)
    ttk.Button(box,text="Abbrechen",command=win.destroy).pack(anchor="e",pady=(12,0))


def filesystem_tuev_checks(store, key_b64: str) -> list[tuple[str,str,str,str]]:
    checks=[]
    targets=_targets(store)
    if not targets:
        return [("FS-001","Dateisystem-Ziele","WARN","Noch kein USB-/NAS-Ziel eingerichtet")]
    for i,t in enumerate(targets,1):
        name=t.get("name") or f"Ziel {i}"; path=t.get("path") or ""
        pre=preflight_filesystem_target(t,[],0)
        checks.append((f"FS-{i:03d}",f"Ziel {name}","PASS" if pre.get("ok") else "WARN",path if pre.get("ok") else "; ".join(x['detail'] for x in pre['checks'] if not x['ok'])[:500]))
        jobs=list_filesystem_jobs(t)
        if jobs:
            vr=verify_filesystem_job(t,jobs[0],key_b64,full=False)
            checks.append((f"FSV-{i:03d}",f"Letzter Stand {name}",vr['result'],f"{vr['checked_files']} Dateien / {vr['checked_chunks']} Chunks"+("" if not vr['errors'] else " · "+vr['errors'][0][:250])))
            st=filesystem_restore_selftest(t,key_b64,int(store.data.get("restore_selftest_max_kb",256)))
            checks.append((f"FSR-{i:03d}",f"Restore-Probe {name}",st['status'],st['details']))
        else:
            checks.append((f"FSV-{i:03d}",f"Letzter Stand {name}","WARN","Noch kein Backup-Stand vorhanden"))
    return checks
