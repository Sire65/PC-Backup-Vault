from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk


def _human_rate(n):
    x=float(n or 0)
    for u in ("B/s","KB/s","MB/s","GB/s"):
        if x < 1024 or u=="GB/s": return f"{x:.1f} {u}"
        x/=1024


def _human_size(n):
    x=float(n or 0)
    for u in ("B","KB","MB","GB","TB"):
        if x < 1024 or u=="TB": return f"{x:.1f} {u}"
        x/=1024


def _clock(sec):
    sec=max(0,int(sec or 0)); h,r=divmod(sec,3600); m,s=divmod(r,60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class TransferMonitor(tk.Toplevel):
    def __init__(self,app):
        super().__init__(app)
        self.title("PC Backup Vault – Backup läuft")
        self.geometry("610x350")
        self.minsize(540,320)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW",self.withdraw)
        self.samples=[]
        box=ttk.Frame(self,padding=12); box.pack(fill="both",expand=True)
        self.title_lbl=ttk.Label(box,text="Sicherung wird vorbereitet …",font=("Segoe UI",12,"bold")); self.title_lbl.pack(anchor="w")
        self.progress=ttk.Progressbar(box,maximum=100); self.progress.pack(fill="x",pady=(8,8))
        self.canvas=tk.Canvas(box,height=130,bg="white",highlightbackground="#cbd5e1",highlightthickness=1); self.canvas.pack(fill="x")
        stats=ttk.Frame(box); stats.pack(fill="x",pady=(10,0))
        self.speed=ttk.Label(stats,text="Aktuell: –",font=("Segoe UI",10,"bold")); self.speed.grid(row=0,column=0,sticky="w",padx=(0,28))
        self.avg=ttk.Label(stats,text="Durchschnitt: –"); self.avg.grid(row=0,column=1,sticky="w",padx=(0,28))
        self.peak=ttk.Label(stats,text="Spitze: –"); self.peak.grid(row=0,column=2,sticky="w")
        self.files=ttk.Label(stats,text="Dateien: –"); self.files.grid(row=1,column=0,sticky="w",pady=(6,0),padx=(0,28))
        self.data=ttk.Label(stats,text="Daten: –"); self.data.grid(row=1,column=1,sticky="w",pady=(6,0),padx=(0,28))
        self.time_lbl=ttk.Label(stats,text="Laufzeit / Rest: –"); self.time_lbl.grid(row=1,column=2,sticky="w",pady=(6,0))
        self.current=ttk.Label(box,text="Aktuelle Datei: –",wraplength=570); self.current.pack(anchor="w",pady=(10,0))

    def update_metrics(self,d,t,message,metrics):
        metrics=dict(metrics or {})
        done=int(metrics.get("bytes_done") or 0); total=int(metrics.get("bytes_total") or 0)
        elapsed=float(metrics.get("elapsed") or 0); speed=float(metrics.get("speed_bps") or 0)
        if speed<=0 and elapsed>0 and done>0: speed=done/elapsed
        avg=done/max(.001,elapsed) if elapsed else 0
        peak=max([speed]+self.samples) if self.samples else speed
        eta=metrics.get("eta_seconds")
        if eta is None and avg>0 and total>=done: eta=(total-done)/avg
        pct=(done/total*100) if total else ((d/t*100) if t else 0)
        self.progress["value"]=max(0,min(100,pct))
        phase=str(metrics.get("phase") or "").lower()
        completed = pct >= 99.999 and ("fertig" in phase or "abgeschlossen" in str(message or "").lower())
        if completed:
            self.title("PC Backup Vault – Backup abgeschlossen")
            self.title_lbl.config(text="Backup abgeschlossen")
        else:
            self.title("PC Backup Vault – Backup läuft")
            self.title_lbl.config(text=message or metrics.get("phase") or "Backup läuft")
        self.speed.config(text=f"Aktuell: {_human_rate(speed)}"); self.avg.config(text=f"Durchschnitt: {_human_rate(avg)}")
        self.peak.config(text=f"Spitze: {_human_rate(max(peak,float(metrics.get('peak_bps') or 0)))}")
        self.files.config(text=f"Dateien: {int(d or 0)} / {int(t or 0)}")
        self.data.config(text=f"Daten: {_human_size(done)} / {_human_size(total)}")
        self.time_lbl.config(text=f"Laufzeit: {_clock(elapsed)} · Rest: {_clock(eta)}")
        self.current.config(text=f"Aktuelle Datei: {metrics.get('current_file') or '–'}")
        self.samples.append(max(0,speed)); self.samples=self.samples[-80:]
        self._draw()

    def _draw(self):
        self.canvas.delete("all"); w=max(20,self.canvas.winfo_width()); h=max(20,self.canvas.winfo_height()); pad=8
        self.canvas.create_line(pad,h-pad,w-pad,h-pad,fill="#cbd5e1")
        if len(self.samples)<2:return
        mx=max(1,max(self.samples)); pts=[]
        for i,v in enumerate(self.samples):
            x=pad+(w-2*pad)*(i/max(1,len(self.samples)-1)); y=h-pad-(h-2*pad)*(v/mx); pts.extend((x,y))
        self.canvas.create_line(*pts,fill="#2563eb",width=2,smooth=True)
        self.canvas.create_text(w-pad,pad,text=f"max {_human_rate(mx)}",anchor="ne",fill="#475569")


def apply_transfer_monitor(AppClass):
    original_begin=AppClass._begin_backup_control
    original_progress=AppClass._progress
    original_set=AppClass._set_backup_running

    def _begin_backup_control(self):
        control=original_begin(self)
        try:
            old=getattr(self,"_transfer_monitor_v180",None)
            if old and old.winfo_exists(): old.destroy()
        except Exception:pass
        self._transfer_monitor_v180=TransferMonitor(self)
        return control

    def _progress(self,d,t,m,metrics=None):
        result=original_progress(self,d,t,m,metrics)
        mon=getattr(self,"_transfer_monitor_v180",None)
        try:
            if mon and mon.winfo_exists(): mon.update_metrics(d,t,m,metrics or {})
        except Exception:pass
        return result

    def _set_backup_running(self,running):
        result=original_set(self,running)
        if not running:
            mon=getattr(self,"_transfer_monitor_v180",None)
            try:
                if mon and mon.winfo_exists():
                    mon.title("PC Backup Vault – Backup abgeschlossen")
                    mon.title_lbl.config(text="Backup abgeschlossen")
                    mon.after(2200,mon.destroy)
            except Exception:pass
        return result

    AppClass._begin_backup_control=_begin_backup_control
    AppClass._progress=_progress
    AppClass._set_backup_running=_set_backup_running
