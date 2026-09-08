from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from archive_restore_v198 import restore_archived_job
from crypto_box import decrypt_text
from job_archive_v198 import (
    archive_file_count, archive_path, get_job, index_hidrive_job, list_job_files, list_jobs,
    refresh_archive, refresh_archive_full,
)
from restore_progress_v1910 import RestoreProgressDialog
from unified_reporting_v193 import human_size


def _fmt_dt(value) -> str:
    if not value:
        return "–"
    try:
        return datetime.fromisoformat(str(value)).astimezone().strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return str(value)


def _refresh_archive_background(app, recent_jobs_func, exact_job_id=None):
    """Best-effort metadata sync; never blocks or changes a backup result."""
    try:
        refresh_archive(app.store, app.active_dsn(), recent_jobs_func)
        if exact_job_id:
            index_hidrive_job(app, str(exact_job_id))
    except Exception:
        pass


class JobFilesWindow(tk.Toplevel):
    def __init__(self, app, job_id: str):
        super().__init__(app)
        self.app = app; self.job_id = str(job_id)
        self.title(f"PC Backup Vault – Dateien in Job {self.job_id}")
        self.geometry("1180x700"); self.minsize(850, 520); self.transient(app)
        head = ttk.Frame(self, padding=12); head.pack(fill="x")
        ttk.Label(head, text=f"Dateikatalog · Job {self.job_id}", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Button(head, text="Schließen", command=self.destroy).pack(side="right")
        ttk.Label(head, text="Namen/Pfade werden nur zur Anzeige mit dem lokalen Wiederherstellungsschlüssel entschlüsselt.").pack(side="left", padx=(16,0))
        box = ttk.Frame(self, padding=(12,0,12,12)); box.pack(fill="both", expand=True)
        box.rowconfigure(0, weight=1); box.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(box, columns=("name","path","size","sha","backend"), show="headings")
        for c,t,w in (("name","Dateiname",260),("path","Ordner",430),("size","Größe",90),("sha","SHA-256",270),("backend","Speicher",120)):
            self.tree.heading(c,text=t); self.tree.column(c,width=w,anchor="w")
        y=ttk.Scrollbar(box,orient="vertical",command=self.tree.yview); x=ttk.Scrollbar(box,orient="horizontal",command=self.tree.xview)
        self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        self.tree.grid(row=0,column=0,sticky="nsew"); y.grid(row=0,column=1,sticky="ns"); x.grid(row=1,column=0,sticky="ew")
        key = app.master_key()
        for row in list_job_files(app.store, self.job_id):
            name = str(row.get("name_cipher") or "")
            path = str(row.get("path_cipher") or "")
            if key:
                try: name = decrypt_text(key, name)
                except Exception: pass
                try: path = decrypt_text(key, path)
                except Exception: pass
            self.tree.insert("","end",values=(name or "–", path or "–", human_size(row.get("original_size")), row.get("sha256") or "–", row.get("backend") or "–"))


class JobArchiveWindow(tk.Toplevel):
    def __init__(self, app, recent_jobs_func):
        super().__init__(app)
        self.app = app; self.recent_jobs_func = recent_jobs_func
        self._restore_progress = None
        self.title("PC Backup Vault – Job-Archiv"); self.geometry("1460x760"); self.minsize(1100,620); self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        head=ttk.Frame(self,padding=(14,12,14,8)); head.pack(fill="x")
        ttk.Label(head,text="Job-Archiv",font=("Segoe UI",20,"bold")).pack(side="left")
        ttk.Label(head,text="Alle Sicherungsläufe – B2, Neon, HiDrive, NAS und Dateispeicher",font=("Segoe UI",10)).pack(side="left",padx=(16,0))
        ttk.Button(head,text="Aktualisieren",command=self.refresh).pack(side="right")
        ttk.Button(head,text="Schließen",command=self.destroy).pack(side="right",padx=(0,6))
        controls=ttk.Frame(self,padding=(14,0,14,8)); controls.pack(fill="x")
        ttk.Label(controls,text="Suche:").pack(side="left"); self.search_var=tk.StringVar()
        entry=ttk.Entry(controls,textvariable=self.search_var,width=42); entry.pack(side="left",fill="x",expand=True,padx=(6,12))
        self.info=ttk.Label(controls,text=""); self.info.pack(side="right")
        box=ttk.Frame(self,padding=(14,0,14,8)); box.pack(fill="both",expand=True); box.columnconfigure(0,weight=1); box.rowconfigure(0,weight=1)
        columns=("date","job","status","source","target","files","size","verify","restore")
        self.tree=ttk.Treeview(box,columns=columns,show="headings",selectmode="browse")
        for c,t,w in (("date","Datum / Uhrzeit",145),("job","Job-ID",235),("status","Status",80),("source","Quelle",260),("target","Ziel",210),("files","Dateien",70),("size","Datenmenge",95),("verify","Prüfung",145),("restore","Restore",105)):
            self.tree.heading(c,text=t); self.tree.column(c,width=w,minwidth=60,anchor="w")
        sy=ttk.Scrollbar(box,orient="vertical",command=self.tree.yview); sx=ttk.Scrollbar(box,orient="horizontal",command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set); self.tree.grid(row=0,column=0,sticky="nsew"); sy.grid(row=0,column=1,sticky="ns"); sx.grid(row=1,column=0,sticky="ew")
        self.tree.bind("<Double-1>",lambda _e:self.restore_selected())
        foot=ttk.Frame(self,padding=(14,8,14,14)); foot.pack(fill="x")
        self.details=ttk.Label(foot,text="Job auswählen. Doppelklick startet die Wiederherstellung.",wraplength=800,justify="left"); self.details.pack(side="left",fill="x",expand=True)
        ttk.Button(foot,text="📄 Dateien anzeigen",command=self.show_files).pack(side="right",padx=(6,0))
        self.restore_btn=ttk.Button(foot,text="♻ Ausgewählten Job wiederherstellen",command=self.restore_selected); self.restore_btn.pack(side="right")
        self.tree.bind("<<TreeviewSelect>>",lambda _e:self._show_details()); self.search_var.trace_add("write",lambda *_:self._render())
        self.rows=[]; self.refresh(); entry.focus_set()

    def refresh(self):
        counts=refresh_archive(self.app.store,self.app.active_dsn(),self.recent_jobs_func)
        self.rows=list_jobs(self.app.store); self._render()
        self.info.config(text=f"Archiv: {counts['total']} Job(s) · {archive_file_count(self.app.store)} Dateiindex-Einträge")
        def remote():
            try:
                refresh_archive_full(self.app,self.recent_jobs_func,include_hidrive=True)
                self.after(0,self._remote_done)
            except Exception:
                pass
        threading.Thread(target=remote,name="pbv-job-archive-hidrive-index",daemon=True).start()

    def _remote_done(self):
        if not self.winfo_exists(): return
        self.rows=list_jobs(self.app.store); self._render()
        self.info.config(text=f"Archiv: {len(self.rows)} Job(s) · {archive_file_count(self.app.store)} Dateiindex-Einträge · HiDrive-Katalog aktualisiert")
        self._show_details()

    def _render(self):
        q=self.search_var.get().strip().casefold(); self.tree.delete(*self.tree.get_children()); shown=0
        for r in self.rows:
            hay=" ".join(str(r.get(k) or "") for k in ("job_id","source_label","target_label","status","backend_label","plan_name")).casefold()
            if q and q not in hay: continue
            jid=str(r.get("job_id")); self.tree.insert("","end",iid=jid,values=(_fmt_dt(r.get("started_at") or r.get("reported_at")),jid,r.get("status") or "–",r.get("source_label") or "–",r.get("target_label") or "–",int(r.get("file_count") or 0),human_size(r.get("original_bytes")),r.get("verification_status") or "–",r.get("restore_status") or "noch nicht")); shown+=1
        self.info.config(text=f"{shown} von {len(self.rows)} Job(s) · {archive_file_count(self.app.store)} Dateiindex-Einträge")

    def _selected_job_id(self):
        sel=self.tree.selection(); return str(sel[0]) if sel else None

    def _show_details(self):
        jid=self._selected_job_id()
        if not jid: return
        r=get_job(self.app.store,jid) or {}; indexed=archive_file_count(self.app.store,jid)
        self.details.config(text=f"{r.get('source_to_target') or '–'} | Status {r.get('status') or '–'} | {int(r.get('file_count') or 0)} Dateien · {human_size(r.get('original_bytes'))} | Dateiindex: {indexed} | Verifizierung: {r.get('verification_status') or '–'}")

    def show_files(self):
        jid=self._selected_job_id()
        if not jid: messagebox.showinfo("Job-Archiv","Bitte zuerst einen Job auswählen.",parent=self); return
        if archive_file_count(self.app.store,jid)==0:
            messagebox.showinfo("Dateikatalog","Für diesen Job ist der Dateikatalog noch nicht verfügbar. Bei HiDrive wird das Manifest im Hintergrund eingelesen; bitte danach erneut versuchen.",parent=self); return
        JobFilesWindow(self.app,jid)

    def restore_selected(self):
        if self._restore_progress is not None:
            try:
                if self._restore_progress.winfo_exists():
                    self._restore_progress.lift(); self._restore_progress.focus_force(); return
            except Exception:
                self._restore_progress = None
        jid=self._selected_job_id()
        if not jid: messagebox.showinfo("Job-Archiv","Bitte zuerst einen Job auswählen.",parent=self); return
        job=get_job(self.app.store,jid) or {}; kind=str((job.get("locator") or {}).get("kind") or "").upper(); backend=str(job.get("backend_label") or "").lower()
        if kind=="NEON" or backend in {"neon","backblaze b2"}:
            self.app._archive_restore_job_id=jid; self.app.open_restore_assistant(); return
        destination=filedialog.askdirectory(parent=self,title=f"Wiederherstellungsziel für Job {jid}")
        if not destination: return
        self.details.config(text=f"Wiederherstellung von {jid} läuft …")
        self.restore_btn.configure(state="disabled")
        progress=RestoreProgressDialog(self,jid,int(job.get("file_count") or 0),int(job.get("original_bytes") or 0))
        self._restore_progress=progress
        try: progress.grab_set()
        except Exception: pass

        def on_progress(info):
            data=dict(info or {})
            try: self.after(0,lambda d=data: progress.update_progress(d))
            except Exception: pass

        def work():
            try:
                result=restore_archived_job(self.app,jid,Path(destination),progress=on_progress)
                self.after(0,lambda:self._restore_done(jid,result,progress))
            except RuntimeError as exc:
                if str(exc)=="DATABASE_RESTORE": self.after(0,lambda:self._database_restore(jid,progress))
                else: self.after(0,lambda e=exc:self._restore_failed(jid,e,progress))
            except Exception as exc: self.after(0,lambda e=exc:self._restore_failed(jid,e,progress))
        threading.Thread(target=work,name=f"pbv-archive-restore-{jid[:8]}",daemon=True).start()

    def _database_restore(self,jid,progress=None):
        if progress:
            try: progress.destroy()
            except Exception: pass
        self._restore_progress=None; self.restore_btn.configure(state="normal")
        self.app._archive_restore_job_id=jid; self.app.open_restore_assistant()

    def _restore_done(self,jid,result,progress=None):
        if progress:
            try:
                progress.finish(True,f"{result['files']} Datei(en) erfolgreich wiederhergestellt · SHA-256 PASS")
                progress.grab_release()
            except Exception: pass
        self.refresh(); self.restore_btn.configure(state="normal")
        messagebox.showinfo("Wiederherstellung erfolgreich",f"Job {jid} wurde wiederhergestellt.\n\n{result['files']} Datei(en) · {human_size(result['bytes'])}\nZiel: {result['destination']}\n\nSHA-256-Prüfung: PASS",parent=progress if progress and progress.winfo_exists() else self)
        if progress:
            try: progress.destroy()
            except Exception: pass
        self._restore_progress=None

    def _restore_failed(self,jid,exc,progress=None):
        if progress:
            try:
                progress.finish(False,str(exc)); progress.grab_release()
            except Exception: pass
        self.refresh(); self.restore_btn.configure(state="normal")
        messagebox.showerror("Wiederherstellung fehlgeschlagen",f"Job {jid}\n\n{exc}",parent=progress if progress and progress.winfo_exists() else self)
        if progress:
            try: progress.destroy()
            except Exception: pass
        self._restore_progress=None


def apply_job_archive_v198(AppClass, RestoreAssistantClass, WorkbenchClass, recent_jobs_func):
    if getattr(AppClass,"_job_archive_v198",False): return
    original_app_build=AppClass._build
    def app_build(self):
        original_app_build(self); self.open_job_archive=lambda:JobArchiveWindow(self,recent_jobs_func)
        try:
            parent=self.btn_backup.master; ttk.Button(parent,text="🗄 Job-Archiv",command=self.open_job_archive).pack(side="left",padx=(0,8),before=self.btn_backup)
        except Exception: pass
        try: self.after(1200,lambda:threading.Thread(target=_refresh_archive_background,args=(self,recent_jobs_func),name="pbv-job-archive-startup",daemon=True).start())
        except Exception: pass
    AppClass._build=app_build
    original_notify=AppClass.notify_kc
    archive_events={"backup_success","backup_failed","backup_cancelled","backup_interrupted","backup_resumed","verify_failed","restore_test_failed"}
    def notify_kc(self,event,title,message,severity="INFO",details=None):
        result=original_notify(self,event,title,message,severity,details)
        if str(event) in archive_events:
            try:
                jid=str((details or {}).get("job_id") or "") or None
                threading.Thread(target=_refresh_archive_background,args=(self,recent_jobs_func,jid),name="pbv-job-archive-event",daemon=True).start()
            except Exception: pass
        return result
    AppClass.notify_kc=notify_kc
    original_load_records=RestoreAssistantClass._load_records
    def load_records(self):
        original_load_records(self); requested=str(getattr(self.app,"_archive_restore_job_id","") or "")
        if not requested: return
        self.records=[r for r in self.records if len(r)>1 and str(r[1])==requested]; valid={str(r[0]) for r in self.records}; self.decoded={k:v for k,v in self.decoded.items() if k in valid}; self.app._archive_restore_job_id=None
    RestoreAssistantClass._load_records=load_records
    AppClass._job_archive_v198=True
