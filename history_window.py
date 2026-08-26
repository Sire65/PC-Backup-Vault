from __future__ import annotations
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from backup_filters import (
    TIME_PRESETS, STATUS_OPTIONS, MODE_OPTIONS, STORAGE_OPTIONS, VERIFY_OPTIONS,
    PROBLEM_STATUSES, period_bounds, status_display, mode_display,
)
from crypto_box import decrypt_text
from vault_db import recent_jobs, recent_verifications, all_files

STATUS_TAGS = {
    "SUCCESS": "success", "PARTIAL": "warning", "FAILED": "error",
    "BLOCKED_LIMIT": "error", "CANCELLED": "cancelled", "RUNNING": "running",
}


def human_size(n):
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(n or 0)
    for u in units:
        if x < 1024 or u == units[-1]: return f"{x:.1f} {u}"
        x /= 1024


def fmt_time(seconds):
    seconds = int(float(seconds or 0))
    h, rem = divmod(seconds, 3600); m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class HistoryWindow(tk.Toplevel):
    def __init__(self, app, report_callback, verify_callback):
        super().__init__(app)
        self.app = app
        self.dsn = app.active_dsn()
        self.report_callback = report_callback
        self.verify_callback = verify_callback
        self.title("Backup-Historie / Reports")
        self.geometry("1400x720")
        self.minsize(1050, 600)
        self._build()
        self.load_data()

    def _build(self):
        head = ttk.Frame(self, padding=(10, 10, 10, 6)); head.pack(fill="x")
        ttk.Label(head, text="Backup-Historie", font=("Segoe UI", 17, "bold")).pack(side="left")
        ttk.Label(head, text="Sicherungen gezielt filtern, suchen, prüfen und Reports öffnen").pack(side="left", padx=16)
        ttk.Button(head, text="↻ Neu laden", command=self.load_data).pack(side="right")

        f = ttk.LabelFrame(self, text="Filter", padding=8); f.pack(fill="x", padx=10, pady=(0, 8))
        self.period_var = tk.StringVar(value="Dieser Monat")
        self.from_var = tk.StringVar(); self.to_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Alle"); self.mode_var = tk.StringVar(value="Alle")
        self.storage_var = tk.StringVar(value="Alle"); self.verify_var = tk.StringVar(value="Alle")
        self.search_var = tk.StringVar(); self.problems_only = tk.BooleanVar(value=False)

        labels = ["Zeitraum", "Von", "Bis", "Status", "Sicherungsart", "Speicher", "Verify", "Suche"]
        for i, text in enumerate(labels): ttk.Label(f, text=text).grid(row=0, column=i, sticky="w")
        self.period_combo = ttk.Combobox(f, textvariable=self.period_var, values=TIME_PRESETS, state="readonly", width=19)
        self.period_combo.grid(row=1, column=0, sticky="ew", padx=(0, 5)); self.period_combo.bind("<<ComboboxSelected>>", lambda e:self._period_changed())
        self.from_entry = ttk.Entry(f, textvariable=self.from_var, width=12); self.from_entry.grid(row=1, column=1, padx=(0, 5))
        self.to_entry = ttk.Entry(f, textvariable=self.to_var, width=12); self.to_entry.grid(row=1, column=2, padx=(0, 5))
        ttk.Combobox(f, textvariable=self.status_var, values=list(STATUS_OPTIONS), state="readonly", width=18).grid(row=1,column=3,padx=(0,5))
        ttk.Combobox(f, textvariable=self.mode_var, values=list(MODE_OPTIONS), state="readonly", width=15).grid(row=1,column=4,padx=(0,5))
        ttk.Combobox(f, textvariable=self.storage_var, values=list(STORAGE_OPTIONS), state="readonly", width=14).grid(row=1,column=5,padx=(0,5))
        ttk.Combobox(f, textvariable=self.verify_var, values=list(VERIFY_OPTIONS), state="readonly", width=15).grid(row=1,column=6,padx=(0,5))
        search = ttk.Entry(f, textvariable=self.search_var, width=30); search.grid(row=1,column=7,sticky="ew",padx=(0,5)); search.bind("<Return>",lambda e:self.apply_filters())
        ttk.Checkbutton(f,text="nur problematische",variable=self.problems_only,command=self.apply_filters).grid(row=1,column=8,padx=(0,6))
        ttk.Button(f,text="Anwenden",command=self.apply_filters).grid(row=1,column=9,padx=(0,4))
        ttk.Button(f,text="Zurücksetzen",command=self.reset_filters).grid(row=1,column=10)
        f.columnconfigure(7,weight=1)
        self._period_changed(initial=True)

        body = ttk.Frame(self, padding=(10,0,10,0)); body.pack(fill="both", expand=True)
        cols = ("start","mode","storage","trigger","plan","status","verify","files","dirs","orig","stored","dedup","duration","speed","job")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        specs = [
            ("start","Start",140),("mode","Art",105),("storage","Speicher",90),("trigger","Auslöser",90),("plan","Plan",130),
            ("status","Status",105),("verify","Verify",80),("files","Dateien",65),("dirs","Ordner",60),("orig","Original",90),
            ("stored","Neu gespeichert",100),("dedup","Gespart",90),("duration","Dauer",75),("speed","Ø Tempo",90),("job","Job-ID",220),
        ]
        for c,t,w in specs: self.tree.heading(c,text=t); self.tree.column(c,width=w,anchor="w")
        y=ttk.Scrollbar(body,orient="vertical",command=self.tree.yview); x=ttk.Scrollbar(body,orient="horizontal",command=self.tree.xview)
        self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        self.tree.grid(row=0,column=0,sticky="nsew"); y.grid(row=0,column=1,sticky="ns"); x.grid(row=1,column=0,sticky="ew")
        body.rowconfigure(0,weight=1); body.columnconfigure(0,weight=1)
        self.tree.tag_configure("success", foreground="#166534")
        self.tree.tag_configure("warning", foreground="#9A6700")
        self.tree.tag_configure("error", foreground="#B91C1C")
        self.tree.tag_configure("cancelled", foreground="#64748B")
        self.tree.tag_configure("running", foreground="#1D4ED8")
        self.tree.bind("<Double-1>", lambda e:self.report_selected())

        foot = ttk.Frame(self,padding=10); foot.pack(fill="x")
        ttk.Button(foot,text="Report öffnen",command=self.report_selected).pack(side="left",padx=(0,6))
        ttk.Button(foot,text="Job verifizieren",command=self.verify_selected).pack(side="left")
        self.count_label = ttk.Label(foot,text=""); self.count_label.pack(side="right")

    def _period_changed(self, initial=False):
        state = "normal" if self.period_var.get()=="Benutzerdefiniert" else "disabled"
        self.from_entry.configure(state=state); self.to_entry.configure(state=state)
        if not initial and state == "disabled": self.apply_filters()

    def reset_filters(self):
        self.period_var.set("Dieser Monat"); self.from_var.set(""); self.to_var.set("")
        self.status_var.set("Alle"); self.mode_var.set("Alle"); self.storage_var.set("Alle"); self.verify_var.set("Alle")
        self.search_var.set(""); self.problems_only.set(False); self._period_changed(initial=True); self.apply_filters()

    def load_data(self):
        try:
            self.jobs = list(recent_jobs(self.dsn, 4000))
            self.verifications = list(recent_verifications(self.dsn, 4000))
            self.verification_by_job = {}
            for v in self.verifications:
                self.verification_by_job.setdefault(str(v[1]), v)
            rows = all_files(self.dsn, 50000)
            key = self.app.master_key(); self.file_search = {}
            for r in rows:
                jid = str(r[1])
                try: name = decrypt_text(key, r[2])
                except Exception: name = ""
                try: parent = decrypt_text(key, r[3])
                except Exception: parent = ""
                if name or parent:
                    self.file_search.setdefault(jid, []).append((name + " " + parent).lower())
        except Exception as e:
            messagebox.showerror("Historie", str(e), parent=self); return
        self.apply_filters()

    def apply_filters(self):
        if not hasattr(self,"jobs"): return
        ref = self.jobs[0][1] if self.jobs else datetime.now().astimezone()
        try: start,end,caption = period_bounds(self.period_var.get(),ref,self.from_var.get(),self.to_var.get())
        except Exception as e: messagebox.showwarning("Filter",str(e),parent=self); return
        status_codes=STATUS_OPTIONS.get(self.status_var.get()); mode_codes=MODE_OPTIONS.get(self.mode_var.get())
        storage_codes=STORAGE_OPTIONS.get(self.storage_var.get()); verify_codes=VERIFY_OPTIONS.get(self.verify_var.get())
        q=self.search_var.get().strip().lower(); filtered=[]
        for j in self.jobs:
            if start is not None and j[1] < start: continue
            if end is not None and j[1] >= end: continue
            if status_codes is not None and j[3] not in status_codes: continue
            if self.problems_only.get() and j[3] not in PROBLEM_STATUSES: continue
            mode=(j[11] if len(j)>11 else "AUTO") or "AUTO"; storage=(j[15] if len(j)>15 else "NEON") or "NEON"
            if mode_codes is not None and mode not in mode_codes: continue
            if storage_codes is not None and storage not in storage_codes: continue
            v=self.verification_by_job.get(str(j[0])); vresult=v[5] if v else None
            if verify_codes is not None and vresult not in verify_codes: continue
            if q:
                text=" ".join([str(j[0]),str(j[8] or ""),str(j[9] or ""),str(j[10] or ""),str(j[3]),mode,storage]).lower()
                file_hit=any(q in s for s in self.file_search.get(str(j[0]),[]))
                if q not in text and not file_hit: continue
            filtered.append(j)
        self.filtered=filtered; self._render(caption)

    def _render(self, caption):
        for iid in self.tree.get_children(): self.tree.delete(iid)
        self.item_job={}
        for r in self.filtered:
            jid=str(r[0]); v=self.verification_by_job.get(jid); verify=v[5] if v else "–"
            iid=self.tree.insert("","end",tags=(STATUS_TAGS.get(r[3],""),),values=(
                r[1].strftime("%d.%m.%Y %H:%M"), mode_display(r[11] if len(r)>11 else "AUTO"), r[15] if len(r)>15 else "NEON",
                r[9], r[10] or "–", status_display(r[3]), verify,
                r[12] if len(r)>12 else r[4], r[16] if len(r)>16 else 0,
                human_size(r[5]), human_size(r[6]), human_size(r[7]), fmt_time(r[17] if len(r)>17 else 0),
                human_size(r[18]) + "/s" if len(r)>18 and r[18] else "–", jid,
            ))
            self.item_job[iid]=jid
        self.count_label.configure(text=f"{len(self.filtered):,}".replace(",",".")+f" Sicherungen · {caption}")

    def selected_job(self):
        sel=self.tree.selection(); return self.item_job.get(sel[0]) if sel else None

    def report_selected(self):
        jid=self.selected_job()
        if not jid: messagebox.showwarning("Historie","Bitte eine Sicherung auswählen.",parent=self); return
        self.report_callback(jid)

    def verify_selected(self):
        jid=self.selected_job()
        if not jid: messagebox.showwarning("Historie","Bitte eine Sicherung auswählen.",parent=self); return
        self.verify_callback(jid)
