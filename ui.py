from __future__ import annotations
import base64, threading, time, os, tempfile
from datetime import datetime
from pathlib import Path, PureWindowsPath
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from config_store import ConfigStore, APP_VERSION
from crypto_box import create_key_b64, decrypt_text
from vault_db import test_connection, initialize_schema, database_size, recent_jobs, all_files, recent_tuev_checks, recent_verifications
from backup_engine import collect_paths, backup_files, restore_file, LimitBlocked, ChristmasGuard, BackupCancelled, BackupControl, guard_active, recommend_backup_mode
from tuev import run_tuev
from plan_runner import run_plan
from scheduler import install_task, remove_task, task_status
from dashboard_window import DashboardWindow
from history_window import HistoryWindow
from object_store import make_b2_store
from recovery_pass import export_encrypted_bundle, import_encrypted_bundle, export_safe_pass_png, export_readme, recovery_fingerprint
from verification import verify_job, latest_successful_job_id
from reporting import load_job_report, report_text, save_report_txt, save_report_csv, fmt_duration
from status_bus import subscribe as status_subscribe, state as status_state
from kc_communication import (make_client as make_kc_client, recent_history as kc_recent_history,
    DEFAULT_MACHINE_ENDPOINT, EVENT_ALIASES)
from interrupted_recovery import (load_checkpoint, clear_checkpoint, save_manual_checkpoint, update_job_id,
    mark_interrupted_job, discard_recovery)

APP_TITLE = "PC Backup Vault"

PAYLOAD_DISPLAY_TO_CODE = {
    "Automatisch (empfohlen)": "AUTO",
    "Backblaze B2": "B2",
    "Neon – nur Kleinmengen": "NEON",
}
PAYLOAD_CODE_TO_DISPLAY = {v:k for k,v in PAYLOAD_DISPLAY_TO_CODE.items()}

def human_size(n):
    units=["B","KB","MB","GB","TB"]; x=float(n or 0)
    for u in units:
        if x < 1024 or u == units[-1]: return f"{x:.1f} {u}"
        x /= 1024

def original_relative(parent: str, name: str) -> Path:
    if "\\" in parent or (len(parent) >= 2 and parent[1] == ":"):
        p = PureWindowsPath(parent)
        parts = [p.drive.replace(":","")] + [x for x in p.parts if x not in (p.drive, "\\", "/")]
    else:
        p = Path(parent)
        parts = [x for x in p.parts if x not in ("/", "\\")]
    return Path(*[x for x in parts if x]) / name

