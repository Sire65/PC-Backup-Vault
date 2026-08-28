from __future__ import annotations

import os
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, StringVar, ttk

from .job_history import history_kpis, read_job_history


class JobHistoryTab(ttk.Frame):
    """Shows real local project-finder job history. No simulated rows."""

    def __init__(self, master, *, output_root: str | None = None):
        super().__init__(master)
        self.output_root = output_root or str(Path.home() / "PC-Backup-Vault-Analysen")
        self.status_var = StringVar(value="Noch keine Jobhistorie geladen")
        self._build()

    def _build(self):
        top=ttk.Frame(self); top.pack(fill=X,padx=12,pady=(12,6))
        ttk.Label(top,text="Planjobs · Verlauf",font=("Segoe UI",13,"bold")).pack(side=LEFT)
        ttk.Label(top,textvariable=self.status_var).pack(side=RIGHT)

        kpi=ttk.LabelFrame(self,text="Historie"); kpi.pack(fill=X,padx=12,pady=6)
        self.vars={k:StringVar(value="0") for k in ("runs","success","failed","files","dups")}
        for i,(title,key) in enumerate((("Läufe","runs"),("Erfolgreich","success"),("Fehler","failed"),("Dateien gescannt","files"),("Dubletten","dups"))):
            box=ttk.Frame(kpi); box.grid(row=0,column=i,padx=12,pady=8,sticky="w")
            ttk.Label(box,text=title).pack(anchor="w")
            ttk.Label(box,textvariable=self.vars[key],font=("Segoe UI",14,"bold")).pack(anchor="w")

        body=ttk.LabelFrame(self,text="Letzte Analysen"); body.pack(fill=BOTH,expand=True,padx=12,pady=6)
        cols=("status","profil","dateien","dups","review","dauer","ordner")
        self.tree=ttk.Treeview(body,columns=cols,show="headings")
        titles={"status":"Status","profil":"Profil","dateien":"Dateien","dups":"Dubletten","review":"Prüfen","dauer":"Dauer s","ordner":"Ergebnisordner"}
        widths={"status":80,"profil":180,"dateien":100,"dups":90,"review":90,"dauer":90,"ordner":520}
        for c in cols:
            self.tree.heading(c,text=titles[c]); self.tree.column(c,width=widths[c],anchor="w")
        self.tree.pack(fill=BOTH,expand=True,padx=8,pady=8)
        self.tree.bind("<Double-1>",lambda _e:self.open_selected())

        bar=ttk.Frame(self); bar.pack(fill=X,padx=12,pady=(0,12))
        ttk.Button(bar,text="Verlauf aktualisieren",command=self.refresh).pack(side=LEFT,padx=(0,6))
        ttk.Button(bar,text="Ergebnisordner öffnen",command=self.open_selected).pack(side=LEFT)
        ttk.Label(bar,text=self.output_root).pack(side=RIGHT)

    def refresh(self):
        rows=read_job_history(self.output_root)
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            status=row.get("status","UNKNOWN")
            lamp="🟢" if status=="SUCCESS" else "🔴" if status=="FAILED" else "🟡"
            self.tree.insert("",END,values=(f"{lamp} {status}",row.get("profile","–"),row.get("files",0),row.get("duplicates",0),row.get("review_candidates",0),row.get("duration_seconds",0),row.get("run_dir","")))
        k=history_kpis(rows)
        self.vars["runs"].set(f"{k['runs']:,}")
        self.vars["success"].set(f"{k['success']:,}")
        self.vars["failed"].set(f"{k['failed']:,}")
        self.vars["files"].set(f"{k['files_scanned']:,}")
        self.vars["dups"].set(f"{k['duplicates_found']:,}")
        self.status_var.set(f"{k['runs']} Läufe · letzter Status {k['latest_status']}")

    def open_selected(self):
        sel=self.tree.selection()
        if not sel: return
        vals=self.tree.item(sel[0],"values")
        if not vals: return
        p=Path(vals[-1])
        if p.exists() and os.name=="nt": os.startfile(str(p))
