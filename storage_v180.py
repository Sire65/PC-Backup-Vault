from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from crypto_box import encrypt_bytes, encrypt_text, sha256_bytes
from backup_engine import BackupCancelled, BackupControl, collect_paths

DISPLAY = "USB / externe Platte / Ordner / NAS"
CODE = "FILESYSTEM"
VAULT_DIR = ".pc-backup-vault"
CHUNK_SIZE = 8 * 1024 * 1024


def _human(n):
    x=float(n or 0)
    for u in ("B","KB","MB","GB","TB"):
        if x < 1024 or u == "TB": return f"{x:.1f} {u}"
        x /= 1024


def _fmt_seconds(seconds):
    seconds=max(0,int(seconds or 0)); h,rem=divmod(seconds,3600); m,s=divmod(rem,60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _ensure_cfg(store):
    changed=False
    if "filesystem_targets" not in store.data:
        store.data["filesystem_targets"]=[]; changed=True
    if "active_filesystem_target_id" not in store.data:
        store.data["active_filesystem_target_id"]=None; changed=True
    for plan in store.data.get("plans",[]):
        if "filesystem_target_id" not in plan:
            plan["filesystem_target_id"]=None; changed=True
        if "favorite" not in plan:
            plan["favorite"]=False; changed=True
    if changed: store.save()


def _targets(store):
    _ensure_cfg(store)
    return list(store.data.get("filesystem_targets") or [])


def _target(store, tid=None):
    tid=tid or store.data.get("active_filesystem_target_id")
    return next((x for x in _targets(store) if x.get("id")==tid),None)


def _set_active_target(store, target):
    store.data["active_filesystem_target_id"]=target.get("id")
    store.save()


def _volume_hint(path):
    p=str(path)
    drive=os.path.splitdrive(p)[0]
    return drive or ("UNC" if p.startswith("\\\\") else "ORDNER")


def add_or_select_target(app):
    _ensure_cfg(app.store)
    win=tk.Toplevel(app); win.title("Backup-Ziel auswählen"); win.geometry("820x430"); win.transient(app); win.grab_set()
    box=ttk.Frame(win,padding=12); box.pack(fill="both",expand=True)
    ttk.Label(box,text="Backup-Ziele – Laufwerk, Ordner, USB/SSD oder NAS",font=("Segoe UI",14,"bold")).pack(anchor="w")
    ttk.Label(box,text="Mit 'Durchsuchen' öffnet sich der Windows-Ordnerdialog. Dort kann gezielt Laufwerk → Ordner → Unterordner gewählt werden.",wraplength=780).pack(anchor="w",pady=(4,10))
    tree=ttk.Treeview(box,columns=("name","path","type"),show="headings",height=12)
    for c,t,w in (("name","Name",190),("path","Zielpfad",470),("type","Typ",110)):
        tree.heading(c,text=t); tree.column(c,width=w,anchor="w")
    tree.pack(fill="both",expand=True)

    def refresh(select_id=None):
        tree.delete(*tree.get_children())
        for t in _targets(app.store):
            iid=t.get("id")
            tree.insert("","end",iid=iid,values=(t.get("name") or "Backup-Ziel",t.get("path") or "",t.get("kind") or "ORDNER"))
            if iid==(select_id or app.store.data.get("active_filesystem_target_id")):
                tree.selection_set(iid); tree.focus(iid)

    def browse():
        p=filedialog.askdirectory(parent=win,title="Backup-Ziel auswählen – Laufwerk, Ordner oder Netzwerkpfad")
        if not p: return
        name=simpledialog.askstring("Name des Backup-Ziels","Wie soll dieses Ziel heißen?",initialvalue=Path(p).name or _volume_hint(p),parent=win)
        if not name: return
        low=str(p).lower(); kind="NAS" if str(p).startswith("\\\\") else ("LAUFWERK" if len(Path(p).parts)<=1 else "ORDNER")
        item={"id":str(uuid.uuid4()),"name":name.strip(),"path":str(p),"kind":kind,"volume_hint":_volume_hint(p)}
        app.store.data["filesystem_targets"].append(item); _set_active_target(app.store,item); refresh(item["id"])

    def unc():
        p=simpledialog.askstring("NAS / Netzwerkpfad","UNC-Pfad eingeben, z. B.  \\\\NAS\\Backup\\PC-Vault",parent=win)
        if not p: return
        p=p.strip()
        if not p.startswith("\\\\"):
            messagebox.showwarning("NAS-Pfad","Bitte einen UNC-Pfad eingeben, der mit \\\\ beginnt.",parent=win); return
        name=simpledialog.askstring("Name des Backup-Ziels","Name für dieses NAS-Ziel:",initialvalue="NAS Backup",parent=win) or "NAS Backup"
        item={"id":str(uuid.uuid4()),"name":name.strip(),"path":p,"kind":"NAS","volume_hint":"UNC"}
        app.store.data["filesystem_targets"].append(item); _set_active_target(app.store,item); refresh(item["id"])

    def choose():
        sel=tree.selection()
        if not sel: return
        t=_target(app.store,sel[0]);
        if not t: return
        _set_active_target(app.store,t); app.payload_var.set(DISPLAY); _update_target_text(app); win.destroy()

    def remove():
        sel=tree.selection()
        if not sel:return
        tid=sel[0]
        if not messagebox.askyesno("Ziel entfernen","Dieses Ziel nur aus der Liste entfernen? Bereits vorhandene Backup-Dateien werden NICHT gelöscht.",parent=win):return
        app.store.data["filesystem_targets"]=[x for x in _targets(app.store) if x.get("id")!=tid]
        if app.store.data.get("active_filesystem_target_id")==tid: app.store.data["active_filesystem_target_id"]=None
        app.store.save(); refresh()

    buttons=ttk.Frame(box); buttons.pack(fill="x",pady=(10,0))
    ttk.Button(buttons,text="＋ Durchsuchen …",command=browse).pack(side="left")
    ttk.Button(buttons,text="＋ NAS-Pfad …",command=unc).pack(side="left",padx=6)
    ttk.Button(buttons,text="Entfernen",command=remove).pack(side="left")
    ttk.Button(buttons,text="Abbrechen",command=win.destroy).pack(side="right")
    ttk.Button(buttons,text="✓ Dieses Ziel verwenden",command=choose).pack(side="right",padx=6)
    tree.bind("<Double-1>",lambda e:choose())
    refresh()


def _resolve_target(app, plan=None):
    tid=(plan or {}).get("filesystem_target_id") or app.store.data.get("active_filesystem_target_id")
    t=_target(app.store,tid)
    if t and Path(t.get("path") or "").exists(): return t
    return t


def _update_target_text(app):
    if app.payload_var.get()!=DISPLAY:return
    t=_target(app.store)
    if t:
        app.lbl_target.config(text=f"Ziel: {t.get('name')} – {t.get('path')}")
        app.lbl_conn.config(text="Verbindung: lokales/Netzwerk-Dateisystem")
    else:
        app.lbl_target.config(text="Ziel: noch kein Laufwerk/Ordner/NAS ausgewählt")


def filesystem_backup(app, paths, target, control=None, progress=None, plan_name=None):
    control=control or BackupControl(); paths=collect_paths(paths,control=control)
    root=Path(target["path"])/VAULT_DIR
    chunks=root/"chunks"; jobs=root/"jobs"
    chunks.mkdir(parents=True,exist_ok=True); jobs.mkdir(parents=True,exist_ok=True)
    # Real write test; catches missing media/read-only NAS before the first payload.
    probe=root/f".write-test-{os.getpid()}"
    try:
        probe.write_bytes(b"PCBV"); probe.unlink(missing_ok=True)
    except Exception as e:
        raise RuntimeError(f"Backup-Ziel ist nicht beschreibbar: {target['path']}\n{e}") from e
    total=sum(p.stat().st_size for p in paths); done=0; files_done=0; stored=0; peak=0.0; started=time.monotonic(); manifest=[]
    for p in paths:
        control.check(); stat=p.stat(); sha=hashlib.sha256()
        with p.open("rb") as fh:
            while True:
                control.check(); block=fh.read(1024*1024)
                if not block:break
                sha.update(block)
        file_sha=sha.hexdigest(); refs=[]; chunk_no=0
        with p.open("rb") as fh:
            while True:
                control.check(); raw=fh.read(CHUNK_SIZE)
                if not raw:break
                aad=f"{file_sha}:{chunk_no}".encode("ascii"); nonce,cipher=encrypt_bytes(app.master_key(),raw,aad)
                chash=sha256_bytes(cipher); rel=Path(file_sha[:2])/file_sha/f"{chunk_no:06d}-{chash[:12]}.bin"; out=chunks/rel
                out.parent.mkdir(parents=True,exist_ok=True)
                t0=time.monotonic()
                if not out.exists(): out.write_bytes(nonce+cipher); stored+=len(nonce)+len(cipher)
                dt=max(.001,time.monotonic()-t0); speed=(len(nonce)+len(cipher))/dt; peak=max(peak,speed)
                refs.append({"no":chunk_no,"file":str(rel).replace("\\","/"),"cipher_sha256":chash,"bytes":len(nonce)+len(cipher)})
                done+=len(raw); chunk_no+=1
                elapsed=max(.001,time.monotonic()-started); avg=done/elapsed; eta=(total-done)/avg if avg else 0
                metrics={"phase":"Dateisystem-Backup","bytes_done":done,"bytes_total":total,"transfer_bytes":stored,"current_file":p.name,"elapsed":elapsed,"speed_bps":speed,"peak_bps":peak,"eta_seconds":eta}
                if progress:
                    try: progress(files_done,len(paths),f"Sichere {p.name}",metrics)
                    except TypeError: progress(files_done,len(paths),f"Sichere {p.name}")
        manifest.append({"path":encrypt_text(app.master_key(),str(p.parent)),"name":encrypt_text(app.master_key(),p.name),"sha256":file_sha,"original_size":stat.st_size,"modified_at":stat.st_mtime,"chunks":refs})
        files_done+=1
    elapsed=max(.001,time.monotonic()-started); job_id=str(uuid.uuid4())
    doc={"format":"PCBV-FS-1","job_id":job_id,"app_version":"1.8.0","created_at":datetime.now().astimezone().isoformat(),"plan_name":plan_name,"target_name":target.get("name"),"files":manifest,"file_count":len(manifest),"original_bytes":total,"stored_bytes":stored,"duration_seconds":elapsed,"avg_speed_bps":int(total/elapsed),"peak_speed_bps":int(peak)}
    tmp=jobs/f"{job_id}.json.tmp"; final=jobs/f"{job_id}.json"; tmp.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8"); tmp.replace(final)
    if progress:
        metrics={"phase":"Fertig","bytes_done":total,"bytes_total":total,"transfer_bytes":stored,"current_file":"","elapsed":elapsed,"speed_bps":0,"peak_bps":peak,"eta_seconds":0}
        try: progress(len(paths),len(paths),"Backup abgeschlossen",metrics)
        except TypeError: progress(len(paths),len(paths),"Backup abgeschlossen")
    return {"job_id":job_id,"status":"SUCCESS","mode":"FILESYSTEM","payload_target":"FILESYSTEM","files":len(manifest),"original_bytes":total,"stored_bytes":stored,"duration_seconds":elapsed,"avg_speed_bps":int(total/elapsed),"peak_transfer_bps":int(peak),"target":str(root)}


def apply_v180(AppClass, ui_module, plan_runner_module=None):
    # Extend existing mappings globally so settings/comboboxes also know the target type.
    ui_module.PAYLOAD_DISPLAY_TO_CODE[DISPLAY]=CODE
    ui_module.PAYLOAD_CODE_TO_DISPLAY[CODE]=DISPLAY
    original_build=AppClass._build
    original_start=AppClass.start_backup
    original_selected=AppClass._selected_payload_code
    original_effective=AppClass._effective_payload_code
    original_refresh=AppClass.refresh_status

    def _build(self):
        _ensure_cfg(self.store); original_build(self)
        vals=list(self.payload_combo.cget("values"))
        if DISPLAY not in vals: vals.append(DISPLAY); self.payload_combo.configure(values=vals)
        parent=self.payload_combo.master
        self.btn_target_v180=ttk.Button(parent,text="📁 Ziel wählen …",command=lambda:add_or_select_target(self))
        self.btn_target_v180.pack(side="left",padx=(0,8),before=self.btn_backup)
        self.payload_combo.bind("<<ComboboxSelected>>",lambda e:(_update_target_text(self),self.update_backup_recommendation()),add="+")
        self._refresh_one_touch_v180()
        _update_target_text(self)

    def _selected_payload_code(self):
        if self.payload_var.get()==DISPLAY:return CODE
        return original_selected(self)

    def _effective_payload_code(self):
        if self.payload_var.get()==DISPLAY:return CODE if _target(self.store) else "FILESYSTEM_MISSING"
        return original_effective(self)

    def refresh_status(self):
        result=original_refresh(self)
        _update_target_text(self); self._refresh_one_touch_v180()
        return result

    def _refresh_one_touch_v180(self):
        plans=[p for p in self.store.data.get("plans",[]) if p.get("enabled",True)]
        try:self.btn_one_touch.configure(text=f"⚡ One-Touch ({len(plans)})")
        except Exception:pass

    def _run_plan_v180(self,plan):
        paths=collect_paths(plan.get("paths") or [])
        if not paths: messagebox.showwarning("One-Touch","Der gewählte Plan enthält keine erreichbaren Dateien/Ordner.",parent=self); return
        if (plan.get("payload_target") or "AUTO").upper()!=CODE:
            old_default=self.store.data.get("default_plan_id"); self.store.data["default_plan_id"]=plan["id"]; self.store.save()
            try:
                # call the pre-1.8 implementation with this selected default plan
                return self._run_default_one_touch_original()
            finally:
                self.store.data["default_plan_id"]=old_default; self.store.save()
        target=_resolve_target(self,plan)
        if not target or not Path(target.get("path") or "").exists():
            messagebox.showwarning("One-Touch","Das Laufwerk/der Ordner/das NAS-Ziel dieses Plans ist nicht erreichbar. Bitte Ziel auswählen.",parent=self); add_or_select_target(self); return
        total=sum(p.stat().st_size for p in paths); self._reset_live_progress(len(paths),total); control=self._begin_backup_control()
        def cb(d,t,m,metrics=None): self.after(0,lambda:self._progress(d,t,m,metrics))
        def work():
            try:
                r=filesystem_backup(self,paths,target,control,cb,plan.get("name")); self.after(0,lambda:self.lbl_progress.config(text=f"One-Touch '{plan.get('name')}' abgeschlossen – {r['files']} Dateien, {_human(r['original_bytes'])}, Ø {_human(r['avg_speed_bps'])}/s.")); self.notify_kc("backup_success","One-Touch Backup erfolgreich",f"Plan {plan.get('name')} wurde auf {target.get('name')} gesichert.","INFO",{"job_id":r['job_id'],"plan":plan.get('name'),"target":target.get('name'),"files":r['files'],"stored_bytes":r['stored_bytes']})
            except BackupCancelled:self.after(0,lambda:messagebox.showinfo("One-Touch","One-Touch wurde abgebrochen.",parent=self))
            except Exception as e:
                msg=str(e); self.notify_kc("backup_failed","One-Touch Backup fehlgeschlagen",msg,"ERROR",{"plan":plan.get('name')}); self.after(0,lambda m=msg:messagebox.showerror("One-Touch",m,parent=self))
            finally:self.after(0,lambda:self._set_backup_running(False))
        import threading; threading.Thread(target=work,daemon=True).start()

    def run_default_one_touch(self):
        plans=[p for p in self.store.data.get("plans",[]) if p.get("enabled",True)]
        if not plans:
            messagebox.showinfo("PC Backup Vault","Noch kein One-Touch-Plan vorhanden. Bitte im Zahnrad einen Plan anlegen.",parent=self); self.open_settings(tab="plans"); return
        if len(plans)==1:return self._run_plan_v180(plans[0])
        win=tk.Toplevel(self); win.title(f"One-Touch – {len(plans)} Jobs"); win.geometry("820x390"); win.transient(self); win.grab_set()
        box=ttk.Frame(win,padding=12); box.pack(fill="both",expand=True)
        ttk.Label(box,text=f"One-Touch Jobs ({len(plans)})",font=("Segoe UI",14,"bold")).pack(anchor="w")
        tree=ttk.Treeview(box,columns=("name","target","last"),show="headings",height=12)
        for c,t,w in (("name","Job",270),("target","Ziel",330),("last","Letzter Lauf",170)):
            tree.heading(c,text=t); tree.column(c,width=w,anchor="w")
        tree.pack(fill="both",expand=True,pady=(8,10))
        for p in plans:
            if (p.get("payload_target") or "AUTO").upper()==CODE:
                t=_target(self.store,p.get("filesystem_target_id")); target=(t or _target(self.store) or {}).get("name") or "Dateisystem-Ziel"
            else: target=p.get("payload_target") or "AUTO"
            tree.insert("","end",iid=p["id"],values=(p.get("name") or "Backup",target,p.get("last_run") or "–"))
        def go():
            sel=tree.selection()
            if not sel:return
            plan=next((p for p in plans if p.get("id")==sel[0]),None); win.destroy()
            if plan:self._run_plan_v180(plan)
        ttk.Button(box,text="Abbrechen",command=win.destroy).pack(side="right")
        ttk.Button(box,text="▶ Ausgewählten Job starten",command=go).pack(side="right",padx=6)
        tree.bind("<Double-1>",lambda e:go())

    def start_backup(self,resume_checkpoint=None):
        if self.payload_var.get()!=DISPLAY or resume_checkpoint is not None:return original_start(self,resume_checkpoint)
        if not self.selected:messagebox.showwarning("PC Backup Vault","Bitte zuerst Dateien oder einen Ordner auswählen.",parent=self);return
        target=_target(self.store)
        if not target or not Path(target.get("path") or "").exists():messagebox.showwarning("Backup-Ziel","Bitte zuerst mit 'Ziel wählen …' ein erreichbares Laufwerk, einen Ordner oder ein NAS auswählen.",parent=self);add_or_select_target(self);return
        paths=list(self.selected); total=sum(p.stat().st_size for p in paths); self._reset_live_progress(len(paths),total); control=self._begin_backup_control()
        def cb(d,t,m,metrics=None):self.after(0,lambda:self._progress(d,t,m,metrics))
        def work():
            try:
                r=filesystem_backup(self,paths,target,control,cb); self.after(0,lambda:self.lbl_progress.config(text=f"Backup abgeschlossen – {r['files']} Dateien, {_human(r['original_bytes'])}, Ø {_human(r['avg_speed_bps'])}/s, Spitze {_human(r['peak_transfer_bps'])}/s.")); self.notify_kc("backup_success","Backup erfolgreich",f"Dateisystem-Backup auf {target.get('name')} abgeschlossen.","INFO",{"job_id":r['job_id'],"target":target.get('name'),"files":r['files'],"stored_bytes":r['stored_bytes']})
            except BackupCancelled:self.after(0,lambda:messagebox.showinfo("PC Backup Vault","Backup wurde abgebrochen.",parent=self))
            except Exception as e:
                msg=str(e); self.notify_kc("backup_failed","Backup fehlgeschlagen",msg,"ERROR"); self.after(0,lambda m=msg:messagebox.showerror("PC Backup Vault",m,parent=self))
            finally:self.after(0,lambda:self._set_backup_running(False))
        import threading; threading.Thread(target=work,daemon=True).start()

    AppClass._build=_build
    AppClass._selected_payload_code=_selected_payload_code
    AppClass._effective_payload_code=_effective_payload_code
    AppClass.refresh_status=refresh_status
    AppClass._refresh_one_touch_v180=_refresh_one_touch_v180
    AppClass._run_default_one_touch_original=AppClass.run_default_one_touch
    AppClass._run_plan_v180=_run_plan_v180
    AppClass.run_default_one_touch=run_default_one_touch
    AppClass.start_backup=start_backup
