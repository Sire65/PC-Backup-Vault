from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from cloud_targets_v191 import (
    PROVIDERS,
    METHOD_LABELS,
    cloud_accounts,
    cloud_account,
    delete_cloud_account,
    ensure_cloud_config,
    ensure_filesystem_bridge,
    filesystem_capable_method,
    get_cloud_secret,
    provider_name,
    save_cloud_account,
    test_cloud_account,
)


class CloudTargetsTab(ttk.Frame):
    def __init__(self, master, settings_window):
        super().__init__(master, padding=10)
        self.settings = settings_window
        self.store = settings_window.store
        ensure_cloud_config(self.store)
        self.current_id = None
        self.method_vars: dict[str, tk.BooleanVar] = {}
        self._build()
        self.refresh_list()

    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, text="Cloud-Ziele / Anbieter-Stammdaten", font=("Segoe UI", 12, "bold")).pack(side="left")
        ttk.Label(
            self,
            text=(
                "Konten werden anbieterunabhängig verwaltet. Passwörter und Tokens liegen nur im Windows-Anmeldetresor. "
                "Ein Anbieter kann mehrere Zugangsarten besitzen; die tatsächlich nutzbaren Methoden werden pro Konto angehakt."
            ),
            wraplength=940,
        ).pack(anchor="w", pady=(0, 10))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="y", padx=(0, 12))
        ttk.Label(left, text="Cloud-Konten", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.lst = tk.Listbox(left, width=31, height=27)
        self.lst.pack(fill="y", expand=True, pady=(5, 6))
        self.lst.bind("<<ListboxSelect>>", self._select_from_list)
        ttk.Button(left, text="＋ Neues Cloud-Konto", command=self.new_account).pack(fill="x", pady=2)
        ttk.Button(left, text="Konto löschen", command=self.delete_account).pack(fill="x", pady=2)

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        self.name_var = tk.StringVar()
        self.provider_var = tk.StringVar(value="STRATO HiDrive")
        self.enabled_var = tk.BooleanVar(value=True)
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.endpoint_var = tk.StringVar()
        self.root_var = tk.StringVar()
        self.local_path_var = tk.StringVar()
        self.preferred_var = tk.StringVar()
        self.notes_var = tk.StringVar()

        f = ttk.LabelFrame(right, text="Anbieter / Konto", padding=10)
        f.pack(fill="x")
        ttk.Label(f, text="Bezeichnung *").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(f, textvariable=self.name_var, width=55).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(f, text="Anbieter *").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.provider_combo = ttk.Combobox(
            f,
            textvariable=self.provider_var,
            state="readonly",
            values=[x["name"] for x in PROVIDERS.values()],
            width=52,
        )
        self.provider_combo.grid(row=1, column=1, sticky="ew", pady=4)
        self.provider_combo.bind("<<ComboboxSelected>>", lambda _e: self._provider_changed())
        ttk.Checkbutton(f, text="Konto für Backups aktivieren", variable=self.enabled_var).grid(row=2, column=1, sticky="w", pady=4)
        f.columnconfigure(1, weight=1)

        methods = ttk.LabelFrame(right, text="Zugangsmöglichkeiten", padding=10)
        methods.pack(fill="x", pady=(8, 0))
        self.methods_frame = ttk.Frame(methods)
        self.methods_frame.pack(fill="x")
        prefrow = ttk.Frame(methods)
        prefrow.pack(fill="x", pady=(8, 0))
        ttk.Label(prefrow, text="Bevorzugte Methode:").pack(side="left", padx=(0, 8))
        self.preferred_combo = ttk.Combobox(prefrow, textvariable=self.preferred_var, state="readonly", width=34)
        self.preferred_combo.pack(side="left")
        ttk.Label(
            methods,
            text="SMB und lokale Sync-Ordner können bereits direkt als Backup-Ziel verwendet werden. WebDAV/SFTP/OAuth sind als Provider-Zugänge vorbereitet und separat testbar.",
            wraplength=820,
        ).pack(anchor="w", pady=(8, 0))

        access = ttk.LabelFrame(right, text="Verbindungsdaten", padding=10)
        access.pack(fill="x", pady=(8, 0))
        fields = [
            ("Benutzername", self.username_var, False),
            ("Passwort", self.password_var, True),
            ("Server / Endpoint", self.endpoint_var, False),
            ("Ziel-Unterordner", self.root_var, False),
            ("Lokaler Sync-Ordner", self.local_path_var, False),
            ("Notiz", self.notes_var, False),
        ]
        for i, (label, var, secret) in enumerate(fields):
            ttk.Label(access, text=label).grid(row=i, column=0, sticky="w", padx=(0, 8), pady=3)
            ttk.Entry(access, textvariable=var, show="*" if secret else "", width=64).grid(row=i, column=1, sticky="ew", pady=3)
        access.columnconfigure(1, weight=1)

        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Speichern", command=self.save_account).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Verbindung testen", command=self.test_account).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Als Backup-Ziel bereitstellen", command=self.publish_backup_target).pack(side="left")
        self.status = ttk.Label(right, text="Bereit.")
        self.status.pack(anchor="w", pady=(8, 0))

        self._render_methods("STRATO_HIDRIVE", selected={"SMB"})

    def _provider_code_from_name(self, name: str) -> str:
        for code, spec in PROVIDERS.items():
            if spec["name"] == name:
                return code
        return "STRATO_HIDRIVE"

    def _render_methods(self, provider_code: str, selected=None):
        selected = set(selected or [])
        for w in self.methods_frame.winfo_children():
            w.destroy()
        self.method_vars = {}
        methods = list(PROVIDERS[provider_code]["methods"])
        for i, method in enumerate(methods):
            v = tk.BooleanVar(value=method in selected)
            self.method_vars[method] = v
            ttk.Checkbutton(self.methods_frame, text=METHOD_LABELS.get(method, method), variable=v, command=self._sync_preferred_values).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 30), pady=3
            )
        self._sync_preferred_values()

    def _sync_preferred_values(self):
        enabled = [m for m, v in self.method_vars.items() if v.get()]
        labels = [METHOD_LABELS.get(m, m) for m in enabled]
        self.preferred_combo.configure(values=labels)
        current = self.preferred_var.get()
        if current not in labels:
            self.preferred_var.set(labels[0] if labels else "")

    def _provider_changed(self):
        code = self._provider_code_from_name(self.provider_var.get())
        self._render_methods(code, selected={PROVIDERS[code]["methods"][0]})
        if code == "STRATO_HIDRIVE":
            self.endpoint_var.set("")
            self.status.configure(text="STRATO: SMB-, WebDAV- und SFTP-Zugang sind vorbereitet. Verfügbarkeit hängt vom HiDrive-Tarif ab.")
        elif code in {"MICROSOFT_ONEDRIVE", "DROPBOX"}:
            self.status.configure(text="Für OneDrive/Dropbox ist lokaler Sync sofort nutzbar; OAuth/API ist als spätere direkte Verbindung vorbereitet.")
        else:
            self.status.configure(text="Generischer Anbieter – Server/Endpoint passend zum Konto eintragen.")

    def refresh_list(self, select_id=None):
        self.lst.delete(0, "end")
        rows = cloud_accounts(self.store)
        for row in rows:
            mark = "✓" if row.get("enabled", True) else "–"
            self.lst.insert("end", f"{mark} {row.get('name')} · {provider_name(row.get('provider_code',''))}")
        target = select_id or self.current_id
        if target:
            for idx, row in enumerate(rows):
                if row.get("id") == target:
                    self.lst.selection_set(idx)
                    self.lst.activate(idx)
                    break

    def _select_from_list(self, _event=None):
        sel = self.lst.curselection()
        if not sel:
            return
        rows = cloud_accounts(self.store)
        if sel[0] >= len(rows):
            return
        self.load_account(rows[sel[0]]["id"])

    def new_account(self):
        self.current_id = None
        self.name_var.set("Mein Cloud-Speicher")
        self.provider_var.set("STRATO HiDrive")
        self.enabled_var.set(True)
        self.username_var.set("")
        self.password_var.set("")
        self.endpoint_var.set("")
        self.root_var.set("")
        self.local_path_var.set("")
        self.notes_var.set("")
        self._render_methods("STRATO_HIDRIVE", selected={"SMB"})
        self.status.configure(text="Neues Konto – Zugangsdaten werden erst beim Speichern in den Windows-Anmeldetresor geschrieben.")

    def load_account(self, account_id: str):
        row = cloud_account(self.store, account_id)
        if not row:
            return
        self.current_id = account_id
        code = row.get("provider_code") or "STRATO_HIDRIVE"
        self.name_var.set(row.get("name") or provider_name(code))
        self.provider_var.set(provider_name(code))
        self.enabled_var.set(bool(row.get("enabled", True)))
        self.username_var.set(row.get("username") or "")
        self.password_var.set(get_cloud_secret(account_id, "password"))
        self.endpoint_var.set(row.get("endpoint") or "")
        self.root_var.set(row.get("root_path") or "")
        self.local_path_var.set(row.get("local_path") or "")
        self.notes_var.set(row.get("notes") or "")
        self._render_methods(code, selected=set(row.get("methods") or []))
        preferred = row.get("preferred_method") or ""
        self.preferred_var.set(METHOD_LABELS.get(preferred, preferred))
        self.status.configure(text="Konto geladen. Passwörter werden nicht in config.json gespeichert.")

    def _form(self):
        code = self._provider_code_from_name(self.provider_var.get())
        methods = [m for m, v in self.method_vars.items() if v.get()]
        if not self.name_var.get().strip():
            raise ValueError("Bitte eine Bezeichnung für das Cloud-Konto eintragen.")
        if not methods:
            raise ValueError("Bitte mindestens eine Zugangsmethode aktivieren.")
        preferred_label = self.preferred_var.get()
        preferred = next((m for m in methods if METHOD_LABELS.get(m, m) == preferred_label), methods[0])
        return {
            "id": self.current_id,
            "name": self.name_var.get().strip(),
            "provider_code": code,
            "enabled": self.enabled_var.get(),
            "methods": methods,
            "preferred_method": preferred,
            "username": self.username_var.get().strip(),
            "endpoint": self.endpoint_var.get().strip(),
            "root_path": self.root_var.get().strip(),
            "local_path": self.local_path_var.get().strip(),
            "notes": self.notes_var.get().strip(),
        }

    def save_account(self):
        try:
            account_id = save_cloud_account(self.store, self._form(), password=self.password_var.get())
        except Exception as exc:
            messagebox.showerror("Cloud-Ziele", str(exc), parent=self)
            return
        self.current_id = account_id
        self.refresh_list(account_id)
        self.status.configure(text="Cloud-Konto gespeichert. Geheimnisse liegen im Windows-Anmeldetresor.")

    def delete_account(self):
        if not self.current_id:
            return
        if not messagebox.askyesno("Cloud-Ziele", "Dieses Cloud-Konto aus den Stammdaten entfernen? Vorhandene Backup-Daten werden nicht gelöscht.", parent=self):
            return
        delete_cloud_account(self.store, self.current_id)
        self.new_account()
        self.refresh_list()

    def test_account(self):
        try:
            account_id = save_cloud_account(self.store, self._form(), password=self.password_var.get())
            self.current_id = account_id
            row = cloud_account(self.store, account_id)
            method = row.get("preferred_method")
            ok, msg = test_cloud_account(self.store, account_id, method)
        except Exception as exc:
            ok, msg = False, str(exc)
        self.status.configure(text=("✓ " if ok else "⚠ ") + msg)
        (messagebox.showinfo if ok else messagebox.showwarning)("Cloud-Verbindungstest", msg, parent=self)
        self.refresh_list(self.current_id)

    def publish_backup_target(self):
        try:
            account_id = save_cloud_account(self.store, self._form(), password=self.password_var.get())
            self.current_id = account_id
            target = ensure_filesystem_bridge(self.store, account_id)
        except Exception as exc:
            messagebox.showwarning("Cloud-Ziel", str(exc), parent=self)
            return
        self.status.configure(text=f"✓ Als Backup-Ziel bereit: {target.get('name')} · {target.get('path')}")
        messagebox.showinfo(
            "Cloud-Ziel bereit",
            "Das Konto ist jetzt im Backup-Assistenten als Ziel auswählbar. Ziel, Sicherungsart, Verifikation und Scheduler werden weiterhin im normalen Backup-Job festgelegt.",
            parent=self,
        )
        self.refresh_list(account_id)


