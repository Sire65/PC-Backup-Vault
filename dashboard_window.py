from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from crypto_box import decrypt_text
from backup_filters import (
    TIME_PRESETS, STATUS_OPTIONS, MODE_OPTIONS, STORAGE_OPTIONS, VERIFY_OPTIONS,
    PROBLEM_STATUSES, period_bounds, status_display, mode_display,
)
from vault_db import (
    all_files,
    recent_jobs,
    recent_restore_tests,
    recent_tuev_checks,
    recent_verifications,
    usage_history,
    database_size,
    schema_compatibility,
)

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
except Exception:  # pragma: no cover - handled at runtime
    FigureCanvasTkAgg = None
    Figure = None

# Dashboard palette: status colours are intentionally stable across all charts.
C = {
    "blue": "#2563EB", "blue2": "#60A5FA", "green": "#16A34A", "green2": "#86EFAC",
    "amber": "#F59E0B", "orange": "#EA580C", "red": "#DC2626", "red2": "#F87171",
    "purple": "#7C3AED", "teal": "#0D9488", "cyan": "#0891B2", "slate": "#64748B",
    "dark": "#0F172A", "muted": "#64748B", "grid": "#E2E8F0", "panel": "#F8FAFC",
    "white": "#FFFFFF", "gray": "#CBD5E1",
}
STATUS_COLORS = {
    "SUCCESS": C["green"], "PARTIAL": C["amber"], "FAILED": C["red"],
    "CANCELLED": C["slate"], "INTERRUPTED": C["orange"], "BLOCKED_LIMIT": C["orange"], "RUNNING": C["blue"],
}
MODE_COLORS = {"FULL": C["purple"], "INCREMENTAL": C["blue"], "QUICK": C["teal"], "AUTO": C["amber"]}
VERIFY_COLORS = {"PASS": C["green"], "WARN": C["amber"], "FAIL": C["red"]}


def human_size(n):
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(n or 0)
    for u in units:
        if x < 1024 or u == units[-1]:
            return f"{x:.1f} {u}"
        x /= 1024


def _fmt_num(n):
    return f"{int(n or 0):,}".replace(",", ".")


