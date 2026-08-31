from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from framework_core_adapters import TOKENS, apply_design_adapter, bind_window_escape, configure_table, normalize_window_geometry
from user_guidance import friendly_error
from .device_resolver import WindowsPathDeviceResolver
from .recovery_audit import save_recovery_audit
from .recovery_coordinator import RecoveryCoordinator
from .recovery_plan import RecoveryStage, STAGE_LABELS
from .recovery_readiness import readiness_snapshot


class RecoveryAssistantWindow(tk.Toplevel):
    """Guided recovery UI; blocked prerequisites stay disabled and no original repair action exists."""

    def __init__(self, parent, selected_disk=None):
        super().__init__(parent)
        self.coordinator = RecoveryCoordinator()
        self.resolver = WindowsPathDeviceResolver()
        self.selected_disk = selected_disk
        self.title("PC Backup Vault – Recovery-Assistent")
        self.configure(bg=TOKENS.bg)
        apply_design_adapter(self)
        normalize_window_geometry(self, 1120, 790, 920, 640)
        bind_window_escape(self, self.destroy)
        self._build()
        self._refresh()

    def _build(self):
        header = ttk.Frame(self, style="Surface.TFrame", padding=(18, 13)); header.pack(fill="x")
        left = ttk.Frame(header, style="Surface.TFrame"); left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="Recovery-Assistent", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Schritt für Schritt · Image-first · Original nie reparieren", style="Muted.TLabel").pack(anchor="w")
        ttk.Button(header, text="Zurück zum NAS", command=self.destroy).pack(side="right")

        progress_box = ttk.Frame(self, style="Surface.TFrame", padding=(18, 8)); progress_box.pack(fill="x")
        self.progress = ttk.Progressbar(progress_box, maximum=6, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_label = ttk.Label(progress_box, text="Schritt 1 von 6", style="Muted.TLabel")
        self.progress_label.pack(side="left", padx=(10, 0))

        body = ttk.Frame(self, style="Vault.TFrame", padding=16); body.pack(fill="both", expand=True)
        steps = ttk.LabelFrame(body, text="Sicherer Ablauf", padding=8); steps.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(steps, height=8)
        configure_table(self.tree, [("step","Schritt",300,"w"),("state","Status",130,"w"),("reason","Hinweis",520,"w")])
        sy = ttk.Scrollbar(steps, orient="vertical", command=self.tree.yview); self.tree.configure(yscrollcommand=sy.set)
        self.tree.pack(side="left", fill="both", expand=True); sy.pack(side="right", fill="y")

        actions = ttk.LabelFrame(body, text="Einzelschritte", padding=10); actions.pack(fill="x", pady=(10,0))
        self.btn_source = ttk.Button(actions, text="1. Quelle übernehmen", command=self._take_source)
        self.btn_assess = ttk.Button(actions, text="2. Quellprüfung bestätigen", command=self._confirm_assessment)
        self.btn_image = ttk.Button(actions, text="3. Vorhandenes Image auswählen", command=self._choose_image)
        self.btn_verify = ttk.Button(actions, text="4. Image verifizieren", command=self._verify)
        self.btn_analyze = ttk.Button(actions, text="5. Image analysieren", command=self._analyze)
        self.btn_target = ttk.Button(actions, text="6. Rettungsziel auswählen", command=self._choose_target)
        for index, button in enumerate((self.btn_source,self.btn_assess,self.btn_image,self.btn_verify,self.btn_analyze,self.btn_target)):
            button.grid(row=index//3, column=index%3, sticky="ew", padx=4, pady=4); actions.columnconfigure(index%3, weight=1)

        self.info = ttk.Label(body, style="Muted.TLabel", wraplength=1040, justify="left"); self.info.pack(fill="x", pady=(10,4))
        footer = ttk.Frame(body, style="Vault.TFrame"); footer.pack(fill="x")
        self.btn_audit = ttk.Button(footer, text="Auditbericht speichern", command=self._save_audit); self.btn_audit.pack(side="left")
        self.btn_next = ttk.Button(footer, text="Nächster Schritt", command=self._run_next); self.btn_next.pack(side="right")
        self.ready_label = ttk.Label(footer, style="Section.TLabel"); self.ready_label.pack(side="right", padx=(0,12))

    def _show_error(self, title: str, exc: Exception):
        messagebox.showerror(title, friendly_error(exc), parent=self)

    def _take_source(self):
        disk = self.selected_disk
        if disk is None: return
        self.coordinator.identify_source(f"Disk {disk.number} · {disk.model}", disk.device_path, disk.size, device_id=disk.device_path)
        self._refresh()

    def _confirm_assessment(self):
        if not messagebox.askyesno("Quellprüfung", "Wurden Datenträgerdetails/SMART bzw. Read-only-Lesetest geprüft?\n\nEs wird keine Reparatur ausgeführt.", parent=self): return
        try: self.coordinator.mark_source_assessed()
        except Exception as exc: self._show_error("Recovery-Assistent", exc)
        self._refresh()

    def _choose_image(self):
        path = filedialog.askopenfilename(parent=self, title="Abgeschlossenes Image wählen", filetypes=[("Disk Image","*.img *.dd *.bin"),("Alle Dateien","*.*")])
        if not path: return
        resolved = self.resolver.resolve(path)
        if not resolved.known:
            messagebox.showwarning("Image-Ziel nicht eindeutig", f"Der physische Datenträger des Images konnte nicht sicher bestimmt werden.\n\n{resolved.reason}", parent=self)
        try: self.coordinator.attach_completed_image(path, device_id=resolved.device_id)
        except Exception as exc: self._show_error("Recovery-Assistent", exc)
        self._refresh()

    def _verify(self):
        try:
            self.coordinator.verify_attached_image()
            messagebox.showinfo("Image-Verifikation", "SHA-256 wurde vollständig berechnet und ein Verifikationsmanifest erzeugt.", parent=self)
        except Exception as exc: self._show_error("Image-Verifikation", exc)
        self._refresh()

    def _analyze(self):
        try:
            result = self.coordinator.analyze_verified_image()
            messagebox.showinfo("Image-Analyse", f"Read-only Analyse abgeschlossen.\nSignaturen: {', '.join(result.signatures) if result.signatures else 'keine einfache Signatur'}", parent=self)
        except Exception as exc: self._show_error("Image-Analyse", exc)
        self._refresh()

    def _choose_target(self):
        path = filedialog.askdirectory(parent=self, title="Rettungsziel auf separatem Datenträger wählen")
        if not path: return
        resolved = self.resolver.resolve(path)
        if not resolved.known:
            messagebox.showwarning("Rettungsziel gesperrt", f"Der physische Zieldatenträger konnte nicht eindeutig bestimmt werden. Recovery bleibt gesperrt.\n\n{resolved.reason}", parent=self)
        try: self.coordinator.select_recovery_target(path, device_id=resolved.device_id)
        except Exception as exc: self._show_error("Rettungsziel", exc)
        self._refresh()

    def _save_audit(self):
        path = filedialog.asksaveasfilename(parent=self, title="Recovery-Audit speichern", defaultextension=".json", filetypes=[("JSON","*.json")])
        if path: save_recovery_audit(self.coordinator.session, path)

    def _run_next(self):
        stage = self.coordinator.session.plan_state().next_stage
        handlers = {
            RecoveryStage.DETECT: self._take_source,
            RecoveryStage.ASSESS: self._confirm_assessment,
            RecoveryStage.IMAGE: self._choose_image,
            RecoveryStage.VERIFY: self._verify,
            RecoveryStage.ANALYZE: self._analyze,
            RecoveryStage.RECOVER: self._choose_target,
        }
        handler = handlers.get(stage)
        if handler: handler()

    def _refresh(self):
        state = self.coordinator.session.plan_state()
        for iid in self.tree.get_children(""): self.tree.delete(iid)
        for row in readiness_snapshot(state):
            status = "NÄCHSTER SCHRITT" if row.status == "next" else "BEREIT" if row.allowed else "GESPERRT"
            self.tree.insert("", "end", values=(row.label, status, row.reason))
        self.btn_source.configure(state="normal" if self.selected_disk is not None and not state.source_identified else "disabled")
        self.btn_assess.configure(state="normal" if state.allowed(RecoveryStage.ASSESS) and not state.source_assessed else "disabled")
        self.btn_image.configure(state="normal" if state.allowed(RecoveryStage.IMAGE) and not state.image_complete else "disabled")
        self.btn_verify.configure(state="normal" if state.allowed(RecoveryStage.VERIFY) and not state.image_verified else "disabled")
        self.btn_analyze.configure(state="normal" if state.allowed(RecoveryStage.ANALYZE) and not state.analysis_complete else "disabled")
        self.btn_target.configure(state="normal" if state.analysis_complete and state.image_verified else "disabled")
        completed = sum((state.source_identified, state.source_assessed, state.image_complete, state.image_verified, state.analysis_complete, state.allowed(RecoveryStage.RECOVER)))
        self.progress.configure(value=completed)
        next_stage = state.next_stage
        self.progress_label.configure(text=f"Schritt {min(completed + 1, 6)} von 6 · {STAGE_LABELS[next_stage]}")
        ids = (state.source_device_id or "?", state.image_device_id or "?", state.recovery_target_device_id or "?")
        self.info.configure(text=f"Physische Geräte: Quelle {ids[0]} · Image-Ziel {ids[1]} · Rettungsziel {ids[2]}. Freigabe nur bei eindeutig getrennten Geräten.")
        ready = state.allowed(RecoveryStage.RECOVER)
        self.ready_label.configure(text="RECOVERY FREIGEGEBEN" if ready else "Recovery gesperrt")
        next_allowed = (self.selected_disk is not None) if next_stage is RecoveryStage.DETECT else state.allowed(next_stage)
        self.btn_next.configure(state="normal" if next_allowed else "disabled", text="Recovery vorbereitet" if ready else "Nächster Schritt")
