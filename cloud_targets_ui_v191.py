from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from cloud_targets_v191 import (
    PROVIDERS, METHOD_LABELS, cloud_accounts, cloud_account, delete_cloud_account,
    ensure_cloud_config, ensure_filesystem_bridge, filesystem_capable_method,
    get_cloud_secret, provider_name, save_cloud_account, test_cloud_account,
)


class CloudTargetsTab(ttk.Frame):
    def __init__(self, master, settings_window):
        super().__init__(master, padding=10)
        self.settings=settings_window; self.store=settings_window.store; ensure_cloud_config(self.store)
        self.current_id=None; self.method_vars={}; self._testing=False; self._password_visible=False
        self._build(); self.refresh_list()

    def _build(self):
        ttk.Label(self,text="Cloud-Ziele / Anbieter-Stammdaten",font=("Segoe UI",12,"bold")).pack(anchor="w",pady=(0,6))
        ttk.Label(self,text="Für STRATO HiDrive sind die technischen Werte bereits vorbelegt. Sie müssen nur Benutzername und Passwort eintragen. Das Passwort liegt ausschließlich im Windows-Anmeldetresor.",wraplength=940).pack(anchor="w",pady=(0,10))
        body=ttk.Frame(self); body.pack(fill="both",expand=True); left=ttk.Frame(body); left.pack(side="left",fill="y",padx=(0,12))
        ttk.Label(left,text="Cloud-Konten",font=("Segoe UI",10,"bold")).pack(anchor="w"); self.lst=tk.Listbox(left,width=31,height=27); self.lst.pack(fill="y",expand=True,pady=(5,6)); self.lst.bind("<<ListboxSelect>>",self._select_from_list)
        ttk.Button(left,text="＋ Neues Cloud-Konto",command=self.new_account).pack(fill="x",pady=2); ttk.Button(left,text="Konto löschen",command=self.delete_account).pack(fill="x",pady=2)
        right=ttk.Frame(body); right.pack(side="left",fill="both",expand=True)
        self.name_var=tk.StringVar(); self.provider_var=tk.StringVar(value="STRATO HiDrive"); self.enabled_var=tk.BooleanVar(value=True); self.username_var=tk.StringVar(); self.password_var=tk.StringVar(); self.endpoint_var=tk.StringVar(); self.root_var=tk.StringVar(); self.local_path_var=tk.StringVar(); self.preferred_var=tk.StringVar(); self.notes_var=tk.StringVar()
        f=ttk.LabelFrame(right,text="Anbieter / Konto",padding=10); f.pack(fill="x"); ttk.Label(f,text="Bezeichnung *").grid(row=0,column=0,sticky="w",padx=(0,8),pady=4); ttk.Entry(f,textvariable=self.name_var,width=55).grid(row=0,column=1,sticky="ew",pady=4); ttk.Label(f,text="Anbieter *").grid(row=1,column=0,sticky="w",padx=(0,8),pady=4)
        self.provider_combo=ttk.Combobox(f,textvariable=self.provider_var,state="readonly",values=[x["name"] for x in PROVIDERS.values()],width=52); self.provider_combo.grid(row=1,column=1,sticky="ew",pady=4); self.provider_combo.bind("<<ComboboxSelected>>",lambda _e:self._provider_changed()); ttk.Checkbutton(f,text="Konto für Backups aktivieren",variable=self.enabled_var).grid(row=2,column=1,sticky="w",pady=4); f.columnconfigure(1,weight=1)
        methods=ttk.LabelFrame(right,text="Zugangsmöglichkeiten",padding=10); methods.pack(fill="x",pady=(8,0)); self.methods_frame=ttk.Frame(methods); self.methods_frame.pack(fill="x"); pref=ttk.Frame(methods); pref.pack(fill="x",pady=(8,0)); ttk.Label(pref,text="Bevorzugte Methode:").pack(side="left",padx=(0,8)); self.preferred_combo=ttk.Combobox(pref,textvariable=self.preferred_var,state="readonly",width=34); self.preferred_combo.pack(side="left")
        ttk.Label(methods,text="Empfohlen für HiDrive: SFTP (SSH). SMB und WebDAV bleiben als alternative Zugangsarten verfügbar, sind aber für den normalen HiDrive-Backupbetrieb nicht nötig.",wraplength=820).pack(anchor="w",pady=(8,0))
        access=ttk.LabelFrame(right,text="Verbindungsdaten",padding=10); access.pack(fill="x",pady=(8,0)); ttk.Label(access,text="Benutzername *").grid(row=0,column=0,sticky="w",padx=(0,8),pady=3); user=ttk.Entry(access,textvariable=self.username_var,width=64); user.grid(row=0,column=1,columnspan=2,sticky="ew",pady=3); user.bind("<FocusOut>",lambda _e:self._fill_hidrive_root())
        ttk.Label(access,text="Passwort *").grid(row=1,column=0,sticky="w",padx=(0,8),pady=3); self.password_entry=ttk.Entry(access,textvariable=self.password_var,show="*",width=58); self.password_entry.grid(row=1,column=1,sticky="ew",pady=3); self.eye_btn=ttk.Button(access,text="👁",width=3,command=self._toggle_password); self.eye_btn.grid(row=1,column=2,padx=(5,0),pady=3)
        fields=[("Server / Endpoint",self.endpoint_var),("Ziel-Unterordner",self.root_var),("Lokaler Sync-Ordner",self.local_path_var),("Notiz",self.notes_var)]
        for i,(label,var) in enumerate(fields,start=2): ttk.Label(access,text=label).grid(row=i,column=0,sticky="w",padx=(0,8),pady=3); ttk.Entry(access,textvariable=var,width=64).grid(row=i,column=1,columnspan=2,sticky="ew",pady=3)
        access.columnconfigure(1,weight=1)
        ttk.Label(access,text="Hinweis: Bei direktem HiDrive-SFTP bleibt „Lokaler Sync-Ordner“ leer.",foreground="#555555").grid(row=6,column=1,columnspan=2,sticky="w",pady=(3,0))
        actions=ttk.Frame(right); actions.pack(fill="x",pady=(10,0)); ttk.Button(actions,text="Speichern",command=self.save_account).pack(side="left",padx=(0,6)); self.test_btn=ttk.Button(actions,text="Verbindung testen",command=self.test_account); self.test_btn.pack(side="left",padx=(0,6)); ttk.Button(actions,text="Als Backup-Ziel bereitstellen",command=self.publish_backup_target).pack(side="left")
        self.progress=ttk.Progressbar(right,mode="indeterminate"); self.status=ttk.Label(right,text="Bereit."); self.status.pack(anchor="w",pady=(8,0)); self._set_hidrive_defaults(reset_methods=True)

    def _provider_code_from_name(self,name):
        return next((c for c,s in PROVIDERS.items() if s["name"]==name),"STRATO_HIDRIVE")
    def _toggle_password(self):
        self._password_visible=not self._password_visible; self.password_entry.configure(show="" if self._password_visible else "*"); self.eye_btn.configure(text="🙈" if self._password_visible else "👁")
    def _render_methods(self,code,selected=None):
        for w in self.methods_frame.winfo_children(): w.destroy()
        selected=set(selected or []); self.method_vars={}
        for i,m in enumerate(PROVIDERS[code]["methods"]):
            v=tk.BooleanVar(value=m in selected); self.method_vars[m]=v; ttk.Checkbutton(self.methods_frame,text=METHOD_LABELS.get(m,m),variable=v,command=self._sync_preferred_values).grid(row=i//2,column=i%2,sticky="w",padx=(0,30),pady=3)
        self._sync_preferred_values()
    def _sync_preferred_values(self):
        enabled=[m for m,v in self.method_vars.items() if v.get()]; labels=[METHOD_LABELS.get(m,m) for m in enabled]; self.preferred_combo.configure(values=labels)
        if self.preferred_var.get() not in labels:self.preferred_var.set(labels[0] if labels else "")
    def _fill_hidrive_root(self):
        if self._provider_code_from_name(self.provider_var.get())=="STRATO_HIDRIVE" and self.username_var.get().strip() and (not self.root_var.get().strip() or self.root_var.get().strip()=="/PC_Backup_Vault"):
            self.root_var.set(f"/users/{self.username_var.get().strip()}/PC_Backup_Vault")
    def _set_hidrive_defaults(self,reset_methods=False):
        if self._provider_code_from_name(self.provider_var.get())!="STRATO_HIDRIVE":return
        if reset_methods:self._render_methods("STRATO_HIDRIVE",{"SFTP"})
        self.endpoint_var.set(self.endpoint_var.get().strip() or "sftp.hidrive.strato.com:22"); self.local_path_var.set(""); self._fill_hidrive_root()
    def _provider_changed(self):
        code=self._provider_code_from_name(self.provider_var.get())
        if code=="STRATO_HIDRIVE":self._set_hidrive_defaults(True);self.status.configure(text="HiDrive ist vorbereitet: SFTP, Server und Zielstruktur werden automatisch gesetzt.")
        else:self._render_methods(code,{PROVIDERS[code]["methods"][0]})
    def refresh_list(self,select_id=None):
        self.lst.delete(0,"end"); rows=cloud_accounts(self.store)
        for r in rows:self.lst.insert("end",f"{'✓' if r.get('enabled',True) else '–'} {r.get('name')} · {provider_name(r.get('provider_code',''))}")
        target=select_id or self.current_id
        if target:
            for i,r in enumerate(rows):
                if r.get("id")==target:self.lst.selection_set(i);self.lst.activate(i);break
    def _select_from_list(self,_event=None):
        s=self.lst.curselection(); rows=cloud_accounts(self.store)
        if s and s[0]<len(rows):self.load_account(rows[s[0]]["id"])
    def new_account(self):
        self.current_id=None;self.name_var.set("STRATO HiDrive");self.provider_var.set("STRATO HiDrive");self.enabled_var.set(True);self.username_var.set("");self.password_var.set("");self.endpoint_var.set("");self.root_var.set("");self.local_path_var.set("");self.notes_var.set("");self._password_visible=False;self.password_entry.configure(show="*");self.eye_btn.configure(text="👁");self._set_hidrive_defaults(True);self.status.configure(text="Nur Benutzername und Passwort eintragen; die technischen HiDrive-Werte sind vorbelegt.")
    def load_account(self,account_id):
        r=cloud_account(self.store,account_id)
        if not r:return
        self.current_id=account_id;code=r.get("provider_code") or "STRATO_HIDRIVE";self.name_var.set(r.get("name") or provider_name(code));self.provider_var.set(provider_name(code));self.enabled_var.set(bool(r.get("enabled",True)));self.username_var.set(r.get("username") or "");self.password_var.set(get_cloud_secret(account_id,"password"));self.endpoint_var.set(r.get("endpoint") or "");self.root_var.set(r.get("root_path") or "");self.local_path_var.set(r.get("local_path") or "");self.notes_var.set(r.get("notes") or "");self._render_methods(code,set(r.get("methods") or []));self.preferred_var.set(METHOD_LABELS.get(r.get("preferred_method") or "",r.get("preferred_method") or ""));self._set_hidrive_defaults(False);self.status.configure(text="Konto geladen. Passwort liegt im Windows-Anmeldetresor.")
    def _form(self):
        code=self._provider_code_from_name(self.provider_var.get()); self._set_hidrive_defaults(False); methods=[m for m,v in self.method_vars.items() if v.get()]
        if not self.name_var.get().strip():raise ValueError("Bitte eine Bezeichnung eintragen.")
        if not self.username_var.get().strip():raise ValueError("Bitte den HiDrive-Benutzernamen eintragen.")
        if not methods:raise ValueError("Bitte mindestens eine Zugangsmethode aktivieren.")
        preferred=next((m for m in methods if METHOD_LABELS.get(m,m)==self.preferred_var.get()),methods[0])
        return {"id":self.current_id,"name":self.name_var.get().strip(),"provider_code":code,"enabled":self.enabled_var.get(),"methods":methods,"preferred_method":preferred,"username":self.username_var.get().strip(),"endpoint":self.endpoint_var.get().strip(),"root_path":self.root_var.get().strip(),"local_path":self.local_path_var.get().strip(),"notes":self.notes_var.get().strip()}
    def save_account(self):
        try:self.current_id=save_cloud_account(self.store,self._form(),password=self.password_var.get())
        except Exception as e:messagebox.showerror("Cloud-Ziele",str(e),parent=self);return
        self.refresh_list(self.current_id);self.status.configure(text="✓ Konto gespeichert. Passwort liegt sicher im Windows-Anmeldetresor.")
    def delete_account(self):
        if self.current_id and messagebox.askyesno("Cloud-Ziele","Dieses Cloud-Konto entfernen? Backup-Daten werden nicht gelöscht.",parent=self):delete_cloud_account(self.store,self.current_id);self.new_account();self.refresh_list()
    def test_account(self):
        if self._testing:return
        try:self.current_id=save_cloud_account(self.store,self._form(),password=self.password_var.get());r=cloud_account(self.store,self.current_id);method=r.get("preferred_method")
        except Exception as e:messagebox.showwarning("Cloud-Verbindungstest",str(e),parent=self);return
        self._testing=True;self.test_btn.configure(state="disabled",text="Test läuft …");self.status.configure(text="Verbindung wird geprüft … Anmeldung, Schreiben, Lesen und Löschen werden getestet.");self.progress.pack(fill="x",pady=(6,0),before=self.status);self.progress.start(12)
        def worker():
            try:result=test_cloud_account(self.store,self.current_id,method)
            except Exception as e:result=(False,str(e))
            self.after(0,lambda:self._test_done(*result))
        threading.Thread(target=worker,daemon=True,name="hidrive-test").start()
    def _test_done(self,ok,msg):
        self._testing=False;self.progress.stop();self.progress.pack_forget();self.test_btn.configure(state="normal",text="Verbindung testen");self.status.configure(text=("✓ " if ok else "⚠ ")+msg);(messagebox.showinfo if ok else messagebox.showwarning)("Cloud-Verbindungstest",msg,parent=self);self.refresh_list(self.current_id)
    def publish_backup_target(self):
        try:self.current_id=save_cloud_account(self.store,self._form(),password=self.password_var.get());target=ensure_filesystem_bridge(self.store,self.current_id)
        except Exception as e:messagebox.showwarning("Cloud-Ziel",str(e),parent=self);return
        self.status.configure(text=f"✓ Als Backup-Ziel bereit: {target.get('name')}");messagebox.showinfo("Cloud-Ziel bereit","Das HiDrive-Konto ist jetzt im Backup-Assistenten als Ziel auswählbar.",parent=self);self.refresh_list(self.current_id)


def apply_cloud_targets_v191(SettingsWindowClass, BackupAssistantClass, storage_module):
    if getattr(SettingsWindowClass,"_cloud_targets_v191",False):return
    original=SettingsWindowClass.__init__
    def init(self,app,tab=None):
        original(self,app,tab);self.cloudtab=CloudTargetsTab(self.nb,self);self.nb.add(self.cloudtab,text="Cloud-Ziele")
        if tab=="cloud":self.nb.select(self.cloudtab)
    SettingsWindowClass.__init__=init;SettingsWindowClass._cloud_targets_v191=True
    old_step=BackupAssistantClass.step_target
    def step_target(self):
        old_step(self);accounts=[x for x in cloud_accounts(self.store) if x.get("enabled",True) and filesystem_capable_method(x)];cloud=ttk.LabelFrame(self.body,text="Gespeicherte Cloud-Ziele",padding=8);cloud.pack(fill="x",pady=(14,0))
        if not accounts:ttk.Label(cloud,text="Noch kein Cloud-Ziel gespeichert. Unter Einstellungen → Cloud-Ziele kann STRATO HiDrive angelegt werden.",wraplength=760).pack(anchor="w");return
        by_label={f"{x.get('name')} · {provider_name(x.get('provider_code',''))}":x for x in accounts};var=tk.StringVar(value=next(iter(by_label)));ttk.Combobox(cloud,textvariable=var,state="readonly",values=list(by_label),width=60).pack(side="left",padx=(0,8))
        def choose():
            row=by_label.get(var.get())
            try:target=ensure_filesystem_bridge(self.store,row["id"])
            except Exception as e:messagebox.showwarning("Cloud-Ziel",str(e),parent=self);return
            self.data["payload_target"]=storage_module.CODE;self.data["filesystem_target_id"]=target["id"];messagebox.showinfo("Cloud-Ziel übernommen",f"{row.get('name')} wurde als Backup-Ziel gewählt.",parent=self);self.render()
        ttk.Button(cloud,text="Cloud-Ziel verwenden",command=choose).pack(side="left")
    BackupAssistantClass.step_target=step_target