class StatusIndicator(tk.Frame):
    COLORS = {
        "ok": "#16a34a", "warn": "#f59e0b", "error": "#dc2626",
        "off": "#94a3b8", "checking": "#2563eb", "unknown": "#94a3b8",
    }
    def __init__(self, master, text, command=None, traffic=True):
        super().__init__(master, bg="#f8fafc", cursor="hand2" if command else "")
        self.command = command; self.traffic_enabled = traffic; self.detail = ""; self.level = "unknown"
        self.canvas = tk.Canvas(self, width=20, height=32, bg="#f8fafc", highlightthickness=0)
        self.canvas.pack(side="left", padx=(0, 3))
        self.main_dot = self.canvas.create_oval(4, 4, 14, 14, fill=self.COLORS["unknown"], outline="#64748b")
        self.traffic_dot = self.canvas.create_oval(6, 21, 12, 27, fill="#cbd5e1", outline="")
        self.label = tk.Label(self, text=text, bg="#f8fafc", fg="#0f172a", font=("Segoe UI", 8, "bold"))
        self.label.pack(side="left")
        for w in (self, self.canvas, self.label):
            if command: w.bind("<Button-1>", lambda e: command())

    def set_state(self, level, detail=""):
        self.level = str(level or "unknown").lower(); self.detail = str(detail or "")
        color = self.COLORS.get(self.level, self.COLORS["unknown"])
        self.canvas.itemconfigure(self.main_dot, fill=color)
        self.label.configure(fg="#0f172a" if self.level != "error" else "#991b1b")

    def pulse(self):
        if not self.traffic_enabled: return
        self.canvas.itemconfigure(self.traffic_dot, fill="#f59e0b")
        try: self.after(700, lambda: self.canvas.itemconfigure(self.traffic_dot, fill="#cbd5e1"))
        except Exception: pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE}  {APP_VERSION}")
        self.geometry("1160x760")
        self.minsize(960,650)
        self.store=ConfigStore(); self.selected=[]
        self.mode_var=tk.StringVar(value="Empfohlen (automatisch)")
        self.payload_var=tk.StringVar(value=PAYLOAD_CODE_TO_DISPLAY.get(self.store.data.get("payload_target_default","AUTO"),"Automatisch (empfohlen)"))
        self._live_phase = None
        self._live_last_t = None
        self._live_last_bytes = 0
        self._live_speed = 0.0
        self._live_last_draw = 0.0
        self._backup_control = None
        self._backup_running = False
        self._backup_paused = False
        self._backup_button_blink_after = None
        self._backup_button_blink_phase = False
        if not self.store.get_master_key(): self.store.set_master_key(create_key_b64())
        self._system_states = {}
        self._status_unsubscribe = status_subscribe(self._on_status_bus)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.exit_app)
        self._write_start_protocol("START", f"PC Backup Vault {APP_VERSION} gestartet")
        self.refresh_status()
        self.after(250, self.refresh_system_status)
        self.after(900, self.check_interrupted_backup)
        self.after(300, self._update_backup_button_state)

    def master_key(self): return self.store.get_master_key()
    def active_profile(self): return self.store.get_profile()
    def active_dsn(self):
        p=self.active_profile(); return self.store.get_dsn(p["id"]) if p else None

    def _build(self):
        top=ttk.Frame(self,padding=(12,10,12,4)); top.pack(fill="x")
        ttk.Label(top,text=APP_TITLE,font=("Segoe UI",20,"bold")).pack(side="left")
        ttk.Label(top,text="Unabhängige verschlüsselte Dateisicherung",font=("Segoe UI",10)).pack(side="left",padx=16)
        ttk.Button(top,text="Beenden",command=self.exit_app).pack(side="right")
        ttk.Separator(top,orient="vertical").pack(side="right",fill="y",padx=8)
        ttk.Button(top,text="⚙ Einstellungen",command=self.open_settings).pack(side="right")

        sysbar=tk.Frame(self,bg="#f8fafc",highlightbackground="#e2e8f0",highlightthickness=1,padx=10,pady=4)
        sysbar.pack(fill="x",padx=12,pady=(2,6))
        tk.Label(sysbar,text="Systemstatus",bg="#f8fafc",fg="#475569",font=("Segoe UI",8,"bold")).pack(side="left",padx=(0,10))
        self.indicators={}
        specs=[("neon","Neon",True),("b2","B2",True),("vault","Tresor",False),("scheduler","Scheduler",False),("verify","Verify/TÜV",True),("kc","KC Kommunikation",True)]
        for key,label,traffic in specs:
            ind=StatusIndicator(sysbar,label,command=lambda k=key:self.open_system_status(k),traffic=traffic)
            ind.pack(side="left",padx=(0,14))
            self.indicators[key]=ind
        ttk.Button(sysbar,text="↻ Status",command=self.refresh_system_status).pack(side="right")
        tk.Label(sysbar,text="oben = Zustand · unten = Datenverkehr",bg="#f8fafc",fg="#64748b",font=("Segoe UI",7)).pack(side="right",padx=(0,10))

        st=ttk.Frame(self,padding=(12,0,12,10)); st.pack(fill="x")
        self.lbl_target=ttk.Label(st,text="Ziel: –"); self.lbl_target.pack(side="left",padx=(0,22))
        self.lbl_conn=ttk.Label(st,text="Verbindung: –"); self.lbl_conn.pack(side="left",padx=(0,22))
        self.lbl_size=ttk.Label(st,text="Speicher: –"); self.lbl_size.pack(side="left",padx=(0,22))
        self.lbl_guard=ttk.Label(st,text="Schutz: –"); self.lbl_guard.pack(side="left")

        act1=ttk.LabelFrame(self,text="Sicherung",padding=(10,6)); act1.pack(fill="x",padx=12,pady=(0,6))
        select_row=ttk.Frame(act1); select_row.pack(fill="x")
        self.btn_pick_files=ttk.Button(select_row,text="＋ Dateien",command=self.pick_files); self.btn_pick_files.pack(side="left",padx=(0,6))
        self.btn_pick_folder=ttk.Button(select_row,text="＋ Ordner",command=self.pick_folder); self.btn_pick_folder.pack(side="left",padx=(0,6))
        self.btn_clear=ttk.Button(select_row,text="Auswahl leeren",command=self.clear); self.btn_clear.pack(side="left",padx=(0,16))
        ttk.Label(select_row,text="Sicherungsart:").pack(side="left",padx=(0,4))
        self.mode_combo=ttk.Combobox(select_row,textvariable=self.mode_var,state="readonly",width=24,values=["Empfohlen (automatisch)","Vollständig","Inkrementell","Schnell"])
        self.mode_combo.pack(side="left",padx=(0,10))

        ttk.Label(select_row,text="Speicherziel:").pack(side="left",padx=(0,4))
        self.payload_combo=ttk.Combobox(select_row,textvariable=self.payload_var,state="readonly",width=28,values=list(PAYLOAD_DISPLAY_TO_CODE.keys()))
        self.payload_combo.pack(side="left",padx=(0,10))
        self.payload_combo.bind("<<ComboboxSelected>>",lambda e:self.update_backup_recommendation())
        self.btn_backup=tk.Button(select_row,text="▶ Backup starten",command=self.start_backup,font=("Segoe UI",9,"bold"),relief="flat",bd=0,padx=14,pady=5,cursor="hand2"); self.btn_backup.pack(side="left",padx=(0,8))
        self.btn_one_touch=ttk.Button(select_row,text="⚡ One-Touch",command=self.run_default_one_touch); self.btn_one_touch.pack(side="left")

        act2=ttk.LabelFrame(self,text="Übersicht / Wiederherstellung",padding=(10,6)); act2.pack(fill="x",padx=12,pady=(0,6))
        ttk.Button(act2,text="📊 Dashboard",command=self.open_dashboard).pack(side="left",padx=(0,6))
        ttk.Button(act2,text="☁ Backup-Explorer",command=self.open_explorer).pack(side="left",padx=(0,6))
        ttk.Button(act2,text="✓ Letzte Sicherung prüfen",command=self.open_verify_last).pack(side="left",padx=(0,6))
        ttk.Button(act2,text="Letzter Report",command=self.open_last_report).pack(side="left",padx=(0,6))
        ttk.Button(act2,text="Historie",command=self.open_history).pack(side="left",padx=(0,6))
        ttk.Button(act2,text="TÜV / Core prüfen",command=self.open_tuev).pack(side="left")

        reco=ttk.Frame(self,padding=(12,0,12,8)); reco.pack(fill="x")
        self.lbl_recommend=ttk.Label(reco,text="Empfehlung: Dateien auswählen – danach bewertet das Programm die nächste Sicherung.")
        self.lbl_recommend.pack(side="left")

        tree_frame=ttk.Frame(self)
        tree_frame.pack(fill="both",expand=True,padx=12,pady=(0,10))
        self.tree=ttk.Treeview(tree_frame,columns=("name","path","size","type"),show="headings",height=18)
        for c,t,w in [("name","Datei",250),("path","Pfad",570),("size","Größe",110),("type","Typ",90)]:
            self.tree.heading(c,text=t); self.tree.column(c,width=w,anchor="e" if c=="size" else "w")
        tree_y=ttk.Scrollbar(tree_frame,orient="vertical",command=self.tree.yview)
        tree_x=ttk.Scrollbar(tree_frame,orient="horizontal",command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_y.set,xscrollcommand=tree_x.set)
        self.tree.grid(row=0,column=0,sticky="nsew")
        tree_y.grid(row=0,column=1,sticky="ns")
        tree_x.grid(row=1,column=0,sticky="ew")
        tree_frame.rowconfigure(0,weight=1); tree_frame.columnconfigure(0,weight=1)
        bottom=ttk.LabelFrame(self,text="Live-Status",padding=(10,8)); bottom.pack(fill="x",padx=12,pady=(0,12))
        live_left=ttk.Frame(bottom); live_left.pack(side="left",padx=(0,12))
        self.gauge=tk.Canvas(live_left,width=92,height=92,highlightthickness=0)
        self.gauge.pack()
        live_right=ttk.Frame(bottom); live_right.pack(side="left",fill="x",expand=True)
        self.progress=ttk.Progressbar(live_right,mode="determinate",maximum=100); self.progress.pack(fill="x")
        self.lbl_progress=ttk.Label(live_right,text="Bereit."); self.lbl_progress.pack(anchor="w",pady=(5,2))
        stats=ttk.Frame(live_right); stats.pack(fill="x",pady=(2,0))
        self.lbl_live_files=ttk.Label(stats,text="Dateien: –"); self.lbl_live_files.pack(side="left",padx=(0,18))
        self.lbl_live_data=ttk.Label(stats,text="Daten: –"); self.lbl_live_data.pack(side="left",padx=(0,18))
        self.lbl_live_speed=ttk.Label(stats,text="Tempo: –"); self.lbl_live_speed.pack(side="left",padx=(0,18))
        self.lbl_live_eta=ttk.Label(stats,text="Restzeit: –"); self.lbl_live_eta.pack(side="left",padx=(0,18))
        self.lbl_live_elapsed=ttk.Label(stats,text="Laufzeit: –"); self.lbl_live_elapsed.pack(side="left")
        runctl=ttk.Frame(live_right); runctl.pack(fill="x",pady=(7,0))
        self.lbl_live_control=ttk.Label(runctl,text="Pause/Abbruch: nur während einer laufenden Sicherung aktiv.")
        self.lbl_live_control.pack(side="left")
        self.btn_abort=ttk.Button(runctl,text="■ Abbrechen",command=self.cancel_backup,state="disabled")
        self.btn_abort.pack(side="right",padx=(6,0))
        self.btn_pause=ttk.Button(runctl,text="⏸ Pause",command=self.toggle_pause,state="disabled")
        self.btn_pause.pack(side="right")
        self._draw_gauge(0)

    def _write_start_protocol(self, event, detail=""):
        if not self.store.data.get("start_protocol_enabled", True):
            return
        try:
            path = self.store.path.parent / "STARTPROTOKOLL.log"
            stamp = datetime.now().astimezone().isoformat(timespec="seconds")
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp}\t{event}\t{detail}\n")
        except Exception:
            pass

    def exit_app(self):
        if self._backup_running:
            if not messagebox.askyesno(APP_TITLE, "Eine Sicherung läuft noch. Programm wirklich schließen?\n\nEin harter Programmabbruch ist nicht empfohlen.", parent=self):
                return
        elif not messagebox.askyesno(APP_TITLE, "PC Backup Vault wirklich beenden?", parent=self):
            return
        self._write_start_protocol("ENDE", "Programm beendet")
        try:
            if self._status_unsubscribe: self._status_unsubscribe()
        except Exception: pass
        try:
            lock=getattr(self,"_instance_lock",None)
            if lock: lock.release(); self._instance_lock=None
        except Exception: pass
        self.destroy()

    def _on_status_bus(self, service, event, payload):
        def apply():
            ind = getattr(self, "indicators", {}).get(service)
            if not ind: return
            if event == "activity":
                ind.pulse()
            elif event == "state":
                ind.set_state(payload.get("level"), payload.get("detail", ""))
                self._system_states[service] = dict(payload)
        try: self.after(0, apply)
        except Exception: pass

    def _set_indicator(self, key, level, detail=""):
        ind = getattr(self, "indicators", {}).get(key)
        if ind: ind.set_state(level, detail)
        self._system_states[key] = {"level": level, "detail": detail, "at": time.time()}
        if key in ("neon","b2","vault"):
            try: self._update_backup_button_state()
            except Exception: pass

    def refresh_system_status(self):
        # Local states first; online checks run in a worker.
        self._set_indicator("vault", "ok" if self.master_key() else "error", "Recovery-/Master-Key im Windows-Tresor" if self.master_key() else "Master-Key fehlt")
        plans = [p for p in self.store.data.get("plans", []) if p.get("enabled") and p.get("schedule_type") != "MANUAL"]
        self._set_indicator("scheduler", "checking" if plans else "off", "Scheduler wird geprüft" if plans else "Keine automatische Aufgabe konfiguriert")
        kc_cfg = self.store.data.get("kc_communication") or {}
        if not kc_cfg.get("enabled"):
            self._set_indicator("kc", "off", "KC Kommunikation deaktiviert")
        elif not self.store.get_kc_device_token():
            self._set_indicator("kc", "warn", "Gerät noch nicht registriert / gekoppelt")
        else:
            self._set_indicator("kc", "checking", "KC-Gerätekopplung wird geprüft")

        if guard_active(self.store.data):
            self._set_indicator("neon", "warn", "Weihnachtsmarkt-Schutz – Online-Test ausgesetzt")
            self._set_indicator("b2", "warn", "Weihnachtsmarkt-Schutz – Online-Test ausgesetzt")
            return
        self._set_indicator("neon", "checking", "Verbindung wird geprüft")
        b2cfg = self.store.get_b2_runtime_config()
        self._set_indicator("b2", "checking" if b2cfg.get("configured") else "off", "Verbindung wird geprüft" if b2cfg.get("configured") else "B2 nicht vollständig eingerichtet")

        def work():
            dsn = self.active_dsn()
            if dsn:
                ok, msg = test_connection(dsn)
                self.after(0, lambda o=ok,m=msg: self._set_indicator("neon", "ok" if o else "error", m))
                if ok:
                    try:
                        vr = recent_verifications(dsn, 1)
                        tv = recent_tuev_checks(dsn, 50)
                        latest_tv=[]
                        if tv:
                            ts=tv[0][0]; latest_tv=[row for row in tv if row[0] == ts]
                        tv_fail=any(row[3] == "FAIL" for row in latest_tv); tv_warn=any(row[3] == "WARN" for row in latest_tv)
                        if vr and vr[0][5] == "FAIL": level,detail="error","Letzte Verifizierung: FAIL"
                        elif tv_fail: level,detail="error","Letzter TÜV enthält Fehler"
                        elif (vr and vr[0][5] == "WARN") or tv_warn: level,detail="warn","Letzte Integritätsprüfung mit Warnung"
                        elif vr or tv: level,detail="ok","Letzte Integritätsprüfung ohne Fehler"
                        else: level,detail="warn","Noch kein Verify/TÜV-Nachweis"
                        self.after(0, lambda l=level,d=detail: self._set_indicator("verify", l, d))
                    except Exception as e:
                        self.after(0, lambda m=str(e): self._set_indicator("verify", "warn", m))
            else:
                self.after(0, lambda: self._set_indicator("neon", "error", "Datenbankzugang fehlt"))
                self.after(0, lambda: self._set_indicator("verify", "off", "Ohne Neon nicht prüfbar"))
            if b2cfg.get("configured"):
                store = make_b2_store(b2cfg)
                ok,msg = store.ping() if store else (False,"B2 nicht eingerichtet")
                self.after(0, lambda o=ok,m=msg: self._set_indicator("b2", "ok" if o else "error", m))
            if plans:
                ok,msg = task_status(plans[0])
                self.after(0, lambda o=ok,m=msg: self._set_indicator("scheduler", "ok" if o else "warn", "Windows-Aufgabe vorhanden" if o else m.splitlines()[0] if m else "Aufgabe nicht gefunden"))
            if kc_cfg.get("enabled"):
                client = make_kc_client(self.store)
                if client:
                    ok,msg = client.test()
                    level = "ok" if ok else ("warn" if "pending" in msg.lower() or "pairing" in msg.lower() else "error")
                    self.after(0, lambda l=level,m=msg: self._set_indicator("kc", l, m))
                else:
                    self.after(0, lambda: self._set_indicator("kc", "warn", "Gerät noch nicht registriert"))
        threading.Thread(target=work, daemon=True).start()

    def open_system_status(self, key):
        names={"neon":"Neon / Metadatenbank","b2":"Backblaze B2","vault":"Lokaler Tresor","scheduler":"Windows Scheduler","verify":"Verify / TÜV","kc":"KC Kommunikation"}
        win=tk.Toplevel(self); win.title(f"Systemstatus – {names.get(key,key)}"); win.geometry("640x330"); win.transient(self)
        box=ttk.Frame(win,padding=14); box.pack(fill="both",expand=True)
        ttk.Label(box,text=names.get(key,key),font=("Segoe UI",16,"bold")).pack(anchor="w")
        statebox=ttk.LabelFrame(box,text="Aktueller Zustand",padding=10); statebox.pack(fill="x",pady=(12,8))
        st=self._system_states.get(key,{})
        level=st.get("level",getattr(self.indicators.get(key),"level","unknown")); detail=st.get("detail",getattr(self.indicators.get(key),"detail","–"))
        lbl=ttk.Label(statebox,text=f"Status: {str(level).upper()}\n{detail}",justify="left",wraplength=580); lbl.pack(anchor="w")
        ttk.Label(box,text="Die obere LED zeigt den Zustand. Die kleine untere LED blinkt bei echtem Datenverkehr.",wraplength=590).pack(anchor="w",pady=(0,8))
        if key=="kc":
            hist=kc_recent_history(1)
            if hist:
                h=hist[0]
                last=f"Letzter Versand: {h.get('delivery','–')}"
                if h.get("channels"): last+=f" · Kanäle: {', '.join(h.get('channels') or [])}"
                detail_last=h.get("result") or h.get("error") or ""
                if detail_last: last+=f"\n{detail_last}"
                ttk.Label(box,text=last,justify="left",wraplength=590).pack(anchor="w",pady=(0,8))
        actions=ttk.Frame(box); actions.pack(fill="x",pady=(8,0))
        def retest():
            lbl.config(text="Status: PRÜFUNG LÄUFT …")
            self.refresh_system_status()
            def later():
                st2=self._system_states.get(key,{})
                lbl.config(text=f"Status: {str(st2.get('level','unknown')).upper()}\n{st2.get('detail','–')}")
            win.after(2500,later)
        ttk.Button(actions,text="Verbindung testen",command=retest).pack(side="left")
        if key=="kc":
            def channel_test(channel):
                lbl.config(text=f"Status: TEST LÄUFT …\n{channel.upper()} wird einzeln geprüft.")
                def worker():
                    client=make_kc_client(self.store)
                    if not client:
                        ok,msg=False,"KC Kommunikation ist nicht vollständig eingerichtet."
                    else:
                        ok,msg=client.diagnose_channel(channel)
                    def done():
                        st2=self._system_states.get("kc",{})
                        level=st2.get("level","ok" if ok else "error")
                        lbl.config(text=f"Status: {str(level).upper()}\n{msg}")
                    self.after(0,done)
                threading.Thread(target=worker,daemon=True).start()
            ttk.Button(actions,text="Push testen",command=lambda:channel_test("push")).pack(side="left",padx=(6,0))
            ttk.Button(actions,text="E-Mail testen",command=lambda:channel_test("email")).pack(side="left",padx=(6,0))
            ttk.Button(actions,text="KC Einstellungen",command=lambda:[win.destroy(),self.open_settings(tab="communication")]).pack(side="left",padx=6)
        ttk.Button(actions,text="Schließen",command=win.destroy).pack(side="right")

    def notify_kc(self, event, title, message, severity="INFO", details=None):
        cfg=self.store.data.get("kc_communication") or {}; events=cfg.get("events") or {}
        event_key=EVENT_ALIASES.get(event,event)
        if not cfg.get("enabled") or not events.get(event_key, False): return
        client=make_kc_client(self.store)
        if not client: return
        def work(): client.send_event(event_key, title, message, severity, details or {})
        threading.Thread(target=work,daemon=True).start()

    def pick_files(self): self._add(filedialog.askopenfilenames(title="Dateien für Backup auswählen"))
    def pick_folder(self):
        p=filedialog.askdirectory(title="Ordner für Backup auswählen")
        if p:self._add([p])
    def _add(self,paths):
        self.selected=collect_paths([str(x) for x in self.selected]+list(paths)); self._refresh_tree(); self.update_backup_recommendation(); self._update_backup_button_state()
    def clear(self):
        self.selected=[]; self._refresh_tree(); self.lbl_recommend.config(text="Empfehlung: Dateien auswählen – danach bewertet das Programm die nächste Sicherung."); self._update_backup_button_state()
    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children()); total=0
        for p in self.selected:
            try: sz=p.stat().st_size
            except Exception: continue
            total+=sz; self.tree.insert("","end",values=(p.name,str(p.parent),human_size(sz),p.suffix.lower() or "–"))
        self.lbl_progress.config(text=f"{len(self.selected)} Datei(en), {human_size(total)} ausgewählt.")

    def _stop_backup_button_blink(self):
        after_id = getattr(self, "_backup_button_blink_after", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        self._backup_button_blink_after = None
        self._backup_button_blink_phase = False

    def _pause_button_blink_tick(self):
        if not (getattr(self, "_backup_running", False) and getattr(self, "_backup_paused", False)):
            self._stop_backup_button_blink()
            self._update_backup_button_state()
            return
        self._backup_button_blink_phase = not bool(getattr(self, "_backup_button_blink_phase", False))
        bg = "#f59e0b" if self._backup_button_blink_phase else "#fde047"
        fg = "#111827"
        try:
            self.btn_backup.configure(
                text="⏸ PAUSE – Sicherung pausiert",
                bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
                disabledforeground=fg,
            )
            self._backup_button_blink_after = self.after(550, self._pause_button_blink_tick)
        except Exception:
            self._backup_button_blink_after = None

    def _start_backup_button_blink(self):
        if getattr(self, "_backup_button_blink_after", None) is None:
            self._backup_button_blink_phase = False
            self._pause_button_blink_tick()

    def _update_backup_button_state(self):
        if not hasattr(self,"btn_backup"):
            return
        control = getattr(self, "_backup_control", None)
        if self._backup_running and control is not None and getattr(control, "cancelled", False):
            level,detail="cancelling","Abbruch läuft"
        elif self._backup_running and self._backup_paused:
            level,detail="paused","Sicherung pausiert"
        elif self._backup_running:
            level,detail="running","Sicherung läuft"
        elif not self.selected:
            level,detail="warn","Bitte Dateien oder Ordner auswählen"
        elif guard_active(self.store.data):
            level,detail="error","Weihnachtsmarkt-Schutz blockiert Online-Sicherungen"
        elif not self.active_profile() or not self.active_dsn():
            level,detail="error","Neon-Zugang ist nicht eingerichtet"
        elif not self.master_key():
            level,detail="error","Lokaler Tresorschlüssel fehlt"
        else:
            effective=self._effective_payload_code()
            total=sum((x.stat().st_size for x in self.selected if x.exists()),0)
            max_run=int(self.store.data.get("max_run_mb",100))*1024*1024
            if effective=="B2_MISSING": level,detail="error","Backblaze B2 ist nicht vollständig eingerichtet"
            elif effective=="NEON" and total>max_run: level,detail="error","Auswahl überschreitet das Neon-Kleinbackup-Limit"
            else:
                ns=(self._system_states.get("neon") or {}).get("level")
                bs=(self._system_states.get("b2") or {}).get("level")
                if ns=="error": level,detail="error","Neon-Verbindung fehlerhaft"
                elif effective=="B2" and bs=="error": level,detail="error","B2-Verbindung fehlerhaft"
                elif ns in (None,"unknown","checking") or (effective=="B2" and bs in (None,"unknown","checking")):
                    level,detail="warn","Verbindungen werden noch geprüft"
                else: level,detail="ok","Bereit für Sicherung"
        colors={
            "ok":("#16a34a","#ffffff","#15803d"), "warn":("#f59e0b","#111827","#d97706"),
            "error":("#dc2626","#ffffff","#b91c1c"), "running":("#2563eb","#ffffff","#1d4ed8"),
            "paused":("#f59e0b","#111827","#fde047"), "cancelling":("#dc2626","#ffffff","#991b1b"),
        }
        bg,fg,active=colors[level]
        if level != "paused":
            self._stop_backup_button_blink()
        self.btn_backup.configure(bg=bg,fg=fg,activebackground=active,activeforeground=fg,disabledforeground=fg)
        try:
            label={
                "running":"▶ Sicherung läuft …",
                "paused":"⏸ PAUSE – Sicherung pausiert",
                "cancelling":"■ Abbruch läuft …",
            }.get(level,"▶ Backup starten")
            self.btn_backup.configure(text=label)
        except Exception:
            pass
        self._backup_button_detail=detail
        if level == "paused":
            self._start_backup_button_blink()

    def refresh_status(self):
        p=self.active_profile(); self.lbl_target.config(text=f"Ziel: {p['name'] if p else 'nicht eingerichtet'}")
        self.lbl_guard.config(text="Schutz: 04.–13.12. EIN" if self.store.data.get("christmas_guard",True) else "Schutz: AUS")
        dsn=self.active_dsn(); self._update_backup_button_state()
        if guard_active(self.store.data):
            self.lbl_conn.config(text="Verbindung: Schutzmodus – kein Neon-Zugriff"); self.lbl_size.config(text="Speicher: nicht abgefragt"); return
        if not dsn:
            self.lbl_conn.config(text="Verbindung: Zugangsdaten fehlen"); self.lbl_size.config(text="Speicher: –"); self._update_backup_button_state(); return
        def work():
            ok,_=test_connection(dsn); size=None
            if ok:
                try:size=database_size(dsn)
                except Exception:pass
            def done():
                self.lbl_conn.config(text=f"Verbindung: {'OK' if ok else 'Fehler'}")
                self._set_indicator("neon","ok" if ok else "error","Verbindung OK" if ok else "Verbindung fehlgeschlagen")
                if size is not None:self.lbl_size.config(text=f"Speicher: {human_size(size)}")
                self._update_backup_button_state()
            self.after(0,done)
        threading.Thread(target=work,daemon=True).start()

    def _fmt_time(self, seconds):
        if seconds is None or seconds < 0:
            return "–"
        seconds = int(seconds)
        h, rem = divmod(seconds, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"

    def _safe_tk_color(self, candidate, fallback):
        """Return a Tk color that is valid on the current Windows/Tk build."""
        try:
            self.winfo_rgb(candidate)
            return candidate
        except tk.TclError:
            return fallback

    def _draw_gauge(self, percent):
        pct=max(0.0,min(100.0,float(percent or 0)))
        self.gauge.delete("all")
        track=self._safe_tk_color("SystemButtonShadow", "#c8cdd4")
        accent=self._safe_tk_color("SystemHighlight", "#2574d8")
        textc=self._safe_tk_color("SystemWindowText", "#202124")
        self.gauge.create_oval(9,9,83,83,outline=track,width=8)
        if pct > 0:
            self.gauge.create_arc(9,9,83,83,start=90,extent=-(pct*3.6),style="arc",outline=accent,width=8)
        self.gauge.create_text(46,39,text=f"{pct:.0f}%",font=("Segoe UI",14,"bold"),fill=textc)
        self.gauge.create_text(46,58,text="Fortschritt",font=("Segoe UI",8),fill=textc)

    def _reset_live_progress(self, total_files=0, total_bytes=0):
        self._live_phase=None; self._live_last_t=None; self._live_last_bytes=0; self._live_speed=0.0; self._live_last_draw=0.0
        self.progress.configure(maximum=100,value=0)
        self._draw_gauge(0)
        self.lbl_live_files.config(text=f"Dateien: 0 / {total_files}" if total_files else "Dateien: –")
        self.lbl_live_data.config(text=f"Daten: 0 B / {human_size(total_bytes)}" if total_bytes else "Daten: –")
        self.lbl_live_speed.config(text="Tempo: –")
        self.lbl_live_eta.config(text="Restzeit: –")
        self.lbl_live_elapsed.config(text="Laufzeit: 00:00")

    def _progress(self,d,t,msg,metrics=None):
        if not metrics:
            self.progress.configure(maximum=max(1,t),value=d)
            self.lbl_progress.config(text=msg)
            return
        now=time.monotonic()
        phase=metrics.get("phase") or "Sicherung"
        bdone=max(0,int(metrics.get("bytes_done") or 0)); btotal=max(0,int(metrics.get("bytes_total") or 0))
        if phase != self._live_phase or self._live_last_t is None or bdone < self._live_last_bytes:
            self._live_phase=phase; self._live_last_t=now; self._live_last_bytes=bdone; self._live_speed=0.0
        else:
            dt=now-self._live_last_t
            if dt >= 0.15:
                inst=max(0,bdone-self._live_last_bytes)/dt
                self._live_speed=inst if self._live_speed <= 0 else (0.75*self._live_speed + 0.25*inst)
                self._live_last_t=now; self._live_last_bytes=bdone
        pct=(bdone/btotal*100.0) if btotal else ((d/max(1,t))*100.0)
        force=(pct>=99.9 or phase != getattr(self,"_live_draw_phase",None) or now-self._live_last_draw>=0.20)
        if not force:
            return
        self._live_last_draw=now; self._live_draw_phase=phase
        remaining=max(0,btotal-bdone)
        eta=(remaining/self._live_speed) if self._live_speed>1024 else None
        elapsed=float(metrics.get("elapsed") or 0)
        self.progress.configure(maximum=100,value=min(100,pct))
        self._draw_gauge(pct)
        self.lbl_progress.config(text=f"{phase}: {msg}")
        self.lbl_live_files.config(text=f"Dateien: {metrics.get('files_done',d)} / {metrics.get('files_total',t)}")
        self.lbl_live_data.config(text=f"Daten: {human_size(bdone)} / {human_size(btotal)}")
        self.lbl_live_speed.config(text=f"Tempo: {human_size(self._live_speed)}/s" if self._live_speed>0 else "Tempo: –")
        self.lbl_live_eta.config(text=f"Restzeit: ca. {self._fmt_time(eta)}" if eta is not None else "Restzeit: wird berechnet …")
        self.lbl_live_elapsed.config(text=f"Laufzeit: {self._fmt_time(elapsed)}")

    def _set_backup_running(self, running: bool):
        self._backup_running = bool(running)
        state = "disabled" if running else "normal"
        for btn in (self.btn_pick_files, self.btn_pick_folder, self.btn_clear, self.btn_backup, self.btn_one_touch): btn.configure(state=state)
        self.mode_combo.configure(state="disabled" if running else "readonly")
        self.payload_combo.configure(state="disabled" if running else "readonly")
        self.btn_pause.configure(state="normal" if running else "disabled"); self.btn_abort.configure(state="normal" if running else "disabled")
        if not running:
            self._backup_control=None; self._backup_paused=False
            self.btn_pause.configure(text="⏸ Pause"); self.btn_abort.configure(text="■ Abbrechen")
            self.lbl_live_control.config(text="Pause/Abbruch: nur während einer laufenden Sicherung aktiv.")
        self._update_backup_button_state()

    def _begin_backup_control(self):
        self._backup_control = BackupControl()
        self._backup_paused = False
        self._set_backup_running(True)
        self.lbl_live_control.config(text="Steuerung aktiv – Pause wirkt am nächsten sicheren Datei-/Uploadblock.")
        return self._backup_control

    def toggle_pause(self):
        control = self._backup_control
        if not self._backup_running or control is None or control.cancelled:
            return
        if self._backup_paused:
            control.resume()
            self._backup_paused = False
            self.btn_pause.configure(text="⏸ Pause")
            self.lbl_live_control.config(text="Fortgesetzt – Sicherung läuft weiter.")
            self.lbl_progress.config(text="Fortgesetzt – Sicherung läuft weiter …")
            self._update_backup_button_state()
        else:
            control.pause()
            self._backup_paused = True
            self.btn_pause.configure(text="▶ Fortsetzen")
            self.lbl_live_control.config(text="PAUSIERT – aktuelle sichere Operation wird noch abgeschlossen.")
            self.lbl_progress.config(text="Pausiert – zum Weiterarbeiten 'Fortsetzen' drücken.")
            self.lbl_live_eta.config(text="Restzeit: pausiert")
            self._update_backup_button_state()

    def cancel_backup(self):
        control = self._backup_control
        if not self._backup_running or control is None or control.cancelled:
            return
        if not messagebox.askyesno(
            "Backup abbrechen",
            "Soll die laufende Sicherung wirklich abgebrochen werden?\n\n"
            "Der aktuelle sichere Datei-/Uploadblock wird noch abgeschlossen. "
            "Danach wird der unvollständige Lauf zurückgerollt.",
            parent=self,
        ):
            return
        control.cancel()
        self._backup_paused = False
        self.btn_pause.configure(state="disabled", text="⏸ Pause")
        self.btn_abort.configure(state="disabled", text="Abbruch läuft …")
        self.lbl_live_control.config(text="ABBRUCH ANGEFORDERT – sichere Bereinigung läuft …")
        self.lbl_progress.config(text="Abbruch angefordert – bitte kurz warten …")
        self.lbl_live_eta.config(text="Restzeit: Abbruch läuft")
        self._update_backup_button_state()

    def _selected_mode_code(self):
        return {
            "Empfohlen (automatisch)":"AUTO",
            "Vollständig":"FULL",
            "Inkrementell":"INCREMENTAL",
            "Schnell":"QUICK",
        }.get(self.mode_var.get(),"AUTO")

    def _selected_payload_code(self):
        return PAYLOAD_DISPLAY_TO_CODE.get(self.payload_var.get(), "AUTO")

    def _effective_payload_code(self):
        requested=self._selected_payload_code()
        b2cfg=self.store.get_b2_runtime_config()
        if requested=="B2":
            return "B2" if b2cfg.get("configured") else "B2_MISSING"
        if requested=="AUTO":
            return "B2" if b2cfg.get("configured") else "NEON"
        return "NEON"

    def update_backup_recommendation(self):
        if not self.selected:
            return
        total_bytes = sum((x.stat().st_size for x in self.selected if x.exists()), 0)
        max_run = int(self.store.data.get("max_run_mb", 100)) * 1024 * 1024
        effective_payload=self._effective_payload_code()
        if effective_payload=="B2_MISSING":
            self.lbl_recommend.config(text="Speicherziel: Backblaze B2 gewählt, aber noch nicht eingerichtet. Bitte Zahnrad → Dateispeicher öffnen.")
            return
        if effective_payload=="NEON" and total_bytes > max_run:
            self.lbl_recommend.config(
                text=f"Speicherempfehlung: {human_size(total_bytes)} ist zu groß für Neon-Kleinbackup ({human_size(max_run)}). Backblaze B2 einrichten/auswählen."
            )
            return
        if guard_active(self.store.data):
            self.lbl_recommend.config(text="Empfehlung: Weihnachtsmarkt-Schutz aktiv – keine Online-Auswertung.")
            return
        dsn=self.active_dsn()
        if not dsn:
            self.lbl_recommend.config(text="Empfehlung: Datenbankzugang noch nicht eingerichtet.")
            return
        self.lbl_recommend.config(text="Empfehlung wird berechnet …")
        def work():
            try:
                mode,reason=recommend_backup_mode(dsn,self.selected)
                label={"FULL":"Vollständig","INCREMENTAL":"Inkrementell","QUICK":"Schnell"}.get(mode,mode)
                target_hint="Backblaze B2 + Neon-Core" if self._effective_payload_code()=="B2" else "Neon-Kleinbackup"
                self.after(0,lambda:self.lbl_recommend.config(text=f"Empfehlung: {label} – Speicher: {target_hint} – {reason}"))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda m=msg: self.lbl_recommend.config(text=f"Empfehlung nicht verfügbar: {m}"))
        threading.Thread(target=work,daemon=True).start()

    def start_backup(self, resume_checkpoint=None):
        resume_payload=dict(getattr(resume_checkpoint,"payload",{}) or {}) if resume_checkpoint else {}
        if resume_checkpoint:
            self.selected=collect_paths(resume_payload.get("paths") or [])
            self._refresh_tree()
        if not self.selected: messagebox.showwarning(APP_TITLE,"Bitte zuerst Dateien oder einen Ordner auswählen."); self._update_backup_button_state(); return
        p=self.active_profile(); dsn=self.active_dsn()
        if not p or not dsn: messagebox.showwarning(APP_TITLE,"Bitte zuerst im Zahnrad die Datenbank-Zugangsdaten hinterlegen."); self.open_settings(); return
        total_bytes=sum((x.stat().st_size for x in self.selected if x.exists()),0); max_run=int(self.store.data.get("max_run_mb",100))*1024*1024
        effective_payload=self._effective_payload_code()
        if resume_checkpoint and resume_payload.get("payload_target") in ("B2","NEON"):
            effective_payload=resume_payload.get("payload_target")
        if effective_payload=="B2_MISSING":
            messagebox.showwarning("Backblaze B2 noch nicht eingerichtet","Bitte im Zahnrad unter 'Dateispeicher' Bucket, Endpoint und B2-Zugangsdaten eintragen und die Verbindung testen."); self.open_settings(tab="storage"); return
        if effective_payload=="NEON" and total_bytes>max_run:
            messagebox.showwarning("Sicherheitssperre",f"Die Auswahl ist {human_size(total_bytes)} groß.\n\nNeon ist hier nur für Kleinbackups bis {human_size(max_run)} vorgesehen.\nFür größere Sicherungen bitte Backblaze B2 einrichten oder als Speicherziel wählen.\n\nEs wurde noch kein Backup gestartet."); return
        paths=list(self.selected); resume_from=str(resume_payload.get("job_id") or "") or None
        mode="QUICK" if resume_from else (resume_payload.get("backup_mode") if resume_checkpoint else self._selected_mode_code())
        payload=(resume_payload.get("payload_target") if resume_checkpoint else self._selected_payload_code()) or "AUTO"
        save_manual_checkpoint(self.master_key(),paths,mode,payload,resume_from)
        self._reset_live_progress(len(paths),total_bytes); control=self._begin_backup_control()
        def cb(d,t,m,metrics=None): self.after(0,lambda:self._progress(d,t,m,metrics))
        def recovery_hook(event,payload_):
            if event=="job_created": update_job_id(self.master_key(),payload_.get("job_id",""))
        def work():
            try:
                r=backup_files(dsn,self.master_key(),p,self.store.data,paths,cb,backup_mode=mode,payload_target=payload,object_store_config=self.store.get_b2_runtime_config(),control=control,resume_from_job_id=resume_from,recovery_hook=recovery_hook)
                clear_checkpoint()
                verification=None
                if self.store.data.get("auto_quick_verify_after_backup",True):
                    try: verification=verify_job(dsn,self.master_key(),r.get("job_id"),mode="QUICK",object_store_config=self.store.get_b2_runtime_config(),progress=cb,control=control,app_version=APP_VERSION)
                    except BackupCancelled: verification=None; self.after(0,lambda:self.lbl_progress.config(text="Backup erfolgreich – automatische Verifizierung wurde abgebrochen."))
                job_id=r.get("job_id"); self.after(0,lambda j=job_id: JobReportWindow(self,j))
                self.after(0,lambda:self.lbl_progress.config(text="Backup abgeschlossen – Report erstellt." if not verification or verification.result=="PASS" else "Backup abgeschlossen – Verifizierung mit Fehlern; Report prüfen."))
                self.notify_kc("backup_resumed" if resume_from else "backup_success", "Backup fortgesetzt und erfolgreich" if resume_from else "Backup erfolgreich", f"Backup-Job {job_id} wurde erfolgreich abgeschlossen.", "INFO", {"job_id":str(job_id),"files":r.get("files"),"stored_bytes":r.get("stored_bytes"),"mode":r.get("mode")})
                self.after(0,self.refresh_status); self.after(0,self.refresh_system_status)
            except BackupCancelled:
                clear_checkpoint(); self.notify_kc("backup_cancelled","Backup abgebrochen","Die laufende Sicherung wurde vom Benutzer abgebrochen.","WARN")
                self.after(0,lambda:messagebox.showinfo(APP_TITLE,"Backup wurde abgebrochen.\n\nDer unvollständige Lauf wurde sicher beendet und zurückgerollt.")); self.after(0,lambda:self.lbl_progress.config(text="Backup abgebrochen – unvollständiger Lauf bereinigt."))
            except (LimitBlocked,ChristmasGuard) as e:
                clear_checkpoint(); msg=str(e); self.notify_kc("capacity_blocked","Backup blockiert",msg,"WARN"); self.after(0,lambda m=msg:messagebox.showwarning("Sicherheitssperre",m))
            except Exception as e:
                clear_checkpoint(); msg=str(e); self.notify_kc("backup_failed","Backup fehlgeschlagen",msg,"ERROR"); self.after(0,lambda m=msg:messagebox.showerror(APP_TITLE,f"Backup fehlgeschlagen:\n{m}"))
            finally: self.after(0,lambda:self._set_backup_running(False))
        threading.Thread(target=work,daemon=True).start()

    def run_default_one_touch(self):
        plan=self.store.get_plan()
        if not plan:
            messagebox.showinfo(APP_TITLE,"Noch kein One‑Touch‑Plan vorhanden. Bitte im Zahnrad unter One‑Touch/Scheduler einen Plan anlegen."); self.open_settings(tab="plans"); return
        self.lbl_progress.config(text=f"One‑Touch läuft: {plan['name']}")
        self._reset_live_progress()
        control=self._begin_backup_control()
        def cb(d,t,m,metrics=None): self.after(0,lambda:self._progress(d,t,m,metrics))
        def work():
            try:
                r=run_plan(plan["id"],cb,control=control)
                job_id=r.get("job_id")
                self.after(0,lambda j=job_id: JobReportWindow(self,j) if j else None)
                self.after(0,lambda:self.lbl_progress.config(text=f"One‑Touch '{plan['name']}' abgeschlossen – Report erstellt."))
                self.notify_kc("backup_success", "One-Touch Backup erfolgreich", f"Plan {plan['name']} wurde abgeschlossen.", "INFO", {"job_id": str(job_id or ""), "plan": plan["name"]})
                self.after(0,self.refresh_status)
                self.after(0,self.refresh_system_status)
            except BackupCancelled:
                self.after(0, lambda: messagebox.showinfo(APP_TITLE, "One‑Touch wurde abgebrochen.\n\nDer unvollständige Lauf wurde sicher beendet."))
                self.after(0, lambda: self.lbl_progress.config(text="One‑Touch abgebrochen."))
            except Exception as e:
                msg = str(e)
                self.notify_kc("backup_failed", "One-Touch Backup fehlgeschlagen", msg, "ERROR", {"plan": plan.get("name")})
                self.after(0, lambda m=msg: messagebox.showerror(APP_TITLE, f"One‑Touch fehlgeschlagen:\n{m}"))
            finally:
                self.after(0, lambda: self._set_backup_running(False))
        threading.Thread(target=work,daemon=True).start()

    def check_interrupted_backup(self):
        if self._backup_running: return
        key=self.master_key()
        if not key: return
        try: cp=load_checkpoint(key)
        except Exception as e:
            messagebox.showwarning("Recovery-Checkpoint","Ein Recovery-Checkpoint ist vorhanden, konnte aber nicht entschlüsselt werden.\n\n"+str(e),parent=self); return
        if not cp: return
        dsn=self.active_dsn(); old_job=str(cp.payload.get("job_id") or "")
        try:
            if dsn and old_job: mark_interrupted_job(dsn,old_job)
        except Exception: pass
        self.notify_kc("backup_interrupted","Sicherung unterbrochen","Beim letzten Programmstart wurde eine nicht sauber beendete Sicherung erkannt.","WARN",{"job_id":old_job})
        if guard_active(self.store.data):
            messagebox.showwarning("Unterbrochene Sicherung","Eine unterbrochene Sicherung wurde erkannt. Wegen des Weihnachtsmarkt-Schutzes wird sie jetzt nicht fortgesetzt. Der Recovery-Checkpoint bleibt erhalten.",parent=self); return
        if self.store.data.get("auto_resume_interrupted",False):
            self._resume_checkpoint(cp); return
        answer=messagebox.askyesnocancel("Unterbrochene Sicherung erkannt","Der letzte Backup-Lauf wurde vermutlich durch Stromausfall, Neustart oder einen harten Programmabbruch beendet.\n\nJA = jetzt sicher fortsetzen\nNEIN = Recovery verwerfen\nABBRECHEN = später entscheiden\n\nBereits vollständig gespeicherte, unveränderte Dateien werden beim Fortsetzen übersprungen.",parent=self)
        if answer is True: self._resume_checkpoint(cp)
        elif answer is False:
            discard_recovery(dsn,old_job); self.lbl_progress.config(text="Unterbrochene Sicherung wurde verworfen.")

    def _resume_checkpoint(self, cp):
        if cp.kind=="PLAN" and cp.payload.get("plan_id"):
            plan_id=str(cp.payload.get("plan_id")); old_job=str(cp.payload.get("job_id") or "") or None
            self._reset_live_progress(); control=self._begin_backup_control()
            def cb(d,t,m,metrics=None): self.after(0,lambda:self._progress(d,t,m,metrics))
            def work():
                try:
                    result=run_plan(plan_id,progress=cb,control=control,resume_from_job_id=old_job); clear_checkpoint()
                    self.notify_kc("backup_resumed","Plan-Sicherung fortgesetzt",f"Plan wurde erfolgreich fortgesetzt.","INFO",{"job_id":result.get("job_id"),"planName":plan_id})
                    self.after(0,lambda:messagebox.showinfo(APP_TITLE,"Die unterbrochene Plan-Sicherung wurde erfolgreich fortgesetzt."))
                except BackupCancelled:
                    clear_checkpoint(); self.after(0,lambda:messagebox.showinfo(APP_TITLE,"Fortsetzung wurde abgebrochen."))
                except Exception as e:
                    clear_checkpoint(); msg=str(e); self.after(0,lambda m=msg:messagebox.showerror(APP_TITLE,f"Fortsetzung fehlgeschlagen:\n{m}"))
                finally:self.after(0,lambda:self._set_backup_running(False))
            threading.Thread(target=work,daemon=True).start()
        else:
            self.start_backup(resume_checkpoint=cp)

    def open_verify_last(self):
        if guard_active(self.store.data):
            messagebox.showwarning("Weihnachtsmarkt-Schutz","04.–13.12. sind Verifizierungszugriffe gesperrt.")
            return
        dsn=self.active_dsn()
        if not dsn:
            messagebox.showwarning(APP_TITLE,"Keine Datenbankverbindung eingerichtet.")
            return
        try:
            job_id=latest_successful_job_id(dsn)
        except Exception as e:
            messagebox.showerror(APP_TITLE,str(e));return
        if not job_id:
            messagebox.showinfo(APP_TITLE,"Noch keine erfolgreiche Sicherung vorhanden.")
            return
        VerifyWindow(self,job_id)

    def open_last_report(self):
        if guard_active(self.store.data):
            messagebox.showwarning("Weihnachtsmarkt-Schutz","04.–13.12. sind Historie und Reports gesperrt.")
            return
        dsn=self.active_dsn()
        if not dsn:
            messagebox.showwarning(APP_TITLE,"Keine Datenbankverbindung eingerichtet.")
            return
        try:
            rows=recent_jobs(dsn,1)
        except Exception as e:
            messagebox.showerror(APP_TITLE,str(e));return
        if not rows:
            messagebox.showinfo(APP_TITLE,"Noch kein Backup-Job vorhanden.")
            return
        JobReportWindow(self,str(rows[0][0]))

    def open_history(self):
        if guard_active(self.store.data):
            messagebox.showwarning("Weihnachtsmarkt-Schutz","04.–13.12. sind auch Historie und Lesezugriffe auf das Backup-Neon gesperrt.")
            return
        dsn=self.active_dsn()
        if not dsn:
            messagebox.showwarning(APP_TITLE,"Keine Datenbankverbindung eingerichtet.")
            return
        HistoryWindow(
            self,
            report_callback=lambda jid: JobReportWindow(self,jid),
            verify_callback=lambda jid: VerifyWindow(self,jid),
        )

    def open_dashboard(self):
        if guard_active(self.store.data):
            messagebox.showwarning("Weihnachtsmarkt-Schutz","04.–13.12. bleibt auch das Dashboard offline, damit das Backup-Projekt keinen Neon-Verbrauch erzeugt.")
            return
        dsn=self.active_dsn()
        if not dsn:
            messagebox.showwarning(APP_TITLE,"Keine Datenbankverbindung eingerichtet.")
            return
        DashboardWindow(self)

    def open_explorer(self):
        if guard_active(self.store.data):
            messagebox.showwarning("Weihnachtsmarkt-Schutz","04.–13.12. bleibt der Backup-Explorer offline, damit das Backup-Projekt keinen Neon-Verbrauch erzeugt.")
            return
        BackupExplorer(self)
    def open_settings(self,tab=None): SettingsWindow(self,tab)
    def open_tuev(self):
        if guard_active(self.store.data):
            messagebox.showwarning("Weihnachtsmarkt-Schutz","04.–13.12. wird kein Online-TÜV gegen Neon ausgeführt.")
            return
        p=self.active_profile();dsn=self.active_dsn()
        if not p or not dsn:messagebox.showwarning(APP_TITLE,"Bitte zuerst Datenbankzugang einrichten.");return
        win=tk.Toplevel(self);win.title("TÜV / Architekturprüfung");win.geometry("1040x600")
        body=ttk.Frame(win,padding=10);body.pack(fill="both",expand=True)
        tr=ttk.Treeview(body,columns=("code","name","result","details"),show="headings")
        for c,t,w in [("code","Code",90),("name","Prüfung",240),("result","Ergebnis",90),("details","Details",650)]:tr.heading(c,text=t);tr.column(c,width=w)
        y=ttk.Scrollbar(body,orient="vertical",command=tr.yview);x=ttk.Scrollbar(body,orient="horizontal",command=tr.xview)
        tr.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        tr.grid(row=0,column=0,sticky="nsew");y.grid(row=0,column=1,sticky="ns");x.grid(row=1,column=0,sticky="ew")
        body.rowconfigure(0,weight=1);body.columnconfigure(0,weight=1)
        status=ttk.Frame(win,padding=(10,0,10,10));status.pack(fill="x")
        lbl=ttk.Label(status,text="TÜV wird ausgeführt …");lbl.pack(side="left")
        tuev_state={"checks":[]}
        def tuev_text():
            checks=tuev_state["checks"]
            fails=sum(1 for c in checks if c[2]=='FAIL');warns=sum(1 for c in checks if c[2]=='WARN')
            lines=["PC BACKUP VAULT – TÜV / ARCHITEKTURPRÜFUNG",f"Erstellt: {datetime.now():%d.%m.%Y %H:%M:%S}",f"Prüfungen: {len(checks)} · Fehler: {fails} · Warnungen: {warns}",""]
            lines.extend(f"{c[0]} | {c[2]} | {c[1]} | {c[3]}" for c in checks)
            return "\n".join(lines)+"\n"
        def copy_tuev():
            if not tuev_state["checks"]:return
            win.clipboard_clear();win.clipboard_append(tuev_text());win.update()
            messagebox.showinfo(APP_TITLE,"TÜV-Report wurde kopiert.",parent=win)
        def print_tuev():
            if not tuev_state["checks"]:return
            try:
                fd,path=tempfile.mkstemp(prefix="PC_Backup_Vault_TUEV_",suffix=".txt");os.close(fd)
                Path(path).write_text(tuev_text(),encoding="utf-8");os.startfile(path,"print")
            except Exception as e:messagebox.showerror(APP_TITLE,f"Drucken nicht möglich:\n{e}",parent=win)
        def send_tuev():
            checks=tuev_state["checks"]
            if not checks:return
            fails=sum(1 for c in checks if c[2]=='FAIL');warns=sum(1 for c in checks if c[2]=='WARN')
            self.notify_kc("tuev_failed","PC Backup Vault – TÜV-Report",f"{len(checks)} Prüfungen · {fails} Fehler · {warns} Warnungen","ERROR" if fails else ("WARN" if warns else "INFO"),{"failedChecks":fails,"warningChecks":warns,"status":"FAIL" if fails else ("WARN" if warns else "PASS")})
            messagebox.showinfo(APP_TITLE,"TÜV-Report wurde zur Übergabe an KC Kommunikation eingestellt.",parent=win)
        ttk.Button(status,text="Kopieren",command=copy_tuev).pack(side="right",padx=(6,0))
        ttk.Button(status,text="Drucken",command=print_tuev).pack(side="right",padx=(6,0))
        ttk.Button(status,text="An KC Kommunikation",command=send_tuev).pack(side="right",padx=(6,0))
        bar=ttk.Progressbar(status,mode="indeterminate");bar.pack(side="left",fill="x",expand=True,padx=10);bar.start(10)
        started=time.monotonic()
        tm=ttk.Label(status,text="Laufzeit: 00:00");tm.pack(side="right")
        def tick():
            if not win.winfo_exists():return
            elapsed=time.monotonic()-started;tm.config(text=f"Laufzeit: {int(elapsed//60):02d}:{int(elapsed%60):02d}")
            if str(bar['mode'])=='indeterminate':win.after(250,tick)
        tick()
        def work():
            checks=run_tuev(dsn,bool(self.master_key()),bool(self.store.data.get("recovery_key_exported")),p,self.store.data)
            def done():
                if not win.winfo_exists():return
                bar.stop();bar.config(mode="determinate",maximum=100,value=100)
                tuev_state["checks"]=list(checks)
                for c in checks:tr.insert("","end",values=c)
                fails=sum(1 for c in checks if c[2]=='FAIL');warns=sum(1 for c in checks if c[2]=='WARN')
                lbl.config(text=f"TÜV abgeschlossen: {len(checks)} Prüfungen · {fails} Fehler · {warns} Warnungen")
                if fails or warns:
                    self.notify_kc("tuev_failed", "Backup-TÜV mit Hinweis", f"{fails} Fehler · {warns} Warnungen", "ERROR" if fails else "WARN")
                self.refresh_system_status()
            self.after(0,done)
        threading.Thread(target=work,daemon=True).start()

class VerifyWindow(tk.Toplevel):
    def __init__(self, app:App, job_id:str):
        super().__init__(app)
        self.app=app; self.job_id=str(job_id); self.dsn=app.active_dsn(); self.control=None; self.running=False
        self.title("Backup verifizieren")
        self.geometry("760x360"); self.minsize(680,320)
        self.protocol("WM_DELETE_WINDOW", self._close)
        head=ttk.Frame(self,padding=12);head.pack(fill="x")
        ttk.Label(head,text="✓ Backup-Verifizierung",font=("Segoe UI",17,"bold")).pack(anchor="w")
        ttk.Label(head,text=f"Job: {self.job_id}",font=("Segoe UI",9)).pack(anchor="w",pady=(2,0))
        explain=ttk.LabelFrame(self,text="Prüfart",padding=10);explain.pack(fill="x",padx=12,pady=(0,10))
        ttk.Label(explain,text="Schnellprüfung: Neon-Katalog, Chunk-Konsistenz sowie B2-Objekte/Größen – ohne vollständigen Download.",wraplength=700).pack(anchor="w")
        ttk.Label(explain,text="Vollprüfung: lädt die zu diesem Job gespeicherten Inhalte, prüft verschlüsselte Chunks, entschlüsselt lokal und vergleicht Datei-SHA-256. Bei großen Backups kann das lange dauern.",wraplength=700).pack(anchor="w",pady=(4,0))
        row=ttk.Frame(explain);row.pack(fill="x",pady=(8,0))
        self.btn_quick=ttk.Button(row,text="Schnellprüfung starten",command=lambda:self.start("QUICK"));self.btn_quick.pack(side="left",padx=(0,6))
        self.btn_full=ttk.Button(row,text="Vollständig verifizieren",command=lambda:self.start("FULL"));self.btn_full.pack(side="left")

        live=ttk.LabelFrame(self,text="Prüfstatus",padding=10);live.pack(fill="x",padx=12,pady=(0,10))
        self.progress=ttk.Progressbar(live,mode="determinate",maximum=100);self.progress.pack(fill="x")
        self.lbl=ttk.Label(live,text="Bereit.");self.lbl.pack(anchor="w",pady=(6,2))
        self.stats=ttk.Label(live,text="Dateien: –   Daten: –   Laufzeit: –");self.stats.pack(anchor="w")
        ctl=ttk.Frame(live);ctl.pack(fill="x",pady=(8,0))
        self.btn_abort=ttk.Button(ctl,text="■ Abbrechen",command=self.cancel,state="disabled");self.btn_abort.pack(side="left")
        self.btn_report=ttk.Button(ctl,text="Report öffnen",command=lambda:JobReportWindow(self.app,self.job_id));self.btn_report.pack(side="right")
        self.result_box=ttk.Label(self,text="",padding=(12,0,12,10),wraplength=720);self.result_box.pack(fill="x")

    def _close(self):
        if self.running:
            if not messagebox.askyesno("Prüfung läuft","Prüfung abbrechen und Fenster schließen?",parent=self):return
            self.cancel()
        self.destroy()

    def cancel(self):
        if self.control is not None:
            self.control.cancel(); self.lbl.config(text="Abbruch angefordert …"); self.btn_abort.config(state="disabled")

    def _progress(self,d,t,msg,metrics=None):
        metrics=metrics or {}
        bdone=int(metrics.get("bytes_done") or 0); btotal=int(metrics.get("bytes_total") or 0)
        pct=(bdone/btotal*100.0) if btotal else (d/max(1,t)*100.0)
        self.progress.configure(value=max(0,min(100,pct)))
        self.lbl.config(text=f"{msg}")
        elapsed=float(metrics.get("elapsed") or 0)
        self.stats.config(text=f"Dateien: {metrics.get('files_done',d)} / {metrics.get('files_total',t)}   Daten: {human_size(bdone)} / {human_size(btotal)}   Laufzeit: {self.app._fmt_time(elapsed)}")

    def start(self,mode):
        if self.running:return
        if mode=="FULL" and not messagebox.askyesno("Vollprüfung", "Die Vollprüfung lädt die gespeicherten Inhalte aus B2/Neon und kann bei mehreren GB entsprechend lange dauern.\n\nJetzt starten?",parent=self):
            return
        self.running=True;self.control=BackupControl()
        self.btn_quick.config(state="disabled");self.btn_full.config(state="disabled");self.btn_abort.config(state="normal")
        self.progress.configure(value=0);self.lbl.config(text="Prüfung wird vorbereitet …");self.result_box.config(text="")
        def cb(d,t,m,metrics=None):self.after(0,lambda:self._progress(d,t,m,metrics))
        def work():
            try:
                r=verify_job(self.dsn,self.app.master_key(),self.job_id,mode=mode,object_store_config=self.app.store.get_b2_runtime_config(),progress=cb,control=self.control,app_version=APP_VERSION)
                def done():
                    self.progress.configure(value=100 if r.result=="PASS" else self.progress["value"])
                    self.lbl.config(text=f"Prüfung beendet: {r.result}")
                    self.stats.config(text=f"Dateien: {r.checked_files}   Chunks: {r.checked_chunks}   Geprüft: {human_size(r.checked_bytes)}   Dauer: {self.app._fmt_time(r.duration_seconds)}")
                    self.result_box.config(text=("✓ " if r.result=="PASS" else "⚠ ")+r.details)
                if r.result != "PASS":
                    self.app.notify_kc("verify_failed", "Backup-Verifizierung fehlgeschlagen", r.details, "ERROR", {"job_id": self.job_id, "mode": mode, "result": r.result})
                self.after(0,done)
                self.after(0,self.app.refresh_system_status)
            except BackupCancelled:
                self.after(0,lambda:self.result_box.config(text="Prüfung wurde abgebrochen und als CANCELLED protokolliert."))
                self.after(0,lambda:self.lbl.config(text="Prüfung abgebrochen."))
            except Exception as e:
                msg=str(e);self.after(0,lambda m=msg:self.result_box.config(text="Fehler: "+m))
            finally:
                def finish():
                    self.running=False;self.control=None;self.btn_quick.config(state="normal");self.btn_full.config(state="normal");self.btn_abort.config(state="disabled")
                self.after(0,finish)
        threading.Thread(target=work,daemon=True).start()


class JobReportWindow(tk.Toplevel):
    def __init__(self, app:App, job_id:str):
        super().__init__(app)
        self.app=app;self.job_id=str(job_id);self.dsn=app.active_dsn();self.report=None
        self.title("Backup-Report")
        self.geometry("940x720");self.minsize(760,560)
        head=ttk.Frame(self,padding=12);head.pack(fill="x")
        self.title_lbl=ttk.Label(head,text="Backup-Report",font=("Segoe UI",18,"bold"));self.title_lbl.pack(side="left")
        self.status_lbl=ttk.Label(head,text="wird geladen …",font=("Segoe UI",12,"bold"));self.status_lbl.pack(side="right")
        self.summary_lbl=ttk.Label(self,text="",padding=(12,0,12,8),font=("Segoe UI",11,"bold"));self.summary_lbl.pack(fill="x")
        frame=ttk.Frame(self,padding=(12,0,12,8));frame.pack(fill="both",expand=True)
        self.text=tk.Text(frame,wrap="none",font=("Consolas",10))
        y=ttk.Scrollbar(frame,orient="vertical",command=self.text.yview);x=ttk.Scrollbar(frame,orient="horizontal",command=self.text.xview)
        self.text.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        self.text.grid(row=0,column=0,sticky="nsew");y.grid(row=0,column=1,sticky="ns");x.grid(row=1,column=0,sticky="ew")
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        buttons=ttk.Frame(self,padding=(12,0,12,12));buttons.pack(fill="x")
        ttk.Button(buttons,text="Neu laden",command=self.load).pack(side="left",padx=(0,6))
        ttk.Button(buttons,text="Als TXT speichern",command=self.save_txt).pack(side="left",padx=(0,6))
        ttk.Button(buttons,text="Als CSV speichern",command=self.save_csv).pack(side="left",padx=(0,6))
        ttk.Button(buttons,text="Kopieren",command=self.copy_report).pack(side="left",padx=(0,6))
        ttk.Button(buttons,text="Drucken",command=self.print_report).pack(side="left",padx=(0,6))
        ttk.Button(buttons,text="An KC Kommunikation",command=self.send_report_to_kc).pack(side="left",padx=(0,6))
        ttk.Button(buttons,text="Schnell prüfen",command=lambda:VerifyWindow(self.app,self.job_id)).pack(side="right",padx=(6,0))
        ttk.Button(buttons,text="Schließen",command=self.destroy).pack(side="right")
        self.load()

    def load(self):
        try:
            self.report=load_job_report(self.dsn,self.job_id,self.app.master_key())
            r=self.report
            self.status_lbl.config(text=r.get("overall","–"))
            self.summary_lbl.config(text=f"{int(r.get('scanned_count') or 0):,} Dateien · {int(r.get('directory_count') or 0):,} Verzeichnisse · {human_size(r.get('original_bytes'))} · {fmt_duration(r.get('duration_seconds'))} · Ø {human_size(r.get('avg_speed_bps'))}/s".replace(",","."))
            self.text.config(state="normal");self.text.delete("1.0","end");self.text.insert("1.0",report_text(r));self.text.config(state="disabled")
        except Exception as e:
            self.status_lbl.config(text="FEHLER");self.text.config(state="normal");self.text.delete("1.0","end");self.text.insert("1.0",str(e));self.text.config(state="disabled")

    def copy_report(self):
        if not self.report:return
        text=report_text(self.report)
        self.clipboard_clear();self.clipboard_append(text);self.update()
        messagebox.showinfo(APP_TITLE,"Report wurde in die Zwischenablage kopiert.",parent=self)

    def print_report(self):
        if not self.report:return
        try:
            fd,path=tempfile.mkstemp(prefix="PC_Backup_Vault_Report_",suffix=".txt")
            os.close(fd)
            Path(path).write_text(report_text(self.report),encoding="utf-8")
            os.startfile(path,"print")
            messagebox.showinfo(APP_TITLE,"Report wurde an den Windows-Druckdialog übergeben.",parent=self)
        except Exception as e:
            messagebox.showerror(APP_TITLE,f"Drucken nicht möglich:\n{e}",parent=self)

    def send_report_to_kc(self):
        if not self.report:return
        r=self.report
        overall=str(r.get("overall") or "UNKNOWN").upper()
        severity="ERROR" if overall in ("FAIL","ERROR","FAILED") else ("WARN" if overall in ("WARN","WARNING") else "INFO")
        self.app.notify_kc(
            "backup_failed" if severity=="ERROR" else ("backup_warning" if severity=="WARN" else "backup_success"),
            f"Backup-Report: {overall}",
            f"Job {self.job_id} · {int(r.get('scanned_count') or 0)} Dateien · {human_size(r.get('original_bytes'))} · {fmt_duration(r.get('duration_seconds'))}",
            severity,
            {"job_id":self.job_id,"status":overall,"files":int(r.get("scanned_count") or 0),"size":int(r.get("original_bytes") or 0)}
        )
        messagebox.showinfo(APP_TITLE,"Report wurde zur Übergabe an KC Kommunikation eingestellt.",parent=self)

    def save_txt(self):
        if not self.report:return
        path=filedialog.asksaveasfilename(parent=self,title="Backup-Report als TXT speichern",defaultextension=".txt",filetypes=[("Text","*.txt")],initialfile=f"Backup_Report_{self.report['started_at']:%Y%m%d_%H%M}.txt")
        if path:
            save_report_txt(self.report,path);messagebox.showinfo(APP_TITLE,"Report gespeichert.",parent=self)

    def save_csv(self):
        if not self.report:return
        path=filedialog.asksaveasfilename(parent=self,title="Backup-Report als CSV speichern",defaultextension=".csv",filetypes=[("CSV","*.csv")],initialfile=f"Backup_Report_{self.report['started_at']:%Y%m%d_%H%M}.csv")
        if path:
            save_report_csv(self.report,path);messagebox.showinfo(APP_TITLE,"CSV gespeichert.",parent=self)


class BackupExplorer(tk.Toplevel):
    def __init__(self,app:App):
        super().__init__(app);self.app=app;self.dsn=app.active_dsn();self.records=[];self.item_records={};self.folder_nodes={}
        self.title("Backup‑Explorer – Neon / Backblaze B2");self.geometry("1180x700")
        if not self.dsn:
            messagebox.showwarning(APP_TITLE,"Keine Datenbankverbindung eingerichtet.",parent=self);self.destroy();return
        self._build();self.load()
    def _build(self):
        top=ttk.Frame(self,padding=10);top.pack(fill="x")
        ttk.Label(top,text="Backup‑Explorer",font=("Segoe UI",16,"bold")).pack(side="left")
        ttk.Label(top,text="  Namen/Pfade werden nur lokal entschlüsselt.").pack(side="left")
        self.search=tk.StringVar();ent=ttk.Entry(top,textvariable=self.search,width=34);ent.pack(side="right");ent.bind("<Return>",lambda e:self.render())
        ttk.Label(top,text="Suche:").pack(side="right",padx=(0,5))
        mid=ttk.Frame(self,padding=(10,0,10,0));mid.pack(fill="both",expand=True)
        self.tree=ttk.Treeview(mid,columns=("date","size","storage","status","plan"),show="tree headings",selectmode="extended")
        self.tree.heading("#0",text="Ordner / Datei");self.tree.column("#0",width=560)
        for c,t,w in [("date","Backup-Datum",140),("size","Größe",95),("storage","Speicher",90),("status","Status",85),("plan","Plan",155)]:self.tree.heading(c,text=t);self.tree.column(c,width=w)
        y=ttk.Scrollbar(mid,orient="vertical",command=self.tree.yview)
        x=ttk.Scrollbar(mid,orient="horizontal",command=self.tree.xview)
        self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        self.tree.grid(row=0,column=0,sticky="nsew")
        y.grid(row=0,column=1,sticky="ns")
        x.grid(row=1,column=0,sticky="ew")
        mid.rowconfigure(0,weight=1);mid.columnconfigure(0,weight=1)
        bot=ttk.Frame(self,padding=10);bot.pack(fill="x")
        self.keep_structure=tk.BooleanVar(value=True);ttk.Checkbutton(bot,text="Originale Ordnerstruktur im Zielordner beibehalten",variable=self.keep_structure).pack(side="left")
        self.all_versions=tk.BooleanVar(value=False);ttk.Checkbutton(bot,text="Alle Dateiversionen anzeigen",variable=self.all_versions,command=self.render).pack(side="left",padx=(18,0))
        ttk.Button(bot,text="↩ Auswahl wiederherstellen",command=self.restore).pack(side="right",padx=(6,0))
        ttk.Button(bot,text="Neu laden",command=self.load).pack(side="right")
        self.status=ttk.Label(self,text="");self.status.pack(fill="x",padx=10,pady=(0,8))
    def load(self):
        try:
            raw=all_files(self.dsn,5000);self.records=[]
            for r in raw:
                try: name=decrypt_text(self.app.master_key(),r[2]); parent=decrypt_text(self.app.master_key(),r[3])
                except Exception: name="[nicht entschlüsselbar]";parent="[Pfad nicht entschlüsselbar]"
                self.records.append({"id":str(r[0]),"name":name,"parent":parent,"size":r[5],"stored":r[6],"status":r[9],"created":r[10],"plan":r[13] or r[12] or "–","backend":r[14] if len(r)>14 else "NEON"})
            self.render()
        except Exception as e:messagebox.showerror(APP_TITLE,str(e),parent=self)
    def render(self):
        self.tree.delete(*self.tree.get_children());self.item_records={};self.folder_nodes={}
        q=self.search.get().strip().lower(); count=0; newest_seen=set()
        for rec in self.records:
            full=(rec["parent"]+"\\"+rec["name"]).lower()
            if q and q not in full:continue
            logical_key=(rec["parent"].lower(),rec["name"].lower())
            if not self.all_versions.get():
                if logical_key in newest_seen: continue
                newest_seen.add(logical_key)
            parent_node=""
            rel=original_relative(rec["parent"],"")
            cumulative=[]
            for part in rel.parts:
                if not part:continue
                cumulative.append(part);key="/".join(cumulative)
                if key not in self.folder_nodes:
                    iid=self.tree.insert(parent_node,"end",text=part,open=len(cumulative)<=2,values=("","","",""));self.folder_nodes[key]=iid
                parent_node=self.folder_nodes[key]
            iid=self.tree.insert(parent_node,"end",text=rec["name"],values=(rec["created"].strftime("%d.%m.%Y %H:%M"),human_size(rec["size"]),rec.get("backend","NEON"),rec["status"],rec["plan"]))
            self.item_records[iid]=rec;count+=1
        mode="alle Versionen" if self.all_versions.get() else "je Datei die neueste Version"
        self.status.config(text=f"{count} Sicherungseinträge angezeigt ({mode}). Mehrfachauswahl sowie ganze Ordner sind möglich.")
    def _desc_records(self,iid):
        out=[]
        if iid in self.item_records:out.append(self.item_records[iid])
        for c in self.tree.get_children(iid):out.extend(self._desc_records(c))
        return out
    def restore(self):
        sels=self.tree.selection()
        if not sels:messagebox.showwarning(APP_TITLE,"Bitte Datei(en) oder Ordner auswählen.",parent=self);return
        recs=[];seen=set()
        for s in sels:
            for r in self._desc_records(s):
                if r["id"] not in seen:seen.add(r["id"]);recs.append(r)
        dest=filedialog.askdirectory(title="Zielordner für Wiederherstellung",parent=self)
        if not dest:return
        destp=Path(dest); ok=0; errors=[]
        self.status.config(text=f"Wiederherstellung läuft: {len(recs)} Datei(en)…");self.update_idletasks()
        for r in recs:
            try:
                rel=original_relative(r["parent"],r["name"]) if self.keep_structure.get() else Path(r["name"])
                restore_file(self.dsn,self.app.master_key(),r["id"],destp,rel,object_store_config=self.app.store.get_b2_runtime_config());ok+=1
            except Exception as e:errors.append(f"{r['name']}: {e}")
        if errors:messagebox.showwarning(APP_TITLE,f"{ok} Datei(en) wiederhergestellt.\n{len(errors)} Fehler.\n\n"+"\n".join(errors[:8]),parent=self)
        else:messagebox.showinfo(APP_TITLE,f"{ok} Datei(en) vollständig wiederhergestellt und per SHA‑256 geprüft.",parent=self)
        self.status.config(text=f"Fertig: {ok} erfolgreich, {len(errors)} Fehler.")

class SettingsWindow(tk.Toplevel):
    SCHEDULE_DISPLAY_TO_CODE = {
        "Manuell": "MANUAL",
        "Täglich": "DAILY",
        "Wöchentlich": "WEEKLY",
        "Bei Windows-Anmeldung": "ONLOGON",
    }
    SCHEDULE_CODE_TO_DISPLAY = {v:k for k,v in SCHEDULE_DISPLAY_TO_CODE.items()}
    WEEKDAY_DISPLAY_TO_CODE = {
        "Montag": "MON", "Dienstag": "TUE", "Mittwoch": "WED",
        "Donnerstag": "THU", "Freitag": "FRI", "Samstag": "SAT", "Sonntag": "SUN"
    }
    WEEKDAY_CODE_TO_DISPLAY = {v:k for k,v in WEEKDAY_DISPLAY_TO_CODE.items()}
    PROVIDER_DISPLAY_TO_CODE = {"Neon":"neon", "Supabase":"supabase", "PostgreSQL":"postgresql"}
    PROVIDER_CODE_TO_DISPLAY = {v:k for k,v in PROVIDER_DISPLAY_TO_CODE.items()}

    def __init__(self,app:App,tab=None):
        super().__init__(app)
        self.app=app
        self.store=app.store
        self.title("Einstellungen")
        self.geometry("1080x730")
        self.minsize(980,650)
        self.nb=ttk.Notebook(self)
        self.nb.pack(fill="both",expand=True,padx=10,pady=(10,4))
        self.dbtab=ttk.Frame(self.nb,padding=10)
        self.storagetab=ttk.Frame(self.nb,padding=10)
        self.plantab=ttk.Frame(self.nb,padding=10)
        self.commtab=ttk.Frame(self.nb,padding=10)
        self.safetab=ttk.Frame(self.nb,padding=10)
        self.nb.add(self.dbtab,text="Datenbanken")
        self.nb.add(self.storagetab,text="Dateispeicher")
        self.nb.add(self.plantab,text="One-Touch / Scheduler")
        self.nb.add(self.commtab,text="Kommunikation / Protokoll")
        self.nb.add(self.safetab,text="Sicherheit / Core")
        self._build_db()
        self._build_storage()
        self._build_plans()
        self._build_communication()
        self._build_safety()
        self.load_profiles()
        self.load_plans()
        if tab=="plans": self.nb.select(self.plantab)
        if tab=="storage": self.nb.select(self.storagetab)
        if tab=="communication": self.nb.select(self.commtab)
        self.protocol("WM_DELETE_WINDOW",self.close)

        # Einheitliche Aktivitätsanzeige für Online-/Prüfvorgänge.
        self.activity_frame=ttk.Frame(self,padding=(10,0,10,8))
        self.activity_frame.pack(fill="x")
        self.activity_label=ttk.Label(self.activity_frame,text="Bereit.")
        self.activity_label.pack(side="left",padx=(0,10))
        self.activity_progress=ttk.Progressbar(self.activity_frame,mode="indeterminate")
        self.activity_progress.pack(side="left",fill="x",expand=True,padx=(0,10))
        self.activity_time=ttk.Label(self.activity_frame,text="")
        self.activity_time.pack(side="right")
        self._activity_started=None
        self._activity_timer=None
        self._activity_buttons=[]

    def _activity_tick(self):
        if self._activity_started is None:
            return
        elapsed=max(0,time.monotonic()-self._activity_started)
        self.activity_time.config(text=f"Laufzeit: {int(elapsed//60):02d}:{int(elapsed%60):02d}")
        self._activity_timer=self.after(250,self._activity_tick)

    def _activity_start(self,label,buttons=()):
        if self._activity_started is not None:
            return False
        self._activity_started=time.monotonic()
        self.activity_label.config(text=label)
        self.activity_time.config(text="Laufzeit: 00:00")
        self.activity_progress.start(10)
        self._activity_buttons=list(buttons)
        for b in self._activity_buttons:
            try:b.config(state="disabled")
            except Exception:pass
        self._activity_tick()
        return True

    def _activity_stop(self,label="Bereit."):
        if self._activity_timer is not None:
            try:self.after_cancel(self._activity_timer)
            except Exception:pass
        self._activity_timer=None
        self.activity_progress.stop()
        self.activity_label.config(text=label)
        if self._activity_started is not None:
            elapsed=max(0,time.monotonic()-self._activity_started)
            self.activity_time.config(text=f"Dauer: {int(elapsed//60):02d}:{int(elapsed%60):02d}")
        self._activity_started=None
        for b in self._activity_buttons:
            try:b.config(state="normal")
            except Exception:pass
        self._activity_buttons=[]

    def _field_label(self,parent,text,row,required=False,note=None):
        box=ttk.Frame(parent)
        box.grid(row=row,column=0,sticky="w",pady=4,padx=(0,8))
        ttk.Label(box,text=text).pack(side="left")
        if required:
            tk.Label(box,text=" *",fg="#b00020",font=("Segoe UI",10,"bold")).pack(side="left")
        if note:
            ttk.Label(box,text=f"  {note}").pack(side="left")
        return box

    def _required_hint(self,parent):
        row=ttk.Frame(parent)
        row.pack(fill="x",pady=(4,8))
        tk.Label(row,text="*",fg="#b00020",font=("Segoe UI",10,"bold")).pack(side="left")
        ttk.Label(row,text=" Pflichtfeld").pack(side="left")

    def _build_db(self):
        left=ttk.Frame(self.dbtab)
        left.pack(side="left",fill="y",padx=(0,12))
        ttk.Label(left,text="Datenbank-Ziele",font=("Segoe UI",11,"bold")).pack(anchor="w")
        ttk.Label(left,text="Primär- und optionale Zweitziele",wraplength=220).pack(anchor="w",pady=(2,4))
        self.lst=tk.Listbox(left,width=29,height=24)
        self.lst.pack(fill="y",expand=True,pady=6)
        self.lst.bind("<<ListboxSelect>>",lambda e:self.load_selected_profile())
        ttk.Button(left,text="＋ Neues Ziel",command=self.new_profile).pack(fill="x",pady=2)
        ttk.Button(left,text="Ziel löschen",command=self.delete_profile).pack(fill="x",pady=2)

        right=ttk.Frame(self.dbtab)
        right.pack(side="left",fill="both",expand=True)
        self.vars={k:tk.StringVar() for k in ["name","provider","dsn","database","project_ref","soft","hard"]}
        form=ttk.LabelFrame(right,text="Ziel / Zugangsdaten",padding=10)
        form.pack(fill="x")

        fields=[
            ("Name","name",True),
            ("Anbieter","provider",True),
            ("Connection String / DSN","dsn",True),
            ("Datenbank","database",True),
            ("Projekt-ID / Referenz","project_ref",False),
            ("Warnlimit MB","soft",True),
            ("Hardlimit MB","hard",True),
        ]
        for i,(lab,key,req) in enumerate(fields):
            self._field_label(form,lab,i,req)
            if key=="provider":
                w=ttk.Combobox(form,textvariable=self.vars[key],state="readonly",values=list(self.PROVIDER_DISPLAY_TO_CODE.keys()),width=69)
            else:
                w=ttk.Entry(form,textvariable=self.vars[key],show="*" if key=="dsn" else "",width=72)
            w.grid(row=i,column=1,sticky="ew",pady=4)
        form.columnconfigure(1,weight=1)
        self._required_hint(right)

        row=ttk.Frame(right)
        row.pack(fill="x",pady=(2,8))
        ttk.Button(row,text="Speichern",command=self.save_profile).pack(side="left",padx=(0,6))
        self.btn_db_test=ttk.Button(row,text="Verbindung testen",command=self.test_profile); self.btn_db_test.pack(side="left",padx=(0,6))
        self.btn_core_test=ttk.Button(row,text="Schema / Core prüfen",command=self.init_schema); self.btn_core_test.pack(side="left")
        ttk.Label(right,text="Connection-Strings und Kennwörter werden ausschließlich im Windows-Anmeldetresor gespeichert; niemals in Neon oder config.json.",wraplength=710).pack(anchor="w",pady=8)

    def _build_storage(self):
        ttk.Label(self.storagetab,text="Dateispeicher für große Backup-Daten",font=("Segoe UI",12,"bold")).pack(anchor="w")
        ttk.Label(
            self.storagetab,
            text="Neon bleibt die Verwaltungsdatenbank für Core, Dateikatalog, Prüfsummen, Historie und TÜV. Die verschlüsselten Dateiblöcke können in Backblaze B2 gespeichert werden.",
            wraplength=900,
        ).pack(anchor="w",pady=(2,10))

        cfg=self.store.data.get("b2",{})
        self.b2_enabled=tk.BooleanVar(value=bool(cfg.get("enabled",False)))
        self.b2_bucket=tk.StringVar(value=str(cfg.get("bucket","") or ""))
        self.b2_endpoint=tk.StringVar(value=str(cfg.get("endpoint_url","") or ""))
        self.b2_region=tk.StringVar(value=str(cfg.get("region","") or ""))
        self.b2_prefix=tk.StringVar(value=str(cfg.get("prefix","pc-backup-vault") or "pc-backup-vault"))
        self.b2_soft=tk.StringVar(value=str(cfg.get("soft_limit_gb",8)))
        self.b2_hard=tk.StringVar(value=str(cfg.get("hard_limit_gb",10)))
        self.b2_workers=tk.StringVar(value=str(cfg.get("upload_workers",4)))
        access,secret=self.store.get_b2_credentials()
        self.b2_access=tk.StringVar(value=access or "")
        self.b2_secret=tk.StringVar(value=secret or "")

        f=ttk.LabelFrame(self.storagetab,text="Backblaze B2",padding=10)
        f.pack(fill="x")
        ttk.Checkbutton(f,text="Backblaze B2 als Dateispeicher aktivieren",variable=self.b2_enabled).grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,6))
        fields=[
            ("Bucket",self.b2_bucket,True,False),
            ("S3 Endpoint",self.b2_endpoint,True,False),
            ("Region",self.b2_region,False,False),
            ("Ordner/Prefix",self.b2_prefix,False,False),
            ("Access Key ID",self.b2_access,True,True),
            ("Application Key",self.b2_secret,True,True),
            ("Warnlimit GB",self.b2_soft,True,False),
            ("Hardlimit GB",self.b2_hard,True,False),
            ("Parallele Uploads (1–8)",self.b2_workers,True,False),
        ]
        for i,(label,var,required,secret_field) in enumerate(fields,start=1):
            self._field_label(f,label,i,required)
            ttk.Entry(f,textvariable=var,show="*" if secret_field else "",width=70).grid(row=i,column=1,sticky="ew",pady=4)
        f.columnconfigure(1,weight=1)
        self._required_hint(self.storagetab)
        row=ttk.Frame(self.storagetab); row.pack(fill="x",pady=(2,8))
        ttk.Button(row,text="B2 speichern",command=self.save_b2).pack(side="left",padx=(0,6))
        self.btn_b2_test=ttk.Button(row,text="B2-Verbindung testen",command=self.test_b2); self.btn_b2_test.pack(side="left",padx=(0,6))
        ttk.Button(row,text="B2-Zugangsdaten löschen",command=self.clear_b2).pack(side="left")
        self.lbl_b2_status=ttk.Label(self.storagetab,text="B2-Status: eingerichtet" if self.store.get_b2_runtime_config().get("configured") else "B2-Status: noch nicht eingerichtet")
        self.lbl_b2_status.pack(anchor="w",pady=(4,0))
        ttk.Label(self.storagetab,text="Access Key und Application Key werden ausschließlich im Windows-Anmeldetresor gespeichert. Sie werden weder in Neon noch in config.json geschrieben.",wraplength=900).pack(anchor="w",pady=(8,0))

    def _b2_form_config(self):
        try:
            soft=float(self.b2_soft.get().replace(",",".")); hard=float(self.b2_hard.get().replace(",","."))
            workers=int(self.b2_workers.get().strip())
            if soft<=0 or hard<=0 or hard<soft or not 1 <= workers <= 8: raise ValueError
        except Exception:
            messagebox.showerror(APP_TITLE,"B2 Warnlimit/Hardlimit müssen positive Zahlen sein; Hardlimit darf nicht kleiner als Warnlimit sein. Parallele Uploads müssen zwischen 1 und 8 liegen.",parent=self)
            return None
        if self.b2_enabled.get():
            missing=[]
            if not self.b2_bucket.get().strip(): missing.append("Bucket")
            if not self.b2_endpoint.get().strip(): missing.append("S3 Endpoint")
            if not self.b2_access.get().strip(): missing.append("Access Key ID")
            if not self.b2_secret.get().strip(): missing.append("Application Key")
            if missing:
                messagebox.showerror(APP_TITLE,"Bitte B2-Pflichtfelder ausfüllen:\n• "+"\n• ".join(missing),parent=self)
                return None
        return {
            "enabled":bool(self.b2_enabled.get()),
            "bucket":self.b2_bucket.get().strip(),
            "endpoint_url":self.b2_endpoint.get().strip().rstrip("/"),
            "region":self.b2_region.get().strip(),
            "prefix":self.b2_prefix.get().strip().strip("/") or "pc-backup-vault",
            "soft_limit_gb":soft,
            "hard_limit_gb":hard,
            "upload_workers":workers,
            "access_key_id":self.b2_access.get().strip(),
            "application_key":self.b2_secret.get().strip(),
            "configured":bool(self.b2_enabled.get() and self.b2_bucket.get().strip() and self.b2_endpoint.get().strip() and self.b2_access.get().strip() and self.b2_secret.get().strip()),
        }

    def save_b2(self):
        cfg=self._b2_form_config()
        if not cfg: return
        self.store.data["b2"]={k:v for k,v in cfg.items() if k not in ("access_key_id","application_key","configured")}
        self.store.set_b2_credentials(cfg.get("access_key_id",""),cfg.get("application_key",""))
        self.store.save()
        self.lbl_b2_status.config(text="B2-Status: eingerichtet" if self.store.get_b2_runtime_config().get("configured") else "B2-Status: deaktiviert/nicht vollständig")
        messagebox.showinfo(APP_TITLE,"Backblaze-B2-Einstellungen gespeichert.",parent=self)

    def test_b2(self):
        cfg=self._b2_form_config()
        if not cfg: return
        if not cfg.get("configured"):
            messagebox.showwarning(APP_TITLE,"B2 ist deaktiviert oder unvollständig.",parent=self); return
        if not self._activity_start("Backblaze B2 wird geprüft (Liste/Schreiben/Lesen/Löschen) …",(getattr(self,"btn_b2_test",None),)):
            return
        def work():
            try:
                store=make_b2_store(cfg)
                ok,msg=store.test()
                self.after(0,lambda:self._finish_b2_test(ok,msg))
            except Exception as e:
                msg=str(e); self.after(0,lambda m=msg:self._finish_b2_test(False,m))
        threading.Thread(target=work,daemon=True).start()

    def _finish_b2_test(self,ok,msg):
        self._activity_stop("B2-Verbindungstest: OK" if ok else "B2-Verbindungstest: FEHLER")
        (messagebox.showinfo if ok else messagebox.showerror)(APP_TITLE,msg,parent=self)

    def clear_b2(self):
        if not messagebox.askyesno(APP_TITLE,"Gespeicherte B2-Zugangsdaten aus dem Windows-Anmeldetresor löschen?",parent=self): return
        self.store.clear_b2_credentials()
        self.b2_access.set(""); self.b2_secret.set("")
        self.lbl_b2_status.config(text="B2-Status: Zugangsdaten fehlen")

    def _build_plans(self):
        left=ttk.Frame(self.plantab)
        left.pack(side="left",fill="y",padx=(0,12))
        ttk.Label(left,text="One-Touch-Pläne",font=("Segoe UI",11,"bold")).pack(anchor="w")
        ttk.Label(left,text="Feste Quellen + optionale Automatik",wraplength=220).pack(anchor="w",pady=(2,4))
        self.planlist=tk.Listbox(left,width=29,height=24)
        self.planlist.pack(fill="y",expand=True,pady=6)
        self.planlist.bind("<<ListboxSelect>>",lambda e:self.load_selected_plan())
        ttk.Button(left,text="＋ Neuer Plan",command=self.new_plan).pack(fill="x",pady=2)
        ttk.Button(left,text="Plan löschen",command=self.delete_plan).pack(fill="x",pady=2)

        right=ttk.Frame(self.plantab)
        right.pack(side="left",fill="both",expand=True)
        self.plan_name=tk.StringVar()
        self.plan_profile=tk.StringVar()
        self.plan_type=tk.StringVar(value="Manuell")
        self.plan_time=tk.StringVar(value="20:00")
        self.plan_day=tk.StringVar(value="Montag")
        self.plan_default=tk.BooleanVar(value=False)
        self.plan_enabled=tk.BooleanVar(value=True)
        self.plan_payload=tk.StringVar(value="Automatisch (empfohlen)")
        self.secondary_enabled=tk.BooleanVar(value=False)
        self.secondary_profile=tk.StringVar()

        f=ttk.LabelFrame(right,text="Plan",padding=10)
        f.pack(fill="x")
        self._field_label(f,"Name",0,True)
        ttk.Entry(f,textvariable=self.plan_name,width=50).grid(row=0,column=1,sticky="ew",pady=4)
        self._field_label(f,"Datenbank-Ziel",1,True)
        self.profile_combo=ttk.Combobox(f,textvariable=self.plan_profile,state="readonly")
        self.profile_combo.grid(row=1,column=1,sticky="ew",pady=4)
        self._field_label(f,"Automatik",2,True)
        self.plan_type_combo=ttk.Combobox(f,textvariable=self.plan_type,state="readonly",values=list(self.SCHEDULE_DISPLAY_TO_CODE.keys()))
        self.plan_type_combo.grid(row=2,column=1,sticky="ew",pady=4)
        self.plan_type_combo.bind("<<ComboboxSelected>>",lambda e:self._update_schedule_fields())
        self._field_label(f,"Uhrzeit (HH:MM)",3,True,"bei täglich/wöchentlich")
        self.time_entry=ttk.Entry(f,textvariable=self.plan_time,width=12)
        self.time_entry.grid(row=3,column=1,sticky="w",pady=4)
        self._field_label(f,"Wochentag",4,True,"bei wöchentlich")
        self.day_combo=ttk.Combobox(f,textvariable=self.plan_day,state="readonly",values=list(self.WEEKDAY_DISPLAY_TO_CODE.keys()),width=18)
        self.day_combo.grid(row=4,column=1,sticky="w",pady=4)
        ttk.Checkbutton(f,text="Als Haupt-One-Touch-Plan verwenden",variable=self.plan_default).grid(row=5,column=1,sticky="w",pady=4)
        ttk.Checkbutton(f,text="Plan aktiv",variable=self.plan_enabled).grid(row=6,column=1,sticky="w",pady=4)
        f.columnconfigure(1,weight=1)

        payload=ttk.LabelFrame(right,text="Dateidaten / Speicherziel",padding=10)
        payload.pack(fill="x",pady=(8,0))
        self._field_label(payload,"Speicherziel",0,True)
        self.plan_payload_combo=ttk.Combobox(payload,textvariable=self.plan_payload,state="readonly",values=list(PAYLOAD_DISPLAY_TO_CODE.keys()))
        self.plan_payload_combo.grid(row=0,column=1,sticky="ew",pady=4)
        payload.columnconfigure(1,weight=1)
        ttk.Label(payload,text="Automatisch nutzt Backblaze B2, sobald B2 eingerichtet ist; Neon bleibt immer Core/Dateikatalog.",wraplength=650).grid(row=1,column=0,columnspan=2,sticky="w",pady=(4,0))

        src=ttk.LabelFrame(right,text="Festgelegte Dateien / Verzeichnisse",padding=10)
        src.pack(fill="both",expand=True,pady=(8,0))
        reqrow=ttk.Frame(src); reqrow.pack(fill="x",pady=(0,5))
        ttk.Label(reqrow,text="Mindestens eine Quelle").pack(side="left")
        tk.Label(reqrow,text=" *",fg="#b00020",font=("Segoe UI",10,"bold")).pack(side="left")
        self.pathlist=tk.Listbox(src,height=7)
        self.pathlist.pack(fill="both",expand=True)
        sr=ttk.Frame(src)
        sr.pack(fill="x",pady=(6,0))
        ttk.Button(sr,text="＋ Ordner",command=self.plan_add_folder).pack(side="left",padx=(0,5))
        ttk.Button(sr,text="＋ Dateien",command=self.plan_add_files).pack(side="left",padx=(0,5))
        ttk.Button(sr,text="Entfernen",command=self.plan_remove_path).pack(side="left")

        second=ttk.LabelFrame(right,text="Zweite unabhängige Kopie",padding=10)
        second.pack(fill="x",pady=(8,0))
        ttk.Checkbutton(second,text="Zusätzlich auf ein zweites Datenbank-Ziel sichern",variable=self.secondary_enabled,command=self._update_secondary_state).grid(row=0,column=0,columnspan=2,sticky="w")
        ttk.Label(second,text="Zweitziel").grid(row=1,column=0,sticky="w",pady=(6,0),padx=(0,8))
        self.secondary_combo=ttk.Combobox(second,textvariable=self.secondary_profile,state="disabled")
        self.secondary_combo.grid(row=1,column=1,sticky="ew",pady=(6,0))
        second.columnconfigure(1,weight=1)

        self._required_hint(right)
        ar=ttk.Frame(right)
        ar.pack(fill="x",pady=8)
        ttk.Button(ar,text="Plan speichern",command=self.save_plan).pack(side="left",padx=(0,5))
        ttk.Button(ar,text="Jetzt ausführen",command=self.run_plan_now).pack(side="left",padx=(0,5))
        ttk.Button(ar,text="Scheduler installieren/aktualisieren",command=self.install_scheduler).pack(side="left",padx=(0,5))
        ttk.Button(ar,text="Scheduler entfernen",command=self.remove_scheduler).pack(side="left")
        ttk.Label(right,text="Der Windows-Scheduler erhält nur Plan-ID und lokalen Programmaufruf – keine Zugangsdaten und keinen Recovery-Key.",wraplength=720).pack(anchor="w")

    def _build_communication(self):
        cfg=self.store.data.get("kc_communication") or {}; events=cfg.get("events") or {}
        kc=ttk.LabelFrame(self.commtab,text="KC Kommunikation – zentrale Maschinenkopplung",padding=10); kc.pack(fill="x",pady=(0,8))
        self.kc_enabled=tk.BooleanVar(value=bool(cfg.get("enabled",False)))
        self.kc_device_name=tk.StringVar(value=str(cfg.get("device_name","PC Backup Vault") or "PC Backup Vault"))
        self.kc_timeout=tk.StringVar(value=str(cfg.get("timeout_seconds",8))); self.kc_push=tk.BooleanVar(value="push" in cfg.get("channels",["push","email"])); self.kc_email=tk.BooleanVar(value="email" in cfg.get("channels",["push","email"]))
        ttk.Checkbutton(kc,text="KC Kommunikation aktivieren",variable=self.kc_enabled).grid(row=0,column=0,columnspan=3,sticky="w",pady=4)
        ttk.Label(kc,text="Zentrale API").grid(row=1,column=0,sticky="w",padx=(0,8)); ttk.Label(kc,text=DEFAULT_MACHINE_ENDPOINT,foreground="#475569").grid(row=1,column=1,columnspan=2,sticky="w")
        ttk.Label(kc,text="Geräte-ID").grid(row=2,column=0,sticky="w",padx=(0,8)); ttk.Label(kc,text=str(cfg.get("device_id") or "–")).grid(row=2,column=1,columnspan=2,sticky="w")
        ttk.Label(kc,text="Gerätename").grid(row=3,column=0,sticky="w",padx=(0,8)); ttk.Entry(kc,textvariable=self.kc_device_name,width=38).grid(row=3,column=1,sticky="w")
        ttk.Label(kc,text="Timeout (Sek.)").grid(row=4,column=0,sticky="w",padx=(0,8)); ttk.Entry(kc,textvariable=self.kc_timeout,width=8).grid(row=4,column=1,sticky="w")
        ch=ttk.Frame(kc); ch.grid(row=5,column=0,columnspan=3,sticky="w",pady=4); ttk.Label(ch,text="Kanäle:").pack(side="left",padx=(0,8)); ttk.Checkbutton(ch,text="Push",variable=self.kc_push).pack(side="left",padx=(0,8)); ttk.Checkbutton(ch,text="E-Mail",variable=self.kc_email).pack(side="left")
        self.kc_pairing_status=ttk.Label(kc,text=f"Pairing-Code: {cfg.get('pairing_code') or 'noch nicht registriert'}",font=("Segoe UI",10,"bold")); self.kc_pairing_status.grid(row=6,column=0,columnspan=3,sticky="w",pady=(6,2))
        actions=ttk.Frame(kc); actions.grid(row=7,column=0,columnspan=3,sticky="w",pady=(4,2)); ttk.Button(actions,text="Gerät registrieren / Pairing-Code",command=self.register_kc_machine).pack(side="left",padx=(0,6)); self.btn_kc_test=ttk.Button(actions,text="Kopplung testen",command=self.test_kc_communication); self.btn_kc_test.pack(side="left")
        ttk.Label(kc,text="Der geheime Geräte-Token wird automatisch erzeugt und ausschließlich im Windows-Anmeldetresor gespeichert. Dateien, Originalpfade, Recovery-Key, Neon-DSN und B2-Zugangsdaten werden niemals an KC Kommunikation übertragen.",wraplength=880).grid(row=8,column=0,columnspan=3,sticky="w",pady=(6,0)); kc.columnconfigure(2,weight=1)
        ev=ttk.LabelFrame(self.commtab,text="Welche Ereignisse weitergeben?",padding=10); ev.pack(fill="x",pady=(0,8)); self.kc_event_vars={}
        items=[("backup_success","Backup erfolgreich"),("backup_failed","Backup fehlgeschlagen"),("backup_cancelled","Backup abgebrochen"),("backup_interrupted","Strom-/Programmabbruch"),("backup_resumed","Sicherung fortgesetzt"),("verify_failed","Verify fehlgeschlagen"),("restore_test_failed","Restore-Test fehlgeschlagen"),("tuev_failed","TÜV Fehler/Warnung"),("capacity_warning","Speicherwarnung"),("capacity_blocked","Speichersperre"),("scheduler_failed","Scheduler fehlgeschlagen")]
        for i,(code,label) in enumerate(items):
            v=tk.BooleanVar(value=bool(events.get(code,True))); self.kc_event_vars[code]=v; ttk.Checkbutton(ev,text=label,variable=v).grid(row=i//3,column=i%3,sticky="w",padx=(0,26),pady=3)
        recovery=ttk.LabelFrame(self.commtab,text="Stromausfall-/Crash-Recovery",padding=10); recovery.pack(fill="x",pady=(0,8)); self.auto_resume_interrupted=tk.BooleanVar(value=bool(self.store.data.get("auto_resume_interrupted",False))); ttk.Checkbutton(recovery,text="Unterbrochene Sicherungen beim nächsten Start automatisch fortsetzen",variable=self.auto_resume_interrupted).pack(anchor="w"); ttk.Label(recovery,text="Standard ist AUS: Das Programm fragt beim nächsten Start nach Fortsetzen, Verwerfen oder später entscheiden.",wraplength=850).pack(anchor="w",pady=(4,0))
        proto=ttk.LabelFrame(self.commtab,text="Startprotokoll",padding=10); proto.pack(fill="x",pady=(0,8)); self.start_protocol=tk.BooleanVar(value=bool(self.store.data.get("start_protocol_enabled",True))); ttk.Checkbutton(proto,text="Startprotokoll schreiben (für Entwicklung/Fehlersuche)",variable=self.start_protocol).pack(anchor="w"); ttk.Label(proto,text="Im Echtbetrieb kann das Protokoll ausgeschaltet werden. Es enthält keine Passwörter oder Schlüssel.",wraplength=850).pack(anchor="w",pady=(4,0))
        row=ttk.Frame(self.commtab); row.pack(fill="x",pady=(4,0)); ttk.Button(row,text="Speichern",command=self.save_communication).pack(side="left",padx=(0,6)); ttk.Button(row,text="Meldungs-Historie",command=self.show_kc_history).pack(side="left")

    def save_communication(self, quiet=False):
        try:
            timeout=int(self.kc_timeout.get()); assert 2<=timeout<=60
        except Exception:
            if not quiet: messagebox.showerror(APP_TITLE,"Timeout muss zwischen 2 und 60 Sekunden liegen.",parent=self)
            return False
        cfg=self.store.data.get("kc_communication") or {}; channels=[]
        if self.kc_push.get(): channels.append("push")
        if self.kc_email.get(): channels.append("email")
        if self.kc_enabled.get() and not channels:
            if not quiet: messagebox.showerror(APP_TITLE,"Bei aktiver KC Kommunikation muss Push und/oder E-Mail gewählt sein.",parent=self)
            return False
        cfg.update({"enabled":bool(self.kc_enabled.get()),"endpoint_url":DEFAULT_MACHINE_ENDPOINT,"device_name":self.kc_device_name.get().strip() or "PC Backup Vault","timeout_seconds":timeout,"channels":channels,"events":{k:bool(v.get()) for k,v in self.kc_event_vars.items()}})
        self.store.data["kc_communication"]=cfg; self.store.data["start_protocol_enabled"]=bool(self.start_protocol.get()); self.store.data["auto_resume_interrupted"]=bool(self.auto_resume_interrupted.get()); self.store.save(); self.app.refresh_system_status()
        if not quiet: messagebox.showinfo(APP_TITLE,"Kommunikations-, Recovery- und Protokoll-Einstellungen gespeichert.",parent=self)
        return True

    def register_kc_machine(self):
        if not self.save_communication(quiet=True): return
        self.store.ensure_kc_device_token(); client=make_kc_client(self.store)
        if not client: messagebox.showerror(APP_TITLE,"KC-Gerät konnte lokal nicht vorbereitet werden.",parent=self); return
        if not self._activity_start("KC-Gerät wird registriert …",()): return
        def work():
            ok,msg,code=client.register()
            def done():
                self._activity_stop("KC Registrierung: aktiv" if ok else "KC Registrierung: Pairing erforderlich"); cfg=self.store.data.get("kc_communication") or {}; cfg["pairing_code"]=code or cfg.get("pairing_code",""); self.store.save(); self.kc_pairing_status.config(text=f"Pairing-Code: {cfg.get('pairing_code') or '–'}"); self.app.refresh_system_status(); (messagebox.showinfo if ok or code else messagebox.showerror)(APP_TITLE,msg,parent=self)
            self.after(0,done)
        threading.Thread(target=work,daemon=True).start()

    def test_kc_communication(self):
        if not self.save_communication(quiet=True): return
        client=make_kc_client(self.store)
        if not client: messagebox.showwarning(APP_TITLE,"Gerät ist noch nicht registriert. Bitte zuerst 'Gerät registrieren / Pairing-Code' ausführen.",parent=self); return
        if not self._activity_start("KC Kopplung wird getestet …",(self.btn_kc_test,)): return
        def work():
            ok,msg=client.test(); self.after(0,lambda:self._finish_kc_test(ok,msg))
        threading.Thread(target=work,daemon=True).start()

    def _finish_kc_test(self,ok,msg):
        self._activity_stop("KC Kommunikation: OK" if ok else "KC Kommunikation: nicht aktiv"); self.app.refresh_system_status(); (messagebox.showinfo if ok else messagebox.showwarning)(APP_TITLE,msg,parent=self)

    def show_kc_history(self):
        win=tk.Toplevel(self); win.title("KC Kommunikations-Historie"); win.geometry("900x430"); frame=ttk.Frame(win,padding=10); frame.pack(fill="both",expand=True); tr=ttk.Treeview(frame,columns=("time","event","severity","delivery","message"),show="headings")
        for c,t,w in [("time","Zeit",180),("event","Ereignis",180),("severity","Stufe",80),("delivery","Versand",90),("message","Meldung",430)]: tr.heading(c,text=t);tr.column(c,width=w)
        y=ttk.Scrollbar(frame,orient="vertical",command=tr.yview); x=ttk.Scrollbar(frame,orient="horizontal",command=tr.xview); tr.configure(yscrollcommand=y.set,xscrollcommand=x.set); tr.grid(row=0,column=0,sticky="nsew");y.grid(row=0,column=1,sticky="ns");x.grid(row=1,column=0,sticky="ew");frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        for r in kc_recent_history(200): tr.insert("","end",values=(r.get("sent_at",""),r.get("event",""),r.get("severity",""),r.get("delivery",""),r.get("message","")))

    def _build_safety(self):
        core=ttk.LabelFrame(self.safetab,text="System / Core",padding=10)
        core.pack(fill="x",pady=(0,8))
        ttk.Label(core,text=f"App-Version: {APP_VERSION}").grid(row=0,column=0,sticky="w",padx=(0,30))
        ttk.Label(core,text="Core-Tabelle: backup_vault.core").grid(row=0,column=1,sticky="w",padx=(0,30))
        ttk.Label(core,text=f"Erwartetes Schema: {APP_VERSION}").grid(row=0,column=2,sticky="w")
        ttk.Label(core,text="Die TÜV-Prüfung vergleicht Core, Isolation und Datenbankzustand.").grid(row=1,column=0,columnspan=3,sticky="w",pady=(6,0))

        protection=ttk.LabelFrame(self.safetab,text="Schutz",padding=10)
        protection.pack(fill="x",pady=(0,8))
        self.guard=tk.BooleanVar(value=self.store.data.get("christmas_guard",True))
        ttk.Checkbutton(protection,text="Weihnachtsmarkt-Schutz 04.–13.12. (Backup, Restore, Explorer und Dashboard sperren)",variable=self.guard).grid(row=0,column=0,columnspan=2,sticky="w",pady=4)
        self.maxrun=tk.StringVar(value=str(self.store.data.get("max_run_mb",100)))
        self._field_label(protection,"Maximale Originaldaten pro Backup-Lauf (MB)",1,True)
        ttk.Entry(protection,textvariable=self.maxrun,width=12).grid(row=1,column=1,sticky="w",pady=4)

        retention=ttk.LabelFrame(self.safetab,text="Aufbewahrung / Selbsttest",padding=10)
        retention.pack(fill="x",pady=(0,8))
        self.retention_days=tk.StringVar(value=str(self.store.data.get("retention_days",90)))
        self.keep_versions=tk.StringVar(value=str(self.store.data.get("keep_last_versions",10)))
        self.auto_delete=tk.BooleanVar(value=bool(self.store.data.get("auto_delete_old_versions",False)))
        self.selftest_after=tk.BooleanVar(value=bool(self.store.data.get("restore_selftest_after_backup",True)))
        self.auto_quick_verify=tk.BooleanVar(value=bool(self.store.data.get("auto_quick_verify_after_backup",True)))
        self.selftest_kb=tk.StringVar(value=str(self.store.data.get("restore_selftest_max_kb",256)))
        self._field_label(retention,"Löschschutz / Aufbewahrung (Tage)",0,True)
        ttk.Entry(retention,textvariable=self.retention_days,width=12).grid(row=0,column=1,sticky="w",pady=4)
        self._field_label(retention,"Mindestens letzte Versionen behalten",1,True)
        ttk.Entry(retention,textvariable=self.keep_versions,width=12).grid(row=1,column=1,sticky="w",pady=4)
        ttk.Checkbutton(retention,text="Alte Versionen automatisch löschen (standardmäßig AUS)",variable=self.auto_delete).grid(row=2,column=1,sticky="w",pady=4)
        ttk.Checkbutton(retention,text="Nach jedem erfolgreichen Backup automatische Schnell-Verifizierung ausführen",variable=self.auto_quick_verify).grid(row=3,column=0,columnspan=2,sticky="w",pady=4)
        ttk.Checkbutton(retention,text="Nach One-Touch/Scheduler automatischen Restore-Selbsttest ausführen",variable=self.selftest_after,command=self._update_selftest_state).grid(row=4,column=0,columnspan=2,sticky="w",pady=4)
        self._field_label(retention,"Maximale Testdatei (KB)",5,True,"wenn Selbsttest aktiv")
        self.selftest_entry=ttk.Entry(retention,textvariable=self.selftest_kb,width=12)
        self.selftest_entry.grid(row=5,column=1,sticky="w",pady=4)

        keys=ttk.LabelFrame(self.safetab,text="Recovery-Key",padding=10)
        keys.pack(fill="x",pady=(0,8))
        row=ttk.Frame(keys)
        row.pack(anchor="w")
        ttk.Button(row,text="Recovery-Key exportieren",command=self.export_key).pack(side="left",padx=(0,6))
        ttk.Button(row,text="Recovery-Key importieren",command=self.import_key).pack(side="left")
        fp = recovery_fingerprint(self.app.master_key()) if self.app.master_key() else "–"
        ttk.Label(keys,text=f"Fingerprint: {fp[:24] if fp != '–' else '–'}",font=("Segoe UI",9,"bold")).pack(anchor="w",pady=(6,0))
        ttk.Label(keys,text="Recovery-Key niemals in Neon speichern. Eine getrennte Offline-Kopie ist für den Notfall dringend empfohlen.",wraplength=820).pack(anchor="w",pady=(3,0))

        emergency=ttk.LabelFrame(self.safetab,text="Backup-Pass / Notfall-Wiederherstellung",padding=10)
        emergency.pack(fill="x",pady=(0,8))
        erow=ttk.Frame(emergency); erow.pack(anchor="w")
        ttk.Button(erow,text="Backup-Pass + Notfall-Paket erstellen",command=self.export_recovery_pass).pack(side="left",padx=(0,6))
        ttk.Button(erow,text="Notfall-Paket importieren",command=self.import_recovery_bundle).pack(side="left")
        ttk.Label(emergency,text="Der Backup-Pass ist als PNG für Handy/Print gedacht und enthält keine Geheimnisse. Das .pvr-Notfall-Paket enthält die notwendigen Zugangsdaten ausschließlich stark verschlüsselt.",wraplength=860).pack(anchor="w",pady=(6,0))
        ttk.Label(emergency,text="Notfall-Passwort: mindestens 12 Zeichen; wird weder im Programm noch im Paket gespeichert.",wraplength=860).pack(anchor="w",pady=(3,0))

        self._required_hint(self.safetab)
        ttk.Button(self.safetab,text="Sicherheitsvorgaben speichern",command=self.save_safety).pack(anchor="w",pady=(4,0))
        self._update_selftest_state()

    def _update_schedule_fields(self):
        code=self.SCHEDULE_DISPLAY_TO_CODE.get(self.plan_type.get(),"MANUAL")
        self.time_entry.configure(state="normal" if code in ("DAILY","WEEKLY") else "disabled")
        self.day_combo.configure(state="readonly" if code=="WEEKLY" else "disabled")

    def _update_secondary_state(self):
        self.secondary_combo.configure(state="readonly" if self.secondary_enabled.get() else "disabled")

    def _update_selftest_state(self):
        self.selftest_entry.configure(state="normal" if self.selftest_after.get() else "disabled")

    def load_profiles(self):
        self.lst.delete(0,"end")
        names=[]
        for p in self.store.data["profiles"]:
            names.append(p["name"])
            self.lst.insert("end",("★ " if p["id"]==self.store.data.get("active_profile_id") else "")+p["name"])
        self.profile_combo["values"]=names
        self.secondary_combo["values"]=names
        if self.store.data["profiles"]:
            idx=next((i for i,p in enumerate(self.store.data["profiles"]) if p["id"]==self.store.data.get("active_profile_id")),0)
            self.lst.selection_set(idx)
            self.load_selected_profile()

    def selected_profile(self):
        s=self.lst.curselection()
        return self.store.data["profiles"][s[0]] if s else None

    def load_selected_profile(self):
        p=self.selected_profile()
        if not p: return
        self.vars["name"].set(p.get("name",""))
        self.vars["provider"].set(self.PROVIDER_CODE_TO_DISPLAY.get(p.get("provider","neon"),"Neon"))
        self.vars["database"].set(p.get("database",""))
        self.vars["project_ref"].set(p.get("project_ref",""))
        self.vars["soft"].set(str(p.get("soft_limit_mb",350)))
        self.vars["hard"].set(str(p.get("hard_limit_mb",420)))
        self.vars["dsn"].set(self.store.get_dsn(p["id"]) or "")

    def new_profile(self):
        pid=self.store.add_profile({"name":"Neues Backup-Ziel","provider":"postgresql","database":"","project_ref":"","soft_limit_mb":350,"hard_limit_mb":420,"enabled":True})
        self.store.set_active(pid)
        self.load_profiles()
        idx=next((i for i,p in enumerate(self.store.data["profiles"]) if p["id"]==pid),0)
        self.lst.selection_clear(0,"end")
        self.lst.selection_set(idx)
        self.load_selected_profile()

    def delete_profile(self):
        p=self.selected_profile()
        if p and messagebox.askyesno(APP_TITLE,f"Ziel '{p['name']}' löschen?\nDie Datenbank selbst wird NICHT gelöscht.",parent=self):
            self.store.delete_profile(p["id"])
            self.load_profiles()
            self.load_plans()

    def _validate_profile(self,p):
        missing=[]
        if not self.vars["name"].get().strip(): missing.append("Name")
        if not self.vars["provider"].get().strip(): missing.append("Anbieter")
        dsn=self.vars["dsn"].get().strip() or (self.store.get_dsn(p["id"]) if p else None)
        if not dsn: missing.append("Connection String / DSN")
        if not self.vars["database"].get().strip(): missing.append("Datenbank")
        if missing:
            messagebox.showerror(APP_TITLE,"Bitte Pflichtfelder ausfüllen:\n• "+"\n• ".join(missing),parent=self)
            return None
        try:
            soft=int(self.vars["soft"].get())
            hard=int(self.vars["hard"].get())
            if soft<=0 or hard<=0 or hard<soft: raise ValueError
        except Exception:
            messagebox.showerror(APP_TITLE,"Warnlimit und Hardlimit müssen positive Zahlen sein; das Hardlimit darf nicht kleiner als das Warnlimit sein.",parent=self)
            return None
        return dsn,soft,hard

    def save_profile(self):
        p=self.selected_profile()
        if not p: return
        valid=self._validate_profile(p)
        if not valid: return
        dsn,soft,hard=valid
        self.store.update_profile(p["id"],{
            "name":self.vars["name"].get().strip(),
            "provider":self.PROVIDER_DISPLAY_TO_CODE.get(self.vars["provider"].get(),"postgresql"),
            "database":self.vars["database"].get().strip(),
            "project_ref":self.vars["project_ref"].get().strip(),
            "soft_limit_mb":soft,
            "hard_limit_mb":hard,
            "enabled":True,
        })
        self.store.set_dsn(p["id"],dsn)
        self.store.set_active(p["id"])
        self.load_profiles()
        self.load_plans()
        messagebox.showinfo(APP_TITLE,"Datenbank-Ziel gespeichert.",parent=self)

    def test_profile(self):
        if guard_active(self.store.data):
            messagebox.showwarning("Weihnachtsmarkt-Schutz","04.–13.12. sind Verbindungstests zum Backup-Ziel gesperrt. Schutz erst bewusst deaktivieren und speichern.",parent=self)
            return
        p=self.selected_profile()
        if not p: return
        valid=self._validate_profile(p)
        if not valid: return
        dsn=valid[0]
        if not self._activity_start("Datenbank-Verbindung wird geprüft …",(getattr(self,"btn_db_test",None),)):
            return
        def work():
            try:
                ok,msg=test_connection(dsn)
                self.after(0,lambda:self._finish_profile_test(ok,msg))
            except Exception as e:
                msg=str(e); self.after(0,lambda m=msg:self._finish_profile_test(False,m))
        threading.Thread(target=work,daemon=True).start()

    def _finish_profile_test(self,ok,msg):
        self._activity_stop("Verbindungstest: OK" if ok else "Verbindungstest: FEHLER")
        (messagebox.showinfo if ok else messagebox.showerror)(APP_TITLE,msg,parent=self)

    def init_schema(self):
        if guard_active(self.store.data):
            messagebox.showwarning("Weihnachtsmarkt-Schutz","04.–13.12. sind Schema-/Core-Zugriffe auf das Backup-Ziel gesperrt.",parent=self)
            return
        p=self.selected_profile()
        if not p: return
        valid=self._validate_profile(p)
        if not valid: return
        if not self._activity_start("Schema / Core wird geprüft und abgeglichen …",(getattr(self,"btn_core_test",None),)):
            return
        dsn=valid[0]
        def work():
            try:
                initialize_schema(dsn)
                self.after(0,self._finish_core_test)
            except Exception as e:
                msg=str(e); self.after(0,lambda m=msg:self._finish_core_error(m))
        threading.Thread(target=work,daemon=True).start()

    def _finish_core_test(self):
        self._activity_stop(f"Schema / Core {APP_VERSION}: OK")
        messagebox.showinfo(APP_TITLE,f"Backup-Schema / Core {APP_VERSION} ist bereit.",parent=self)

    def _finish_core_error(self,msg):
        self._activity_stop("Schema / Core: FEHLER")
        messagebox.showerror(APP_TITLE,msg,parent=self)

    def load_plans(self,select_id=None):
        self.planlist.delete(0,"end")
        plans=self.store.data.get("plans",[])
        for p in plans:
            self.planlist.insert("end",("★ " if p["id"]==self.store.data.get("default_plan_id") else "")+p["name"])
        if plans:
            idx=next((i for i,p in enumerate(plans) if p["id"]==select_id),0) if select_id else 0
            self.planlist.selection_set(idx)
            self.load_selected_plan()

    def selected_plan(self):
        s=self.planlist.curselection()
        return self.store.data.get("plans",[])[s[0]] if s else None

    def load_selected_plan(self):
        p=self.selected_plan()
        if not p: return
        self.plan_name.set(p.get("name",""))
        prof=self.store.get_profile(p.get("profile_id"))
        self.plan_profile.set(prof["name"] if prof else "")
        self.plan_type.set(self.SCHEDULE_CODE_TO_DISPLAY.get(p.get("schedule_type","MANUAL"),"Manuell"))
        self.plan_time.set(p.get("schedule_time","20:00"))
        self.plan_day.set(self.WEEKDAY_CODE_TO_DISPLAY.get(p.get("weekday","MON"),"Montag"))
        self.plan_default.set(p["id"]==self.store.data.get("default_plan_id"))
        self.plan_enabled.set(p.get("enabled",True))
        self.plan_payload.set(PAYLOAD_CODE_TO_DISPLAY.get(p.get("payload_target","AUTO"),"Automatisch (empfohlen)"))
        self.secondary_enabled.set(bool(p.get("secondary_copy_enabled",False)))
        second=self.store.get_profile(p.get("secondary_profile_id"))
        self.secondary_profile.set(second["name"] if second else "")
        self.pathlist.delete(0,"end")
        for x in p.get("paths",[]): self.pathlist.insert("end",x)
        self._update_schedule_fields()
        self._update_secondary_state()

    def new_plan(self):
        pid=self.store.add_plan({"name":"Mein One-Touch Backup","profile_id":self.store.data.get("active_profile_id"),"paths":[],"schedule_type":"MANUAL"})
        self.load_plans(pid)

    def delete_plan(self):
        p=self.selected_plan()
        if p and messagebox.askyesno(APP_TITLE,f"Plan '{p['name']}' löschen?",parent=self):
            remove_task(p)
            self.store.delete_plan(p["id"])
            self.load_plans()

    def plan_add_folder(self):
        p=filedialog.askdirectory(parent=self,title="Quellordner auswählen")
        if p: self.pathlist.insert("end",p)

    def plan_add_files(self):
        for p in filedialog.askopenfilenames(parent=self,title="Quelldateien auswählen"):
            self.pathlist.insert("end",p)

    def plan_remove_path(self):
        for i in reversed(self.pathlist.curselection()): self.pathlist.delete(i)

    def _profile_id_by_name(self,name):
        return next((p["id"] for p in self.store.data["profiles"] if p["name"]==name),None)

    def _validate_plan(self):
        missing=[]
        if not self.plan_name.get().strip(): missing.append("Name")
        primary_id=self._profile_id_by_name(self.plan_profile.get())
        if not primary_id: missing.append("Datenbank-Ziel")
        if not self.plan_type.get().strip(): missing.append("Automatik")
        paths=list(self.pathlist.get(0,"end"))
        if not paths: missing.append("mindestens eine Datei oder ein Verzeichnis")
        if missing:
            messagebox.showerror(APP_TITLE,"Bitte Pflichtfelder ausfüllen:\n• "+"\n• ".join(missing),parent=self)
            return None
        code=self.SCHEDULE_DISPLAY_TO_CODE.get(self.plan_type.get(),"MANUAL")
        time=self.plan_time.get().strip()
        if code in ("DAILY","WEEKLY"):
            try:
                hh,mm=map(int,time.split(":"))
                if not (0<=hh<=23 and 0<=mm<=59): raise ValueError
            except Exception:
                messagebox.showerror(APP_TITLE,"Für täglich/wöchentlich ist eine gültige Uhrzeit als HH:MM erforderlich.",parent=self)
                return None
        weekday=self.WEEKDAY_DISPLAY_TO_CODE.get(self.plan_day.get(),"MON")
        if code=="WEEKLY" and not self.plan_day.get():
            messagebox.showerror(APP_TITLE,"Für wöchentliche Sicherungen ist ein Wochentag erforderlich.",parent=self)
            return None
        secondary_id=self._profile_id_by_name(self.secondary_profile.get()) if self.secondary_enabled.get() else None
        if self.secondary_enabled.get():
            if not secondary_id:
                messagebox.showerror(APP_TITLE,"Für die zweite Kopie muss ein Zweitziel gewählt werden.",parent=self)
                return None
            if secondary_id==primary_id:
                messagebox.showerror(APP_TITLE,"Primärziel und Zweitziel müssen verschieden sein.",parent=self)
                return None
        return code,time,weekday,paths,primary_id,secondary_id

    def save_plan(self):
        p=self.selected_plan()
        if not p: return
        valid=self._validate_plan()
        if not valid: return
        code,time,weekday,paths,primary_id,secondary_id=valid
        vals={
            "name":self.plan_name.get().strip(),
            "profile_id":primary_id,
            "paths":paths,
            "schedule_type":code,
            "schedule_time":time,
            "weekday":weekday,
            "enabled":bool(self.plan_enabled.get()),
            "payload_target":PAYLOAD_DISPLAY_TO_CODE.get(self.plan_payload.get(),"AUTO"),
            "secondary_copy_enabled":bool(self.secondary_enabled.get()),
            "secondary_profile_id":secondary_id,
        }
        pid=p["id"]
        self.store.update_plan(pid,vals)
        if self.plan_default.get(): self.store.set_default_plan(pid)
        self.load_plans(pid)
        messagebox.showinfo(APP_TITLE,"Plan gespeichert.",parent=self)
        return pid

    def run_plan_now(self):
        pid=self.save_plan()
        p=self.store.get_plan(pid) if pid else None
        if not p: return
        try:
            r=run_plan(p["id"])
            messagebox.showinfo(APP_TITLE,f"Plan erfolgreich. {r['files']} Datei(en) geprüft/gesichert.",parent=self)
        except Exception as e:
            messagebox.showerror(APP_TITLE,str(e),parent=self)

    def install_scheduler(self):
        pid=self.save_plan()
        p=self.store.get_plan(pid) if pid else None
        if not p: return
        if p.get("schedule_type")=="MANUAL":
            messagebox.showwarning(APP_TITLE,"Für 'Manuell' wird keine Windows-Scheduler-Aufgabe benötigt.",parent=self)
            return
        ok,msg=install_task(p)
        (messagebox.showinfo if ok else messagebox.showerror)(APP_TITLE,msg,parent=self)

    def remove_scheduler(self):
        p=self.selected_plan()
        if not p: return
        ok,msg=remove_task(p)
        (messagebox.showinfo if ok else messagebox.showwarning)(APP_TITLE,msg,parent=self)

    def save_safety(self):
        try:
            maxrun=int(self.maxrun.get())
            retention=int(self.retention_days.get())
            versions=int(self.keep_versions.get())
            selftest_kb=int(self.selftest_kb.get())
            if maxrun<=0 or retention<=0 or versions<=0: raise ValueError
            if self.selftest_after.get() and selftest_kb<=0: raise ValueError
        except Exception:
            messagebox.showerror(APP_TITLE,"Bitte alle mit * markierten Zahlenfelder mit positiven Zahlen ausfüllen.",parent=self)
            return
        self.store.data["christmas_guard"]=bool(self.guard.get())
        self.store.data["max_run_mb"]=maxrun
        self.store.data["retention_days"]=retention
        self.store.data["keep_last_versions"]=versions
        self.store.data["auto_delete_old_versions"]=bool(self.auto_delete.get())
        self.store.data["restore_selftest_after_backup"]=bool(self.selftest_after.get())
        self.store.data["auto_quick_verify_after_backup"]=bool(self.auto_quick_verify.get())
        self.store.data["restore_selftest_max_kb"]=selftest_kb
        self.store.save()
        messagebox.showinfo(APP_TITLE,"Sicherheitsvorgaben gespeichert.",parent=self)

    def export_recovery_pass(self):
        folder=filedialog.askdirectory(parent=self,title="Ordner für Backup-Pass / Notfall-Paket auswählen")
        if not folder: return
        pw=simpledialog.askstring("Notfall-Passwort","Eigenes Notfall-Passwort eingeben (mindestens 12 Zeichen):",show="*",parent=self)
        if pw is None: return
        if len(pw)<12:
            messagebox.showerror(APP_TITLE,"Das Notfall-Passwort muss mindestens 12 Zeichen lang sein.",parent=self); return
        pw2=simpledialog.askstring("Notfall-Passwort bestätigen","Notfall-Passwort erneut eingeben:",show="*",parent=self)
        if pw2 is None: return
        if pw != pw2:
            messagebox.showerror(APP_TITLE,"Die beiden Notfall-Passwörter stimmen nicht überein.",parent=self); return
        stamp=datetime.now().strftime("%Y%m%d_%H%M")
        base=Path(folder)
        bundle=base/f"PC_Backup_Vault_Notfallpaket_{stamp}.pvr"
        png=base/f"PC_Backup_Vault_Backup-Pass_{stamp}.png"
        readme=base/f"PC_Backup_Vault_NOTFALL_{stamp}.txt"
        try:
            export_encrypted_bundle(self.store,bundle,pw)
            export_safe_pass_png(self.store,png,bundle.name)
            export_readme(readme,bundle.name,png.name)
            self.store.data["recovery_key_exported"]=True
            self.store.data["last_recovery_export"]=datetime.now().isoformat(timespec="seconds")
            self.store.save()
            messagebox.showinfo(
                APP_TITLE,
                "Backup-Pass und Notfall-Paket wurden erstellt.\n\n"
                f"Backup-Pass: {png.name}\n"
                f"Notfall-Paket: {bundle.name}\n"
                f"Anleitung: {readme.name}\n\n"
                "Empfehlung: PNG aufs Handy kopieren; .pvr zusätzlich auf Handy oder USB-Stick sichern. "
                "Das Notfall-Passwort getrennt merken/aufbewahren.",
                parent=self,
            )
        except Exception as e:
            messagebox.showerror(APP_TITLE,str(e),parent=self)

    def import_recovery_bundle(self):
        path=filedialog.askopenfilename(parent=self,title="Verschlüsseltes Notfall-Paket importieren",filetypes=[("PC Backup Vault Notfall-Paket","*.pvr"),("Alle Dateien","*.*")])
        if not path: return
        if not messagebox.askyesno(APP_TITLE,"Das Notfall-Paket kann lokale Neon-/B2-Zugangsdaten und den Recovery-Key ersetzen. Fortfahren?",parent=self):
            return
        pw=simpledialog.askstring("Notfall-Passwort","Notfall-Passwort eingeben:",show="*",parent=self)
        if pw is None: return
        try:
            import_encrypted_bundle(self.store,path,pw)
            self.load_profiles()
            b2=self.store.data.get("b2") or {}
            self.b2_enabled.set(bool(b2.get("enabled",False)))
            self.b2_bucket.set(str(b2.get("bucket","") or "")); self.b2_endpoint.set(str(b2.get("endpoint_url","") or ""))
            self.b2_region.set(str(b2.get("region","") or "")); self.b2_prefix.set(str(b2.get("prefix","") or ""))
            self.b2_soft.set(str(b2.get("soft_limit_gb",8))); self.b2_hard.set(str(b2.get("hard_limit_gb",10))); self.b2_workers.set(str(b2.get("upload_workers",4)))
            access,secret=self.store.get_b2_credentials(); self.b2_access.set(access or ""); self.b2_secret.set(secret or "")
            messagebox.showinfo(
                APP_TITLE,
                "Notfall-Paket erfolgreich importiert.\n\n"
                "Jetzt bitte Datenbank-Verbindung, B2-Verbindung und anschließend den Backup-Explorer prüfen.",
                parent=self,
            )
        except Exception as e:
            messagebox.showerror(APP_TITLE,str(e),parent=self)

    def export_key(self):
        path=filedialog.asksaveasfilename(parent=self,title="Recovery-Key speichern",defaultextension=".pvkey",filetypes=[("PC Backup Vault Key","*.pvkey")])
        if not path: return
        Path(path).write_text("PC_BACKUP_VAULT_RECOVERY_KEY_V1\n"+self.app.master_key()+"\n",encoding="utf-8")
        self.store.data["recovery_key_exported"]=True
        self.store.data["last_recovery_export"]=datetime.now().isoformat(timespec="seconds")
        self.store.save()
        messagebox.showinfo(APP_TITLE,"Recovery-Key exportiert. Bitte getrennt vom PC aufbewahren.",parent=self)

    def import_key(self):
        path=filedialog.askopenfilename(parent=self,title="Recovery-Key importieren",filetypes=[("PC Backup Vault Key","*.pvkey"),("Alle Dateien","*.*")])
        if not path: return
        try:
            lines=Path(path).read_text(encoding="utf-8").strip().splitlines()
            if len(lines)<2 or lines[0]!="PC_BACKUP_VAULT_RECOVERY_KEY_V1": raise ValueError("Ungültige Recovery-Key-Datei.")
            if len(base64.urlsafe_b64decode(lines[1].encode("ascii")))!=32: raise ValueError("Ungültige Schlüssellänge.")
            self.store.set_master_key(lines[1].strip())
            messagebox.showinfo(APP_TITLE,"Recovery-Key importiert.",parent=self)
        except Exception as e:
            messagebox.showerror(APP_TITLE,str(e),parent=self)

    def close(self):
        self.app.refresh_status()
        self.destroy()