def apply_cloud_targets_v191(SettingsWindowClass, BackupAssistantClass, storage_module):
    if getattr(SettingsWindowClass, "_cloud_targets_v191", False):
        return

    original_settings_init = SettingsWindowClass.__init__

    def settings_init(self, app, tab=None):
        original_settings_init(self, app, tab)
        self.cloudtab = CloudTargetsTab(self.nb, self)
        self.nb.add(self.cloudtab, text="Cloud-Ziele")
        if tab == "cloud":
            self.nb.select(self.cloudtab)

    SettingsWindowClass.__init__ = settings_init
    SettingsWindowClass._cloud_targets_v191 = True

    original_step_target = BackupAssistantClass.step_target

    def step_target(self):
        original_step_target(self)
        accounts = [x for x in cloud_accounts(self.store) if x.get("enabled", True) and filesystem_capable_method(x)]
        cloud = ttk.LabelFrame(self.body, text="Gespeicherte Cloud-Ziele", padding=8)
        cloud.pack(fill="x", pady=(14, 0))
        if not accounts:
            ttk.Label(
                cloud,
                text="Noch kein direkt nutzbares Cloud-Ziel gespeichert. Unter Einstellungen → Cloud-Ziele können STRATO, OneDrive, Dropbox und weitere Anbieter angelegt werden.",
                wraplength=760,
            ).pack(anchor="w")
            return
        by_label = {f"{x.get('name')} · {provider_name(x.get('provider_code',''))}": x for x in accounts}
        var = tk.StringVar(value=next(iter(by_label.keys())))
        combo = ttk.Combobox(cloud, textvariable=var, state="readonly", values=list(by_label.keys()), width=60)
        combo.pack(side="left", padx=(0, 8))

        def choose_cloud():
            row = by_label.get(var.get())
            if not row:
                return
            try:
                target = ensure_filesystem_bridge(self.store, row["id"])
            except Exception as exc:
                messagebox.showwarning("Cloud-Ziel", str(exc), parent=self)
                return
            self.data["payload_target"] = storage_module.CODE
            self.data["filesystem_target_id"] = target["id"]
            messagebox.showinfo(
                "Cloud-Ziel übernommen",
                f"{row.get('name')} wurde als Backup-Ziel gewählt.\n\nIm nächsten Schritt können Sicherungsart, Verifikation, One-Touch und Scheduler wie gewohnt festgelegt werden.",
                parent=self,
            )
            self.render()

        ttk.Button(cloud, text="Cloud-Ziel verwenden", command=choose_cloud).pack(side="left")

    BackupAssistantClass.step_target = step_target