class ScrollableTab(ttk.Frame):
    """Notebook tab with a stable minimum chart size and vertical scrolling.

    Matplotlib canvases are never squeezed below their requested height, which
    prevents clipped titles, axes and value labels on 1366/1440px displays.
    """
    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=C["panel"])
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")
        self.inner = ttk.Frame(self.canvas, padding=8)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._sync_region)
        self.canvas.bind("<Configure>", self._sync_width)
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _sync_region(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_width(self, event):
        self.canvas.itemconfigure(self._window, width=max(1, event.width))

    def _wheel(self, event):
        if event.delta:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


class DashboardWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.dsn = app.active_dsn()
        self.title("Dashboard / Statistiken")
        self.geometry("1440x920")
        self.minsize(1050, 700)
        self.configure(bg=C["panel"])
        self._canvases = {}
        if Figure is None:
            messagebox.showerror(
                "Dashboard",
                "matplotlib ist nicht installiert. Bitte STARTEN.bat erneut ausführen, damit die Dashboard-Komponente installiert wird.",
                parent=self,
            )
            self.destroy()
            return
        self._loading=False; self._files_loading=False; self.files_loaded=False; self.files=[]; self.dec_files=[]
        self._build()
        self.after(30, self.load_data)

    def _build(self):
        head = tk.Frame(self, bg=C["white"], padx=16, pady=12)
        head.pack(fill="x")
        tk.Label(head, text="Backup-Dashboard", bg=C["white"], fg=C["dark"], font=("Segoe UI", 19, "bold")).pack(side="left")
        tk.Label(head, text="Kennzahlen, Trends, Speicher, Integrität und Wiederherstellung", bg=C["white"], fg=C["muted"], font=("Segoe UI", 10)).pack(side="left", padx=18)
        ttk.Button(head, text="↻ Neu laden", command=self.load_data).pack(side="right")

        filters = ttk.LabelFrame(self, text="Filter / Sicherungen suchen", padding=8)
        filters.pack(fill="x", padx=10, pady=(10, 6))

        self.period_var = tk.StringVar(value=self.app.store.data.get("dashboard_period", "Dieser Monat"))
        self.from_var = tk.StringVar(value="")
        self.to_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Alle")
        self.mode_var = tk.StringVar(value="Alle")
        self.storage_var = tk.StringVar(value="Alle")
        self.verify_var = tk.StringVar(value="Alle")
        self.search_var = tk.StringVar(value="")
        self.problems_only = tk.BooleanVar(value=False)

        # Responsive filter layout: category filters on the first row, dates/search on the second.
        fields = [
            ("Zeitraum", self.period_var, TIME_PRESETS, 19),
            ("Status", self.status_var, list(STATUS_OPTIONS), 16),
            ("Sicherungsart", self.mode_var, list(MODE_OPTIONS), 15),
            ("Speicher", self.storage_var, list(STORAGE_OPTIONS), 14),
            ("Verify", self.verify_var, list(VERIFY_OPTIONS), 14),
        ]
        for col, (label, var, values, width) in enumerate(fields):
            ttk.Label(filters, text=label).grid(row=0, column=col, sticky="w", padx=(0, 8))
            cb = ttk.Combobox(filters, textvariable=var, values=values, state="readonly", width=width)
            cb.grid(row=1, column=col, sticky="ew", padx=(0, 8))
            if col == 0:
                self.period_combo = cb
                cb.bind("<<ComboboxSelected>>", lambda e: self._period_changed())

        date_box=ttk.Frame(filters)
        date_box.grid(row=2, column=0, columnspan=2, sticky="w", pady=(9,0), padx=(0,12))
        ttk.Label(date_box,text="Von (TT.MM.JJJJ)").grid(row=0,column=0,sticky="w")
        self.from_entry=ttk.Entry(date_box,textvariable=self.from_var,width=13); self.from_entry.grid(row=0,column=1,padx=(6,12))
        ttk.Label(date_box,text="Bis").grid(row=0,column=2,sticky="w")
        self.to_entry=ttk.Entry(date_box,textvariable=self.to_var,width=13); self.to_entry.grid(row=0,column=3,padx=(6,0))

        search_box=ttk.Frame(filters)
        search_box.grid(row=2,column=2,columnspan=3,sticky="ew",pady=(9,0),padx=(0,10))
        ttk.Label(search_box,text="Suche: Datei, Ordner, Job-ID oder Plan").pack(side="left",padx=(0,8))
        search=ttk.Entry(search_box,textvariable=self.search_var); search.pack(side="left",fill="x",expand=True)
        search.bind("<Return>",lambda e:self.apply_filters())

        actions=ttk.Frame(filters)
        actions.grid(row=3,column=0,columnspan=5,sticky="ew",pady=(8,0))
        ttk.Checkbutton(actions,text="nur problematische Sicherungen",variable=self.problems_only,command=self.apply_filters).pack(side="left")
        ttk.Button(actions,text="Anwenden",command=self.apply_filters).pack(side="left",padx=(18,6))
        ttk.Button(actions,text="Zurücksetzen",command=self.reset_filters).pack(side="left")
        for c in range(5): filters.columnconfigure(c,weight=1)
        self._period_changed(initial=True)

        self.schema_notice = tk.Label(self, text="", bg=C["panel"], fg=C["amber"], font=("Segoe UI", 9, "bold"), anchor="w")
        self.schema_notice.pack(fill="x", padx=14, pady=(0, 2))
        self.period_label = tk.Label(self, text="", bg=C["panel"], fg=C["muted"], font=("Segoe UI", 9))
        self.period_label.pack(fill="x", padx=14, pady=(0, 4))

        self.cards_frame = tk.Frame(self, bg=C["panel"], padx=8, pady=2)
        self.cards_frame.pack(fill="x")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(4, 6))
        self.tab_overview = ScrollableTab(self.nb)
        self.tab_trend = ScrollableTab(self.nb)
        self.tab_inventory = ScrollableTab(self.nb)
        self.tab_health = ScrollableTab(self.nb)
        self.tab_restore = ScrollableTab(self.nb)
        self.nb.add(self.tab_overview, text="Übersicht")
        self.nb.add(self.tab_trend, text="Verlauf")
        self.nb.add(self.tab_inventory, text="Dateien / Verzeichnisse")
        self.nb.add(self.tab_health, text="TÜV / Verify / Fehler")
        self.nb.add(self.tab_restore, text="Wiederherstellung")
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)

        self.status = tk.Label(self, text="", bg=C["white"], fg=C["muted"], anchor="w", padx=12, pady=6)
        self.status.pack(fill="x")

    def _chart_host(self, tab):
        return getattr(tab, "inner", tab)

    def _period_changed(self, initial=False):
        custom = self.period_var.get() == "Benutzerdefiniert"
        state = "normal" if custom else "disabled"
        self.from_entry.configure(state=state)
        self.to_entry.configure(state=state)
        if not initial and not custom:
            self.apply_filters()

    def reset_filters(self):
        self.period_var.set("Dieser Monat")
        self.from_var.set("")
        self.to_var.set("")
        self.status_var.set("Alle")
        self.mode_var.set("Alle")
        self.storage_var.set("Alle")
        self.verify_var.set("Alle")
        self.search_var.set("")
        self.problems_only.set(False)
        self._period_changed(initial=True)
        self.apply_filters()

    def load_data(self):
        if self._loading: return
        self._loading=True; self.status.configure(text="Dashboard wird geladen …"); self.schema_notice.configure(text="Neon-Kennzahlen werden im Hintergrund geladen …",fg=C["blue"])
        def work():
            try:
                payload={
                    "schema_info":schema_compatibility(self.dsn), "jobs":list(recent_jobs(self.dsn,2500)),
                    "restores":list(recent_restore_tests(self.dsn,1000)), "tuev":list(recent_tuev_checks(self.dsn,2500)),
                    "verifications":list(recent_verifications(self.dsn,2500)), "usage":list(reversed(usage_history(self.dsn,730))),
                    "db_size":database_size(self.dsn),
                }; err=None
            except Exception as e: payload=None; err=str(e)
            self.after(0,lambda:self._finish_load_data(payload,err))
        threading.Thread(target=work,daemon=True).start()

    def _finish_load_data(self,payload,err=None):
        self._loading=False
        if err:
            self.status.configure(text="Dashboard konnte nicht geladen werden."); messagebox.showerror("Dashboard",err,parent=self); return
        for k,v in payload.items(): setattr(self,k,v)
        self.files=[]; self.dec_files=[]; self.files_loaded=False; self.verification_by_job={}
        for v in self.verifications:
            jid=str(v[1])
            if jid not in self.verification_by_job:self.verification_by_job[jid]=v
        if getattr(self,"schema_info",{}).get("legacy"):
            ver=self.schema_info.get("schema_version","unbekannt"); self.schema_notice.configure(text=f"⚠ Neon-Core {ver}: Kompatibilitätsmodus. Bitte Schema / Core prüfen.",fg=C["amber"])
        else:self.schema_notice.configure(text="✓ Neon-Core ist aktuell – Dashboard-Kennzahlen verfügbar.",fg=C["green"])
        self.apply_filters()

    def _tab_changed(self,_event=None):
        if not hasattr(self,"jobs"): return
        idx=self.nb.index(self.nb.select())
        if idx==2 and not self.files_loaded:
            self._ensure_files_loaded(); return
        self._render_current_tab()

    def _ensure_files_loaded(self,reapply=True):
        if self.files_loaded:
            if reapply:self.apply_filters()
            return
        if self._files_loading:return
        self._files_loading=True; self.status.configure(text="Dateikatalog wird bei Bedarf geladen und lokal entschlüsselt …")
        host=self._chart_host(self.tab_inventory); self._clear(host); ttk.Label(host,text="Dateikatalog wird geladen …",font=("Segoe UI",12,"bold")).grid(row=0,column=0,padx=30,pady=40,sticky="w")
        def work():
            try:
                rows=list(all_files(self.dsn,30000)); dec=self._decrypt_files(rows); err=None
            except Exception as e: rows=[]; dec=[]; err=str(e)
            self.after(0,lambda:self._finish_files_loaded(rows,dec,err,reapply))
        threading.Thread(target=work,daemon=True).start()

    def _finish_files_loaded(self,rows,dec,err,reapply):
        self._files_loading=False
        if err:
            self.status.configure(text="Dateikatalog konnte nicht geladen werden."); messagebox.showerror("Dashboard",err,parent=self); return
        self.files=rows; self.dec_files=dec; self.files_loaded=True
        if reapply:self.apply_filters()
        else:self._render_current_tab()

    def _render_current_tab(self):
        if not hasattr(self,"filtered_jobs"):return
        idx=self.nb.index(self.nb.select())
        if idx==0:self.render_overview_tab()
        elif idx==1:self.render_trend_tab()
        elif idx==2:
            if not self.files_loaded:self._ensure_files_loaded(reapply=False)
            else:self.render_inventory_tab()
        elif idx==3:self.render_health_tab()
        elif idx==4:self.render_restore_tab()

    def apply_filters(self):
        if not hasattr(self,"jobs"): return
        q=self.search_var.get().strip().lower()
        if q and not self.files_loaded:
            self._ensure_files_loaded(reapply=True); return
        ref=self.jobs[0][1] if self.jobs else datetime.now().astimezone()
        try:start,end,caption=period_bounds(self.period_var.get(),ref,self.from_var.get(),self.to_var.get())
        except Exception as e:messagebox.showwarning("Filter",str(e),parent=self);return
        self.app.store.data["dashboard_period"]=self.period_var.get()
        try:self.app.store.save()
        except Exception:pass
        status_codes=STATUS_OPTIONS.get(self.status_var.get()); mode_codes=MODE_OPTIONS.get(self.mode_var.get()); storage_codes=STORAGE_OPTIONS.get(self.storage_var.get()); verify_codes=VERIFY_OPTIONS.get(self.verify_var.get())
        matching_file_jobs=set()
        if q:
            for f in self.dec_files:
                if q in f["name"].lower() or q in f["parent"].lower() or q in f["ext"].lower():matching_file_jobs.add(f["job_id"])
        out=[]
        for j in self.jobs:
            if start is not None and j[1]<start:continue
            if end is not None and j[1]>=end:continue
            if status_codes is not None and j[3] not in status_codes:continue
            if self.problems_only.get() and j[3] not in PROBLEM_STATUSES:continue
            mode=(j[11] if len(j)>11 else "AUTO") or "AUTO"; storage=(j[15] if len(j)>15 else "NEON") or "NEON"
            if mode_codes is not None and mode not in mode_codes:continue
            if storage_codes is not None and storage not in storage_codes:continue
            v=self.verification_by_job.get(str(j[0])); vresult=v[5] if v else None
            if verify_codes is not None and vresult not in verify_codes:continue
            if q:
                text=" ".join([str(j[0]),str(j[8] or ""),str(j[9] or ""),str(j[10] or ""),str(j[3] or ""),str(mode),str(storage)]).lower()
                if q not in text and str(j[0]) not in matching_file_jobs:continue
            out.append(j)
        self.filtered_jobs=out; job_ids={str(j[0]) for j in out}; self.filtered_files=[f for f in self.dec_files if f["job_id"] in job_ids] if self.files_loaded and job_ids else []
        self.filtered_tuev=[t for t in self.tuev if (start is None or t[0]>=start) and (end is None or t[0]<end)]; self.filtered_restores=[r for r in self.restores if (start is None or r[0]>=start) and (end is None or r[0]<end)]; self.filtered_verifications=[v for v in self.verifications if (start is None or v[3]>=start) and (end is None or v[3]<end)]
        self.filter_caption=caption; self.period_label.configure(text=f"Aktiver Zeitraum: {caption}   ·   Filter wirken auf Kennzahlen und Diagramme.")
        self.render_cards(); self._render_current_tab(); catalog=f"{_fmt_num(len(self.filtered_files))} Dateieinträge" if self.files_loaded else "Dateikatalog: lädt nur bei Bedarf"; self.status.configure(text=f"{_fmt_num(len(self.filtered_jobs))} Backup-Läufe · {catalog} · {caption}")

    def _decrypt_files(self, rows):
        out = []
        key = self.app.master_key()
        for r in rows:
            try:
                name = decrypt_text(key, r[2])
            except Exception:
                name = "[nicht entschlüsselbar]"
            try:
                parent = decrypt_text(key, r[3])
            except Exception:
                parent = "[Pfad nicht entschlüsselbar]"
            out.append({
                "id": str(r[0]), "job_id": str(r[1]), "name": name, "parent": parent,
                "ext": (r[4] or "").lower() or "(ohne)", "original_size": int(r[5] or 0),
                "stored_size": int(r[6] or 0), "status": r[9], "created": r[10], "modified": r[11],
                "trigger": r[12] or "–", "plan": r[13] or "–", "backend": r[14] if len(r) > 14 else "NEON",
            })
        return out

    def _clear(self, parent):
        for child in parent.winfo_children():
            child.destroy()
        self._canvases[str(parent)] = []

    def _card(self, parent, row, col, title, value, accent, subtitle=""):
        box = tk.Frame(parent, bg=C["white"], highlightbackground=C["grid"], highlightthickness=1)
        box.grid(row=row, column=col, sticky="nsew", padx=5, pady=4)
        tk.Frame(box, bg=accent, width=5).pack(side="left", fill="y")
        body = tk.Frame(box, bg=C["white"], padx=10, pady=7)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=title, bg=C["white"], fg=C["muted"], font=("Segoe UI", 8)).pack(anchor="w")
        tk.Label(body, text=value, bg=C["white"], fg=C["dark"], font=("Segoe UI", 13, "bold"), anchor="w").pack(anchor="w")
        if subtitle:
            tk.Label(body, text=subtitle, bg=C["white"], fg=C["muted"], font=("Segoe UI", 8), anchor="w", justify="left", wraplength=245).pack(anchor="w")

    def render_cards(self):
        self._clear(self.cards_frame)
        jobs = self.filtered_jobs
        files = self.filtered_files
        total_original = sum(int(j[5] or 0) for j in jobs)
        total_stored = sum(int(j[6] or 0) for j in jobs)
        total_files = sum(int(j[12] or j[4] or 0) for j in jobs)
        unique_dirs = sum(int(j[16] or 0) for j in jobs)
        success = sum(1 for j in jobs if j[3] == "SUCCESS")
        bad = sum(1 for j in jobs if j[3] in PROBLEM_STATUSES)
        speeds = [int(j[18] or 0) for j in jobs if len(j) > 18 and int(j[18] or 0) > 0]
        avg_speed = sum(speeds) / len(speeds) if speeds else 0
        efficiency = (total_stored / total_original * 100.0) if total_original else 0.0
        last_job = jobs[0] if jobs else None
        verify = self.verification_by_job.get(str(last_job[0])) if last_job else None
        verify_text = verify[5] if verify else "–"
        verify_color = VERIFY_COLORS.get(verify_text, C["slate"])
        last_tuev = self.filtered_tuev[0] if self.filtered_tuev else None
        tuev_text = last_tuev[3] if last_tuev else "–"
        tuev_color = VERIFY_COLORS.get(tuev_text, C["slate"])
        b2_count = sum(int(j[12] or j[4] or 0) for j in jobs if ((j[15] if len(j)>15 else "NEON") or "NEON") == "B2")
        neon_count = sum(int(j[12] or j[4] or 0) for j in jobs if ((j[15] if len(j)>15 else "NEON") or "NEON") != "B2")
        hard = int((self.app.active_profile() or {}).get("hard_limit_mb", 420)) * 1024 * 1024
        db_pct = (self.db_size / hard * 100.0) if hard else 0.0
        db_color = C["green"] if db_pct < 60 else C["amber"] if db_pct < 85 else C["red"]

        cards = [
            ("Letzte Sicherung", last_job[1].strftime("%d.%m.%Y %H:%M") if last_job else "–", C["blue"], status_display(last_job[3]) if last_job else ""),
            ("Dateien geprüft", _fmt_num(total_files), C["blue2"], f"{_fmt_num(unique_dirs)} Verzeichnisse"),
            ("Datenmenge", human_size(total_original), C["purple"], f"neu gespeichert {human_size(total_stored)}"),
            ("B2 / Neon Dateien", f"{_fmt_num(b2_count)} / {_fmt_num(neon_count)}", C["teal"], "Dateieinträge im Filter"),
            ("Erfolgreiche Läufe", _fmt_num(success), C["green"], f"von {_fmt_num(len(jobs))} Läufen"),
            ("Problematische Läufe", _fmt_num(bad), C["red"] if bad else C["green"], "Fehler · Teilweise · Abbruch"),
            ("Ø Geschwindigkeit", f"{human_size(avg_speed)}/s" if avg_speed else "–", C["orange"], "aktive Laufzeit"),
            ("Speicher-Effizienz", f"{efficiency:.1f} %" if total_original else "–", C["cyan"], "neu gespeichert / Original"),
            ("Letzter Verify", verify_text, verify_color, verify[4].strftime("%d.%m.%Y %H:%M") if verify and verify[4] else "nicht durchgeführt"),
            ("Letzter TÜV", tuev_text, tuev_color, last_tuev[0].strftime("%d.%m.%Y %H:%M") if last_tuev else "nicht durchgeführt"),
            ("Neon DB", human_size(self.db_size), db_color, f"{db_pct:.1f} % vom Hardlimit"),
            ("Deduplizierung", human_size(sum(int(j[7] or 0) for j in jobs)), C["purple"], "eingesparte Übertragung"),
        ]
        cols = 4
        for i, item in enumerate(cards):
            self._card(self.cards_frame, i // cols, i % cols, *item)
        for c in range(cols):
            self.cards_frame.columnconfigure(c, weight=1)

    def _figure(self, title=None):
        # constrained_layout prevents titles/ticks/labels from being clipped.
        fig = Figure(figsize=(6.1, 3.25), dpi=100, facecolor=C["white"], layout="constrained")
        ax = fig.add_subplot(111)
        ax.set_facecolor(C["white"])
        if title:
            ax.set_title(title, fontsize=11, fontweight="bold", color=C["dark"], pad=9)
        return fig, ax

    def _style_axis(self, ax, grid="y"):
        ax.tick_params(colors=C["muted"], labelsize=8, pad=4)
        ax.xaxis.label.set_color(C["muted"]); ax.yaxis.label.set_color(C["muted"])
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(C["grid"])
        if grid:
            ax.grid(axis=grid, color=C["grid"], linewidth=0.8, alpha=0.75)
            ax.set_axisbelow(True)

    def _empty(self, ax, text="Keine Daten im gewählten Filter"):
        ax.text(0.5, 0.5, text, ha="center", va="center", color=C["muted"], transform=ax.transAxes, fontsize=9)
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values(): sp.set_visible(False)

    def _value_labels(self, ax, bars, fmt=lambda x: f"{int(x)}"):
        labels = [fmt(b.get_height()) for b in bars]
        try:
            ax.bar_label(bars, labels=labels, padding=3, fontsize=8, color=C["dark"])
        except Exception:
            for b, label in zip(bars, labels):
                h = b.get_height()
                ax.text(b.get_x() + b.get_width()/2, h, label, ha="center", va="bottom", fontsize=8, color=C["dark"], clip_on=False)

    def _donut(self, ax, labels, values, colors, center_text=""):
        rows = [(l, float(v), c) for l, v, c in zip(labels, values, colors) if float(v) > 0]
        if not rows:
            self._empty(ax)
            return
        labels, values, colors = zip(*rows)
        total = sum(values)
        def pct(p):
            return f"{p:.0f}%" if p >= 4 else ""
        wedges, _texts, _auto = ax.pie(
            values, labels=None, autopct=pct, pctdistance=0.79, startangle=90, colors=colors,
            wedgeprops={"width": 0.38, "edgecolor": C["white"], "linewidth": 1.3},
            textprops={"fontsize": 8, "color": C["dark"]},
        )
        ax.text(0, 0, center_text or human_size(total), ha="center", va="center", fontweight="bold", fontsize=10, color=C["dark"])
        ax.legend(wedges, labels, loc="lower center", bbox_to_anchor=(0.5, -0.08), ncol=min(3, len(labels)), frameon=False, fontsize=8)

    def _canvas(self, parent, fig, row, col, colspan=1):
        panel = tk.Frame(parent, bg=C["white"], highlightbackground=C["grid"], highlightthickness=1, height=345)
        panel.grid(row=row, column=col, columnspan=colspan, sticky="nsew", padx=7, pady=7)
        panel.grid_propagate(False)
        canvas = FigureCanvasTkAgg(fig, master=panel)
        widget = canvas.get_tk_widget()
        widget.pack(fill="both", expand=True, padx=3, pady=3)
        canvas.draw()
        self._canvases.setdefault(str(parent), []).append(canvas)
        parent.rowconfigure(row, minsize=360)
        return canvas

    def render_overview_tab(self):
        frame = self._chart_host(self.tab_overview)
        self._clear(frame)
        for c in range(2): frame.columnconfigure(c, weight=1)
        for r in range(2): frame.rowconfigure(r, weight=1)

        status_counts = Counter(j[3] for j in self.filtered_jobs)
        fig1, ax1 = self._figure("Backup-Status")
        if status_counts:
            order = [x for x in ["SUCCESS", "PARTIAL", "FAILED", "INTERRUPTED", "CANCELLED", "BLOCKED_LIMIT", "RUNNING"] if status_counts.get(x)]
            vals = [status_counts[x] for x in order]
            bars = ax1.bar([status_display(x) for x in order], vals, color=[STATUS_COLORS[x] for x in order], width=0.62)
            self._value_labels(ax1, bars); ax1.set_ylabel("Anzahl Läufe"); self._style_axis(ax1)
            ax1.tick_params(axis="x", rotation=12); [lab.set_ha("right") for lab in ax1.get_xticklabels()]
        else: self._empty(ax1)
        self._canvas(frame, fig1, 0, 0)

        hard = int((self.app.active_profile() or {}).get("hard_limit_mb", 420)) * 1024 * 1024
        pct = min(100, (self.db_size / hard) * 100) if hard else 0
        fig2, ax2 = self._figure("Neon-Metadaten / Hardlimit")
        ax2.barh(["Neon"], [100], color=C["grid"], height=0.36)
        cap_color = C["green"] if pct < 60 else C["amber"] if pct < 85 else C["red"]
        ax2.barh(["Neon"], [pct], color=cap_color, height=0.36)
        ax2.set_xlim(0, 100); ax2.set_xlabel("Prozent des Hardlimits"); self._style_axis(ax2, "x")
        ax2.text(min(pct + 2, 92), 0, f"{pct:.1f} %", va="center", fontweight="bold", color=C["dark"])
        self._canvas(frame, fig2, 0, 1)

        backend_bytes = Counter()
        for f in self.filtered_files:
            backend_bytes[f["backend"]] += f["stored_size"]
        fig3, ax3 = self._figure("Speicherverteilung der Dateiblöcke")
        if sum(backend_bytes.values()) > 0:
            labels = ["Backblaze B2" if k == "B2" else "Neon" for k in backend_bytes]
            vals = list(backend_bytes.values())
            colors = [C["blue" if k == "B2" else "purple"] for k in backend_bytes]
            self._donut(ax3, labels, vals, colors, human_size(sum(vals)))
        else: self._empty(ax3)
        self._canvas(frame, fig3, 1, 0)

        mode_counts = Counter((j[11] if len(j) > 11 else "AUTO") or "AUTO" for j in self.filtered_jobs)
        fig4, ax4 = self._figure("Sicherungsarten")
        if mode_counts:
            order = [x for x in ["FULL", "INCREMENTAL", "QUICK", "AUTO"] if mode_counts.get(x)]
            vals = [mode_counts[x] for x in order]
            bars = ax4.bar([mode_display(x) for x in order], vals, color=[MODE_COLORS[x] for x in order], width=0.62)
            self._value_labels(ax4, bars); ax4.set_ylabel("Anzahl Läufe"); self._style_axis(ax4)
            ax4.tick_params(axis="x", rotation=8); [lab.set_ha("right") for lab in ax4.get_xticklabels()]
        else: self._empty(ax4)
        self._canvas(frame, fig4, 1, 1)

    def render_trend_tab(self):
        frame = self._chart_host(self.tab_trend)
        self._clear(frame)
        for c in range(2): frame.columnconfigure(c, weight=1)
        for r in range(2): frame.rowconfigure(r, weight=1)

        daily = defaultdict(lambda: {"orig": 0, "stored": 0, "files": 0, "speeds": [], "eff": []})
        for j in self.filtered_jobs:
            d = j[1].date(); daily[d]["orig"] += int(j[5] or 0); daily[d]["stored"] += int(j[6] or 0)
            daily[d]["files"] += int(j[12] or j[4] or 0)
            if len(j) > 18 and int(j[18] or 0) > 0: daily[d]["speeds"].append(int(j[18]))
        days = sorted(daily); labels = [d.strftime("%d.%m.") for d in days]

        fig1, ax1 = self._figure("Datenvolumen pro Tag")
        if days:
            orig = [daily[d]["orig"] / 1024 / 1024 for d in days]; stored = [daily[d]["stored"] / 1024 / 1024 for d in days]
            ax1.plot(labels, orig, marker="o", linewidth=2, color=C["blue"], label="Original MB")
            ax1.plot(labels, stored, marker="o", linewidth=2, color=C["teal"], label="Neu gespeichert MB")
            ax1.fill_between(range(len(labels)), stored, alpha=0.10, color=C["teal"])
            ax1.set_ylabel("MB"); self._style_axis(ax1); ax1.legend(frameon=False, fontsize=8)
            ax1.tick_params(axis="x", rotation=28); [lab.set_ha("right") for lab in ax1.get_xticklabels()]
        else: self._empty(ax1)
        self._canvas(frame, fig1, 0, 0)

        fig2, ax2 = self._figure("Dateien pro Tag")
        if days:
            bars = ax2.bar(labels, [daily[d]["files"] for d in days], color=C["blue2"], width=0.65)
            ax2.set_ylabel("Dateien"); self._style_axis(ax2); ax2.tick_params(axis="x", rotation=28); [lab.set_ha("right") for lab in ax2.get_xticklabels()]
        else: self._empty(ax2)
        self._canvas(frame, fig2, 0, 1)

        fig3, ax3 = self._figure("Ø Geschwindigkeit pro Tag")
        if days:
            speeds = [(sum(daily[d]["speeds"]) / len(daily[d]["speeds"]) / 1024 / 1024) if daily[d]["speeds"] else 0 for d in days]
            ax3.plot(labels, speeds, marker="o", linewidth=2.3, color=C["orange"])
            ax3.set_ylabel("MB/s"); self._style_axis(ax3); ax3.tick_params(axis="x", rotation=28); [lab.set_ha("right") for lab in ax3.get_xticklabels()]
        else: self._empty(ax3)
        self._canvas(frame, fig3, 1, 0)

        fig4, ax4 = self._figure("Speicher-Effizienz pro Lauf")
        jobs = list(reversed(self.filtered_jobs[:30]))
        if jobs:
            x = [j[1].strftime("%d.%m.\n%H:%M") for j in jobs]
            eff = [(int(j[6] or 0) / int(j[5] or 1) * 100) if int(j[5] or 0) else 0 for j in jobs]
            ax4.plot(x, eff, marker="o", linewidth=2, color=C["purple"])
            ax4.fill_between(range(len(x)), eff, alpha=0.08, color=C["purple"])
            ax4.set_ylabel("neu gespeichert / Original (%)"); self._style_axis(ax4); ax4.tick_params(axis="x", rotation=28); [lab.set_ha("right") for lab in ax4.get_xticklabels()]
        else: self._empty(ax4)
        self._canvas(frame, fig4, 1, 1)

    def render_inventory_tab(self):
        frame = self._chart_host(self.tab_inventory)
        self._clear(frame)
        for c in range(2): frame.columnconfigure(c, weight=1)
        for r in range(2): frame.rowconfigure(r, weight=1)
        files = self.filtered_files

        ext_counts = Counter(f["ext"] or "(ohne)" for f in files); top_ext = ext_counts.most_common(10)
        fig1, ax1 = self._figure("Top-Dateitypen")
        if top_ext:
            names = [e[0] for e in top_ext[::-1]]; vals = [e[1] for e in top_ext[::-1]]
            ax1.barh(names, vals, color=[C["blue2"] if i % 2 == 0 else C["blue"] for i in range(len(vals))])
            ax1.set_xlabel("Anzahl Dateien"); self._style_axis(ax1, "x")
        else: self._empty(ax1)
        self._canvas(frame, fig1, 0, 0)

        dir_counts = Counter(Path(f["parent"]).name or f["parent"] for f in files); top_dirs = dir_counts.most_common(10)
        fig2, ax2 = self._figure("Top-Verzeichnisse")
        if top_dirs:
            names = [(d[0] if len(d[0]) < 25 else d[0][:22] + "…") for d in top_dirs[::-1]]; vals = [d[1] for d in top_dirs[::-1]]
            ax2.barh(names, vals, color=[C["teal"] if i % 2 == 0 else C["cyan"] for i in range(len(vals))])
            ax2.set_xlabel("Anzahl Dateien"); self._style_axis(ax2, "x")
        else: self._empty(ax2)
        self._canvas(frame, fig2, 0, 1)

        size_bins = {"< 1 MB": 0, "1–10 MB": 0, "10–100 MB": 0, "> 100 MB": 0}
        for f in files:
            mb = f["original_size"] / 1024 / 1024
            if mb < 1: size_bins["< 1 MB"] += 1
            elif mb < 10: size_bins["1–10 MB"] += 1
            elif mb < 100: size_bins["10–100 MB"] += 1
            else: size_bins["> 100 MB"] += 1
        fig3, ax3 = self._figure("Dateigrößenklassen")
        bars = ax3.bar(list(size_bins), list(size_bins.values()), color=[C["green2"], C["teal"], C["amber"], C["orange"]], width=0.62)
        self._value_labels(ax3, bars); ax3.set_ylabel("Anzahl Dateien"); self._style_axis(ax3)
        self._canvas(frame, fig3, 1, 0)

        backend = Counter()
        for f in files: backend[f["backend"]] += f["stored_size"]
        fig4, ax4 = self._figure("B2 / Neon nach gespeicherter Menge")
        if sum(backend.values()):
            keys = list(backend); vals = [backend[k] for k in keys]
            self._donut(ax4, ["Backblaze B2" if k == "B2" else "Neon" for k in keys], vals,
                        [C["blue"] if k == "B2" else C["purple"] for k in keys], human_size(sum(vals)))
        else: self._empty(ax4)
        self._canvas(frame, fig4, 1, 1)

    def render_health_tab(self):
        frame = self._chart_host(self.tab_health)
        self._clear(frame)
        for c in range(2): frame.columnconfigure(c, weight=1)
        for r in range(2): frame.rowconfigure(r, weight=1)

        tuev_counts = Counter(t[3] for t in self.filtered_tuev)
        fig1, ax1 = self._figure("TÜV-Ergebnisse")
        if tuev_counts:
            keys = [k for k in ["PASS", "WARN", "FAIL"] if tuev_counts.get(k)]
            vals = [tuev_counts[k] for k in keys]
            self._donut(ax1, keys, vals, [VERIFY_COLORS[k] for k in keys], f"{sum(vals)} Prüfungen")
        else: self._empty(ax1)
        self._canvas(frame, fig1, 0, 0)

        verify_counts = Counter(v[5] for v in self.filtered_verifications)
        fig2, ax2 = self._figure("Verifizierungs-Ergebnisse")
        if verify_counts:
            keys = [k for k in ["PASS", "WARN", "FAIL"] if verify_counts.get(k)]
            vals = [verify_counts[k] for k in keys]
            bars = ax2.bar(keys, vals, color=[VERIFY_COLORS[k] for k in keys], width=0.56)
            self._value_labels(ax2, bars); ax2.set_ylabel("Prüfungen"); self._style_axis(ax2)
        else: self._empty(ax2, "Noch keine Verifizierungen im Zeitraum")
        self._canvas(frame, fig2, 0, 1)

        job_err_by_day = defaultdict(int)
        for j in self.filtered_jobs:
            if j[3] in PROBLEM_STATUSES: job_err_by_day[j[1].date()] += 1
        fig3, ax3 = self._figure("Problematische Läufe pro Tag")
        days = sorted(job_err_by_day)
        if days:
            labels = [d.strftime("%d.%m.") for d in days]
            ax3.bar(labels, [job_err_by_day[d] for d in days], color=C["red2"], width=0.65)
            ax3.set_ylabel("Anzahl"); self._style_axis(ax3); ax3.tick_params(axis="x", rotation=28); [lab.set_ha("right") for lab in ax3.get_xticklabels()]
        else: self._empty(ax3, "Keine problematischen Läufe")
        self._canvas(frame, fig3, 1, 0)

        text_frame = ttk.LabelFrame(frame, text="Letzte Warnungen / Fehler", padding=4)
        text_frame.grid(row=1, column=1, sticky="nsew", padx=6, pady=6)
        text_frame.rowconfigure(0, weight=1); text_frame.columnconfigure(0, weight=1)
        health_text = tk.Text(text_frame, height=12, wrap="word", relief="flat", bg=C["white"], fg=C["dark"])
        sb = ttk.Scrollbar(text_frame, orient="vertical", command=health_text.yview); health_text.configure(yscrollcommand=sb.set)
        health_text.grid(row=0, column=0, sticky="nsew"); sb.grid(row=0, column=1, sticky="ns")
        recent_bad = [t for t in self.filtered_tuev if t[3] in ("WARN", "FAIL")][:25]
        if recent_bad:
            for t in recent_bad: health_text.insert("end", f"{t[0]:%d.%m.%Y %H:%M}  ·  {t[1]}  ·  {t[3]}\n{t[4]}\n\n")
        else: health_text.insert("end", "Keine aktuellen Warnungen oder Fehler im gewählten Zeitraum.")
        health_text.configure(state="disabled")

    def render_restore_tab(self):
        frame = self._chart_host(self.tab_restore)
        self._clear(frame)
        for c in range(2): frame.columnconfigure(c, weight=1)
        frame.rowconfigure(0, weight=1); frame.rowconfigure(1, weight=1)

        restore_counts = Counter(r[1] for r in self.filtered_restores)
        fig1, ax1 = self._figure("Restore-Ergebnisse")
        if restore_counts:
            keys = list(restore_counts); vals = [restore_counts[k] for k in keys]
            colors = [C["green"] if str(k).upper() in ("PASS", "SUCCESS", "OK") else C["red"] for k in keys]
            bars = ax1.bar(keys, vals, color=colors, width=0.6); self._value_labels(ax1, bars)
            ax1.set_ylabel("Anzahl"); self._style_axis(ax1)
        else: self._empty(ax1, "Noch keine Restore-Tests")
        self._canvas(frame, fig1, 0, 0)

        bytes_by_day = defaultdict(int)
        for r in self.filtered_restores: bytes_by_day[r[0].date()] += int(r[3] or 0)
        days = sorted(bytes_by_day)
        fig2, ax2 = self._figure("Wiederhergestelltes Volumen pro Tag")
        if days:
            labels = [d.strftime("%d.%m.") for d in days]
            vals = [bytes_by_day[d] / 1024 / 1024 for d in days]
            ax2.plot(labels, vals, marker="o", linewidth=2.3, color=C["teal"]); ax2.fill_between(range(len(labels)), vals, alpha=0.10, color=C["teal"])
            ax2.set_ylabel("MB"); self._style_axis(ax2); ax2.tick_params(axis="x", rotation=28); [lab.set_ha("right") for lab in ax2.get_xticklabels()]
        else: self._empty(ax2)
        self._canvas(frame, fig2, 0, 1)

        table_frame = ttk.Frame(frame); table_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=6, pady=6)
        table_frame.rowconfigure(0, weight=1); table_frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(table_frame, columns=("time", "result", "hash", "bytes", "details"), show="headings")
        for c, t, w in [("time", "Zeit", 150), ("result", "Ergebnis", 90), ("hash", "Hash", 70), ("bytes", "Daten", 100), ("details", "Details", 650)]:
            tree.heading(c, text=t); tree.column(c, width=w)
        y = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview); x = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        tree.grid(row=0, column=0, sticky="nsew"); y.grid(row=0, column=1, sticky="ns"); x.grid(row=1, column=0, sticky="ew")
        for r in self.filtered_restores[:250]:
            tree.insert("", "end", values=(r[0].strftime("%d.%m.%Y %H:%M"), r[1], "OK" if r[2] else "Nein", human_size(r[3] or 0), r[4] or ""))
