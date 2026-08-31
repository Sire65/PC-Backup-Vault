from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from framework_core_adapters import (
    TOKENS,
    apply_design_adapter,
    bind_window_escape,
    configure_table,
    normalize_window_geometry,
    status_color,
)

from .service import NasRecoveryService, PhysicalDisk, human_bytes


class NasRecoveryWindow(tk.Toplevel):
    """Framework-Core-aligned NAS recovery UI.

    The window exposes only read-only diagnostics plus the explicit source->image
    copy path. RAID reconstruction and network/SSH diagnostics are staged for a
    later adapter pass and are not presented as production-ready yet.
    """

    def __init__(self, parent, service: NasRecoveryService | None = None):
        super().__init__(parent)
        self.service = service or NasRecoveryService()
        self.disks: list[PhysicalDisk] = []
        self.selected_disk: PhysicalDisk | None = None
        self._cancel_image = False
        self._worker: threading.Thread | None = None

        self.title("PC Backup Vault – NAS & RAID Recovery")
        self.configure(bg=TOKENS.bg)
        apply_design_adapter(self)
        normalize_window_geometry(self, 1320, 830, 1040, 680)
        bind_window_escape(self, self._safe_close)
        self.protocol("WM_DELETE_WINDOW", self._safe_close)
        self._build()
        self.after(300, self.refresh_disks)

    def _safe_close(self):
        if self._worker and self._worker.is_alive():
            messagebox.showwarning(
                "NAS Recovery",
                "Ein Lese-/Image-Vorgang läuft noch. Bitte zuerst abbrechen oder beenden lassen.",
                parent=self,
            )
            return
        self.destroy()

    def _build(self):
        header = ttk.Frame(self, style="Surface.TFrame", padding=(18, 13))
        header.pack(fill="x")
        left = ttk.Frame(header, style="Surface.TFrame")
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="NAS & RAID Recovery", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            left,
            text="Geschützter Read-only-Rettungsbereich · Basis: NAS Migration Studio v5.6",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        ttk.Button(header, text="Schließen", command=self._safe_close).pack(side="right")

        safety = tk.Frame(
            self,
            bg="#ecfdf5",
            highlightbackground="#86efac",
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        safety.pack(fill="x", padx=16, pady=(12, 8))
        tk.Label(
            safety,
            text="✓ SICHERHEITSMODUS AKTIV",
            bg="#ecfdf5",
            fg="#166534",
            font=(TOKENS.font_family, 9, "bold"),
        ).pack(side="left")
        tk.Label(
            safety,
            text="Originalplatten: keine Initialisierung · keine Formatierung · keine Reparatur · kein RAID-Rebuild · keine Schreibtests",
            bg="#ecfdf5",
            fg="#166534",
            font=(TOKENS.font_family, 8),
        ).pack(side="left", padx=(14, 0))

        body = ttk.Frame(self, style="Vault.TFrame", padding=(16, 2, 16, 12))
        body.pack(fill="both", expand=True)

        toolbar = ttk.Frame(body, style="Vault.TFrame")
        toolbar.pack(fill="x", pady=(0, 7))
        ttk.Button(toolbar, text="↻ Datenträger erkennen", command=self.refresh_disks).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="Windows-Details", command=self.show_disk_details).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="SMART lesen", command=self.show_smart).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="Read-only Lesetest (4 MiB)", command=self.run_read_test).pack(side="left", padx=(0, 6))
        self.admin_label = ttk.Label(toolbar, style="Muted.TLabel")
        self.admin_label.pack(side="right")

        split = ttk.Panedwindow(body, orient="vertical")
        split.pack(fill="both", expand=True)

        disks_box = ttk.LabelFrame(split, text="1. Direkt mit Windows verbundene Datenträger", padding=8)
        split.add(disks_box, weight=3)
        self.tree = ttk.Treeview(disks_box, height=10)
        configure_table(
            self.tree,
            [
                ("num", "Disk", 60, "center"),
                ("model", "Modell", 250, "w"),
                ("serial", "Seriennummer", 180, "w"),
                ("bus", "Bus", 80, "w"),
                ("size", "Größe", 110, "e"),
                ("status", "Status", 120, "w"),
                ("partition", "Partition", 100, "w"),
                ("offline", "Offline", 70, "center"),
                ("readonly", "RO", 55, "center"),
            ],
        )
        sy = ttk.Scrollbar(disks_box, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(disks_box, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        disks_box.rowconfigure(0, weight=1)
        disks_box.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        lower = ttk.Frame(split, style="Vault.TFrame")
        split.add(lower, weight=2)
        lower.columnconfigure(0, weight=3)
        lower.columnconfigure(1, weight=2)
        lower.rowconfigure(0, weight=1)

        log_box = ttk.LabelFrame(lower, text="Diagnose / Ergebnis", padding=7)
        log_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.log = tk.Text(log_box, wrap="word", height=10, font=("Consolas", 9))
        log_y = ttk.Scrollbar(log_box, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_y.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_y.pack(side="right", fill="y")

        image_box = ttk.LabelFrame(lower, text="2. Sektorweises Image", padding=10)
        image_box.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ttk.Label(
            image_box,
            text="Das Original wird ausschließlich gelesen. Das Image muss auf einem anderen Datenträger liegen.",
            style="Muted.TLabel",
            wraplength=410,
            justify="left",
        ).pack(anchor="w")
        target_row = ttk.Frame(image_box)
        target_row.pack(fill="x", pady=(9, 5))
        self.image_target = tk.StringVar()
        ttk.Entry(target_row, textvariable=self.image_target).pack(side="left", fill="x", expand=True)
        ttk.Button(target_row, text="…", width=3, command=self.pick_image_target).pack(side="left", padx=(5, 0))
        controls = ttk.Frame(image_box)
        controls.pack(fill="x", pady=(3, 6))
        self.image_btn = ttk.Button(controls, text="Image erstellen / fortsetzen", command=self.start_image)
        self.image_btn.pack(side="left")
        self.cancel_btn = ttk.Button(controls, text="Abbrechen", command=self.cancel_image, state="disabled")
        self.cancel_btn.pack(side="right")
        self.progress = ttk.Progressbar(image_box, maximum=100)
        self.progress.pack(fill="x", pady=(4, 4))
        self.progress_text = ttk.Label(image_box, text="Bereit.", style="Muted.TLabel")
        self.progress_text.pack(anchor="w")

        staged = ttk.LabelFrame(image_box, text="Weitere v5.6-Funktionen", padding=8)
        staged.pack(fill="x", pady=(12, 0))
        ttk.Label(
            staged,
            text=(
                "RAID-Image-Analyse · Recovery-Engines · NAS-Netzwerkcheck · SSH-Read-only-Check\n"
                "werden in den nächsten Adapterstufen übernommen. Bis zum jeweiligen TÜV bleiben sie gesperrt."
            ),
            style="Muted.TLabel",
            justify="left",
            wraplength=410,
        ).pack(anchor="w")

        footer = ttk.Frame(self, style="Surface.TFrame", padding=(16, 8))
        footer.pack(fill="x")
        self.state_dot = tk.Canvas(footer, width=16, height=16, bg=TOKENS.surface, highlightthickness=0)
        self.state_dot.pack(side="left")
        self.state_dot_id = self.state_dot.create_oval(3, 3, 13, 13, fill=status_color("off"), outline="")
        self.state_label = ttk.Label(footer, text="Bereit", style="Muted.TLabel")
        self.state_label.pack(side="left", padx=(6, 0))

    def _set_state(self, level: str, text: str):
        self.state_dot.itemconfigure(self.state_dot_id, fill=status_color(level))
        self.state_label.configure(text=text)
        self.update_idletasks()

    def _append(self, text: str):
        self.log.insert("end", str(text).rstrip() + "\n")
        self.log.see("end")

    def _run_worker(self, name, fn, done):
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("NAS Recovery", "Es läuft bereits ein Vorgang.", parent=self)
            return
        self._set_state("checking", name)

        def work():
            try:
                result = fn()
            except Exception as exc:
                self.after(0, lambda: self._worker_error(name, exc))
                return
            self.after(0, lambda: done(result))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _worker_error(self, name, exc):
        self._append(f"FEHLER – {name}: {exc}")
        self._set_state("error", f"{name}: Fehler")
        messagebox.showerror("NAS Recovery", f"{name}\n\n{exc}", parent=self)

    def refresh_disks(self):
        self.admin_label.configure(text=f"Administrator: {'ja' if self.service.is_admin() else 'nein'}")

        def done(disks):
            self.disks = disks
            self.selected_disk = None
            for iid in self.tree.get_children(""):
                self.tree.delete(iid)
            for disk in disks:
                self.tree.insert(
                    "",
                    "end",
                    iid=str(disk.number),
                    values=(
                        disk.number,
                        disk.model,
                        disk.serial or "–",
                        disk.bus or "–",
                        human_bytes(disk.size),
                        disk.status or "–",
                        disk.partition_style or "–",
                        "ja" if disk.is_offline else "nein",
                        "ja" if disk.is_read_only else "nein",
                    ),
                )
            self._append(f"Datenträgererkennung abgeschlossen: {len(disks)} Datenträger.")
            self._set_state("ok", f"{len(disks)} Datenträger erkannt")

        self._run_worker("Datenträger werden gelesen …", self.service.scan_disks, done)

    def _on_select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            self.selected_disk = None
            return
        number = int(selection[0])
        self.selected_disk = next((d for d in self.disks if d.number == number), None)
        if self.selected_disk:
            self._set_state("ok", f"Disk {number} ausgewählt · nur Lesen")

    def _require_disk(self) -> PhysicalDisk | None:
        if not self.selected_disk:
            messagebox.showinfo("NAS Recovery", "Bitte zuerst einen Datenträger auswählen.", parent=self)
            return None
        return self.selected_disk

    def show_disk_details(self):
        disk = self._require_disk()
        if not disk:
            return

        def done(text):
            self._append(f"\n=== Disk {disk.number} – Windows-Details ===\n{text}")
            self._set_state("ok", f"Disk {disk.number}: Details gelesen")

        self._run_worker("Windows-Details werden gelesen …", lambda: self.service.disk_details(disk.number), done)

    def show_smart(self):
        disk = self._require_disk()
        if not disk:
            return

        def done(text):
            self._append(f"\n=== Disk {disk.number} – SMART ===\n{text}")
            self._set_state("ok", f"Disk {disk.number}: SMART gelesen")

        self._run_worker("SMART wird gelesen …", lambda: self.service.smart_report(disk), done)

    def run_read_test(self):
        disk = self._require_disk()
        if not disk:
            return

        def done(result):
            self._append(
                f"Read-only Lesetest erfolgreich: {result.bytes_read:,} Bytes · SHA-256 {result.sha256}"
            )
            self._set_state("ok", f"Disk {disk.number}: Lesetest erfolgreich")

        self._run_worker("Read-only Lesetest läuft …", lambda: self.service.read_test(disk), done)

    def pick_image_target(self):
        disk = self._require_disk()
        initial = f"PhysicalDrive{disk.number}.img" if disk else "NAS_Disk.img"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Image-Zieldatei wählen",
            initialfile=initial,
            defaultextension=".img",
            filetypes=[("Disk Image", "*.img"), ("Alle Dateien", "*.*")],
        )
        if path:
            self.image_target.set(path)

    def start_image(self):
        disk = self._require_disk()
        if not disk:
            return
        target = self.image_target.get().strip()
        if not target:
            self.pick_image_target()
            target = self.image_target.get().strip()
        if not target:
            return
        if not messagebox.askyesno(
            "Sektorweises Image",
            f"Quelle: {disk.device_path}\nZiel: {target}\n\n"
            "Die Quelle wird ausschließlich gelesen. Image jetzt starten?",
            parent=self,
        ):
            return
        self._cancel_image = False
        self.image_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.configure(value=0)

        def progress(done, total):
            pct = (done / total * 100) if total else 0
            self.after(0, lambda: self._image_progress(done, total, pct))

        def job():
            return self.service.create_image(
                disk,
                target,
                progress=progress,
                should_cancel=lambda: self._cancel_image,
            )

        def done(path):
            self.image_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            state = "abgebrochen" if self._cancel_image else "abgeschlossen"
            self._append(f"Image {state}: {path}")
            self._set_state("warn" if self._cancel_image else "ok", f"Image {state}")

        self._run_worker("Sektorweises Image läuft …", job, done)

    def _image_progress(self, done, total, pct):
        self.progress.configure(value=pct)
        total_text = human_bytes(total) if total else "unbekannt"
        self.progress_text.configure(text=f"{pct:.1f} % · {human_bytes(done)} / {total_text}")
        self._set_state("checking", f"Image: {pct:.1f} %")

    def cancel_image(self):
        self._cancel_image = True
        self.cancel_btn.configure(state="disabled")
        self._set_state("warn", "Image-Abbruch angefordert …")


def enable_nas_recovery(AppClass):
    """Attach the NAS module without changing proven backup logic."""
    if getattr(AppClass, "_nas_recovery_enabled", False):
        return AppClass

    def open_nas_recovery(self):
        existing = getattr(self, "_nas_recovery_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return existing
        except Exception:
            pass
        win = NasRecoveryWindow(self)
        self._nas_recovery_window = win
        return win

    AppClass.open_nas_recovery = open_nas_recovery
    AppClass._nas_recovery_enabled = True
    return AppClass
