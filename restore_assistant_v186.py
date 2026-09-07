from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path, PureWindowsPath
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from vault_db import all_files
from backup_engine import restore_file


def _safe_rel(original_path: str, file_name: str) -> Path:
    p = PureWindowsPath(original_path or "")
    parts = []
    if p.drive:
        parts.append(p.drive.replace(":", ""))
    for x in p.parts:
        if x not in (p.drive, "\\", "/"):
            parts.append(x)
    if parts and parts[-1].lower() == file_name.lower():
        parts = parts[:-1]
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


class RestoreAssistant(tk.Toplevel):
    """Simple 4-step restore workflow reusing the existing restore engine."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.store = app.store
        self.dsn = app.active_dsn()
        self.title("PC Backup Vault – Wiederherstellen")
        self.geometry("960x700")
        self.minsize(860, 620)
        self.transient(app)
        self.grab_set()
        self.step = 0
        self.records = []
        self.visible = []
        self.selected_ids = set()
        self.destination_mode = "OTHER"
        self.destination = str(Path.home() / "Desktop" / "PC Backup Vault Wiederherstellung")
        self.conflict = "KEEP_BOTH"

        if not self.dsn:
            messagebox.showwarning("Wiederherstellung", "Keine Neon-Datenbankverbindung eingerichtet.", parent=self)
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

    def _load_records(self):
        try:
            self.records = list(all_files(self.dsn, 5000))
        except Exception as e:
            messagebox.showerror("Wiederherstellung", f"Sicherungen konnten nicht geladen werden:\n\n{e}", parent=self)
            self.records = []

    def _clear(self):
        for w in self.body.winfo_children(): w.destroy()

    def render(self):
        self._clear(); self.btn_back.configure(state="disabled" if self.step == 0 else "normal")
        self.btn_next.configure(text="Weiter →")
        [self.step_what, self.step_when, self.step_where, self.step_summary][self.step]()

    def step_what(self):
        self.subtitle.configure(text="Schritt 1 von 4 – Was möchten Sie wiederherstellen?")
        ttk.Label(self.body, text="Dateien auswählen", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        row = ttk.Frame(self.body); row.pack(fill="x", pady=(10, 8))
        ttk.Label(row, text="Suche:").pack(side="left")
        self.search = tk.StringVar()
        ent = ttk.Entry(row, textvariable=self.search); ent.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.tree = ttk.Treeview(self.body, columns=("file","path","date","size"), show="headings", selectmode="extended")
        for c,t,w in [("file","Datei",240),("path","Ursprünglicher Pfad",420),("date","Sicherung",150),("size","Größe",90)]:
            self.tree.heading(c,text=t); self.tree.column(c,width=w,anchor="e" if c=="size" else "w")
        y=ttk.Scrollbar(self.body,orient="vertical",command=self.tree.yview); self.tree.configure(yscrollcommand=y.set)
        self.tree.pack(side="left",fill="both",expand=True); y.pack(side="right",fill="y")
        self.search.trace_add("write", lambda *_: self._refresh_files())
        self._refresh_files(); ent.focus_set()

    def _refresh_files(self):
        if not hasattr(self, "tree"): return
        q = self.search.get().strip().lower() if hasattr(self,"search") else ""
        for x in self.tree.get_children(): self.tree.delete(x)
        self.visible=[]
        seen=set()
        for r in self.records:
            fid, job_id, name, orig, ext, osize, ssize, sha, comp, status, created, modified, trigger, plan, backend = r
            key=(str(orig).lower(), str(name).lower())
            if key in seen: continue  # newest version first
            if q and q not in f"{name} {orig} {plan or ''}".lower(): continue
            seen.add(key); self.visible.append(r)
            stamp = created.strftime("%d.%m.%Y %H:%M") if hasattr(created,"strftime") else str(created)
            size = f"{(osize or 0)/1024:.1f} KB" if (osize or 0)<1024*1024 else f"{(osize or 0)/1024/1024:.1f} MB"
            self.tree.insert("", "end", iid=str(fid), values=(name, orig, stamp, size))

    def step_when(self):
        self.subtitle.configure(text="Schritt 2 von 4 – Von wann?")
        ttk.Label(self.body, text="Sicherungsstand", font=("Segoe UI",15,"bold")).pack(anchor="w")
        ttk.Label(self.body, text="Standardmäßig wird die neueste erfolgreiche Version verwendet. Für ältere Stände können Sie unten eine Version wählen.", wraplength=850).pack(anchor="w", pady=(6,12))
        chosen=[r for r in self.records if str(r[0]) in self.selected_ids]
        for r in chosen:
            name=r[2]; orig=r[3]
            box=ttk.LabelFrame(self.body,text=name,padding=8); box.pack(fill="x",pady=4)
            versions=[x for x in self.records if x[2]==name and x[3]==orig]
            labels=[]; mapping={}
            for x in versions:
                stamp=x[10].strftime("%d.%m.%Y %H:%M") if hasattr(x[10],"strftime") else str(x[10])
                label=f"{stamp} · {x[14]} · {x[9]}"
                labels.append(label); mapping[label]=x
            var=tk.StringVar(value=labels[0] if labels else "")
            cb=ttk.Combobox(box,textvariable=var,state="readonly",values=labels,width=72); cb.pack(anchor="w")
            def setver(*_, v=var, m=mapping, old=str(r[0])):
                x=m.get(v.get())
                if x:
                    self.selected_ids.discard(old); self.selected_ids.add(str(x[0]))
            var.trace_add("write",setver)

    def step_where(self):
        self.subtitle.configure(text="Schritt 3 von 4 – Wohin?")
        ttk.Label(self.body,text="Ziel auswählen",font=("Segoe UI",15,"bold")).pack(anchor="w")
        mode=tk.StringVar(value=self.destination_mode)
        ttk.Radiobutton(self.body,text="In einen sicheren Wiederherstellungsordner (empfohlen)",variable=mode,value="OTHER",command=lambda:self._set_mode(mode.get())).pack(anchor="w",pady=(12,4))
        ttk.Radiobutton(self.body,text="An ursprünglichen Speicherort",variable=mode,value="ORIGINAL",command=lambda:self._set_mode(mode.get())).pack(anchor="w",pady=4)
        row=ttk.Frame(self.body); row.pack(fill="x",pady=(14,4))
        self.dest_var=tk.StringVar(value=self.destination)
        ttk.Entry(row,textvariable=self.dest_var).pack(side="left",fill="x",expand=True)
        ttk.Button(row,text="Ordner wählen …",command=self._choose_dest).pack(side="left",padx=(6,0))
        ttk.Label(self.body,text="Bei Wiederherstellung an den ursprünglichen Ort kann eine bestehende Datei betroffen sein. Deshalb gilt immer eine Konfliktregel.",wraplength=850).pack(anchor="w",pady=(8,16))
        ttk.Label(self.body,text="Wenn eine Datei bereits existiert:",font=("Segoe UI",10,"bold")).pack(anchor="w")
        cv=tk.StringVar(value=self.conflict)
        for code,label in [("KEEP_BOTH","Beide behalten (empfohlen)"),("REPLACE","Vorhandene Datei ersetzen"),("SKIP","Vorhandene Datei überspringen")]:
            ttk.Radiobutton(self.body,text=label,variable=cv,value=code,command=lambda:self._set_conflict(cv.get())).pack(anchor="w",pady=3)

    def _set_mode(self,v): self.destination_mode=v
    def _set_conflict(self,v): self.conflict=v
    def _choose_dest(self):
        p=filedialog.askdirectory(parent=self,title="Zielordner für Wiederherstellung")
        if p: self.destination=p; self.dest_var.set(p)

    def step_summary(self):
        self.subtitle.configure(text="Schritt 4 von 4 – Prüfen und wiederherstellen")
        ttk.Label(self.body,text="Bereit zur Wiederherstellung",font=("Segoe UI",15,"bold")).pack(anchor="w")
        rows=[r for r in self.records if str(r[0]) in self.selected_ids]
        total=sum(int(r[5] or 0) for r in rows)
        target="ursprünglicher Speicherort" if self.destination_mode=="ORIGINAL" else self.destination
        conflict={"KEEP_BOTH":"Beide behalten","REPLACE":"Ersetzen","SKIP":"Überspringen"}[self.conflict]
        text=f"Dateien: {len(rows)}\nDatenmenge: {total/1024:.1f} KB\nZiel: {target}\nBei Konflikten: {conflict}\n\nDie vorhandene Restore-Engine entschlüsselt und prüft die wiederhergestellten Daten."
        ttk.Label(self.body,text=text,justify="left",wraplength=850).pack(anchor="w",pady=(12,0))
        self.btn_next.configure(text="♻ Jetzt wiederherstellen")

    def next(self):
        if self.step==0:
            sel=self.tree.selection()
            if not sel:
                messagebox.showwarning("Wiederherstellung","Bitte mindestens eine Datei auswählen.",parent=self); return
            self.selected_ids=set(sel)
        if self.step==2 and self.destination_mode=="OTHER":
            self.destination=self.dest_var.get().strip()
            if not self.destination:
                messagebox.showwarning("Wiederherstellung","Bitte einen Zielordner auswählen.",parent=self); return
        if self.step<3:
            self.step+=1; self.render(); return
        self._restore_now()

    def back(self):
        if self.step>0: self.step-=1; self.render()

    def _restore_now(self):
        rows=[r for r in self.records if str(r[0]) in self.selected_ids]
        if not rows: return
        self.btn_next.configure(state="disabled",text="Wiederherstellung läuft …")
        def worker():
            ok=[]; skipped=[]; errors=[]
            for r in rows:
                fid,name,orig=str(r[0]),str(r[2]),str(r[3] or "")
                try:
                    if self.destination_mode=="ORIGINAL":
                        original_file=Path(orig) if Path(orig).name else Path(orig)/name
                        root=original_file.parent; rel=Path(original_file.name)
                    else:
                        root=Path(self.destination); rel=_safe_rel(orig,name)
                    final=root/rel
                    if final.exists():
                        if self.conflict=="SKIP": skipped.append(str(final)); continue
                        if self.conflict=="KEEP_BOTH":
                            alt=_keep_both(final); rel=alt.relative_to(root)
                    restored=restore_file(self.dsn,self.app.master_key(),fid,root,relative_path=rel,object_store_config=self.store.get_b2_runtime_config())
                    ok.append(str(restored))
                except Exception as e:
                    errors.append(f"{name}: {e}")
            def done():
                self.btn_next.configure(state="normal",text="♻ Jetzt wiederherstellen")
                if errors:
                    messagebox.showwarning("Wiederherstellung",f"Wiederhergestellt: {len(ok)}\nÜbersprungen: {len(skipped)}\nFehler: {len(errors)}\n\n"+"\n".join(errors[:8]),parent=self)
                else:
                    messagebox.showinfo("Wiederherstellung",f"Wiederherstellung erfolgreich ✓\n\nWiederhergestellt: {len(ok)}\nÜbersprungen: {len(skipped)}",parent=self)
                    self.destroy()
            self.after(0,done)
        threading.Thread(target=worker,daemon=True).start()


def apply_restore_assistant_v186(AppClass, BackupAssistantClass):
    original_build=AppClass._build
    def _build(self):
        original_build(self)
        def walk(w):
            for c in w.winfo_children():
                if isinstance(c,ttk.LabelFrame) and str(c.cget("text")) == "Übersicht / Wiederherstellung":
                    ttk.Button(c,text="♻ Wiederherstellen",command=lambda:RestoreAssistant(self)).pack(side="left",padx=(0,6),before=c.winfo_children()[1] if len(c.winfo_children())>1 else None)
                    return True
                if walk(c): return True
            return False
        try: walk(self)
        except Exception: pass
        self.open_restore_assistant=lambda:RestoreAssistant(self)
    AppClass._build=_build

    def finish_restore(self):
        self.destroy()
        try: RestoreAssistant(self.app)
        except Exception as e: messagebox.showerror("Wiederherstellung",str(e),parent=self.app)
    BackupAssistantClass.finish_restore=finish_restore
