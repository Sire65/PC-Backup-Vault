from __future__ import annotations

import tkinter as tk
from datetime import datetime
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

from .raid_analysis import assess_image_set, render_worksheet, save_worksheet
from .recovery_engines import detect_recovery_engines, launch_engine
from .service import human_bytes


class RaidWorkspaceWindow(tk.Toplevel):
    """Read-only RAID workspace operating exclusively on image files."""

    def __init__(self, parent):
        super().__init__(parent)
        self.images: list[str] = []
        self.assessment = None
        self.engines = ()
        self.title("PC Backup Vault – RAID-Image-Analyse")
        self.configure(bg=TOKENS.bg)
        apply_design_adapter(self)
        normalize_window_geometry(self, 1280, 800, 1000, 650)
        bind_window_escape(self, self.destroy)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._build()
        self.refresh_engines()

    def _build(self):
        header = ttk.Frame(self, style="Surface.TFrame", padding=(18, 13))
        header.pack(fill="x")
        left = ttk.Frame(header, style="Surface.TFrame")
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="RAID-Image-Analyse", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            left,
            text="Nur Image-Dateien · keine Originalplatten · keine automatische RAID-Rekonstruktion",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        ttk.Button(header, text="Schließen", command=self.destroy).pack(side="right")

        safety = tk.Frame(self, bg="#ecfdf5", highlightbackground="#86efac", highlightthickness=1, padx=12, pady=8)
        safety.pack(fill="x", padx=16, pady=(12, 8))
        tk.Label(safety, text="✓ IMAGE-MODUS", bg="#ecfdf5", fg="#166534", font=(TOKENS.font_family, 9, "bold")).pack(side="left")
        tk.Label(
            safety,
            text="Analyse erfolgt ausschließlich lesend. RAID-Parameter werden dokumentiert, nicht automatisch auf Datenträger geschrieben.",
            bg="#ecfdf5", fg="#166534", font=(TOKENS.font_family, 8),
        ).pack(side="left", padx=(14, 0))

        body = ttk.Frame(self, style="Vault.TFrame", padding=(16, 2, 16, 12))
        body.pack(fill="both", expand=True)
        split = ttk.Panedwindow(body, orient="horizontal")
        split.pack(fill="both", expand=True)

        left_box = ttk.Frame(split, style="Vault.TFrame")
        right_box = ttk.Frame(split, style="Vault.TFrame")
        split.add(left_box, weight=3)
        split.add(right_box, weight=2)

        images_box = ttk.LabelFrame(left_box, text="1. RAID-Mitglied-Images", padding=8)
        images_box.pack(fill="both", expand=True, padx=(0, 6))
        actions = ttk.Frame(images_box)
        actions.pack(fill="x", pady=(0, 7))
        ttk.Button(actions, text="＋ Images auswählen", command=self.choose_images).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Header prüfen", command=self.inspect).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="RAID-Arbeitsblatt speichern", command=self.save_sheet).pack(side="left")

        self.tree = ttk.Treeview(images_box, height=12)
        configure_table(self.tree, [
            ("name", "Image", 230, "w"),
            ("size", "Größe", 110, "e"),
            ("signatures", "Signaturen", 220, "w"),
            ("hash", "SHA-256 Kopf", 260, "w"),
            ("warning", "Hinweis", 280, "w"),
        ])
        sy = ttk.Scrollbar(images_box, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(images_box, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.pack(fill="both", expand=True)
        sx.pack(fill="x")

        result_box = ttk.LabelFrame(left_box, text="Bewertung", padding=8)
        result_box.pack(fill="x", padx=(0, 6), pady=(8, 0))
        self.result = ttk.Label(result_box, text="Noch keine Images geprüft.", style="Muted.TLabel", wraplength=720, justify="left")
        self.result.pack(anchor="w")

        engines_box = ttk.LabelFrame(right_box, text="2. Recovery-Engines", padding=8)
        engines_box.pack(fill="both", expand=True, padx=(6, 0))
        erow = ttk.Frame(engines_box)
        erow.pack(fill="x", pady=(0, 7))
        ttk.Button(erow, text="↻ Engines suchen", command=self.refresh_engines).pack(side="left")
        ttk.Button(erow, text="Ausgewählte Engine starten", command=self.start_selected_engine).pack(side="right")

        self.engine_tree = ttk.Treeview(engines_box, height=8)
        configure_table(self.engine_tree, [
            ("engine", "Engine", 150, "w"),
            ("installed", "Erkannt", 80, "center"),
            ("path", "Pfad", 330, "w"),
            ("purpose", "Stärke", 340, "w"),
        ])
        esy = ttk.Scrollbar(engines_box, orient="vertical", command=self.engine_tree.yview)
        esx = ttk.Scrollbar(engines_box, orient="horizontal", command=self.engine_tree.xview)
        self.engine_tree.configure(yscrollcommand=esy.set, xscrollcommand=esx.set)
        self.engine_tree.pack(fill="both", expand=True)
        esx.pack(fill="x")

        note = ttk.LabelFrame(right_box, text="Arbeitsregel", padding=8)
        note.pack(fill="x", padx=(6, 0), pady=(8, 0))
        ttk.Label(
            note,
            text=(
                "Mindestens zwei Recovery-Engines können bei kritischen RAID-Fällen unabhängig mit denselben Images geprüft werden. "
                "Das Programm übergibt absichtlich keinen PhysicalDrive-Pfad automatisch an eine Engine."
            ),
            style="Muted.TLabel", wraplength=430, justify="left",
        ).pack(anchor="w")

        footer = ttk.Frame(self, style="Surface.TFrame", padding=(16, 8))
        footer.pack(fill="x")
        self.state_dot = tk.Canvas(footer, width=16, height=16, bg=TOKENS.surface, highlightthickness=0)
        self.state_dot.pack(side="left")
        self.state_dot_id = self.state_dot.create_oval(3, 3, 13, 13, fill=status_color("off"), outline="")
        self.state = ttk.Label(footer, text="Bereit", style="Muted.TLabel")
        self.state.pack(side="left", padx=(6, 0))

    def _set_state(self, level: str, text: str):
        self.state_dot.itemconfigure(self.state_dot_id, fill=status_color(level))
        self.state.configure(text=text)

    def choose_images(self):
        paths = filedialog.askopenfilenames(
            parent=self,
            title="RAID-Mitglied-Images auswählen",
            filetypes=[("Disk Images", "*.img *.dd *.raw *.bin"), ("Alle Dateien", "*.*")],
        )
        if not paths:
            return
        self.images = list(paths)
        self.assessment = None
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        for index, path in enumerate(self.images, 1):
            p = Path(path)
            self.tree.insert("", "end", iid=str(index), values=(p.name, human_bytes(p.stat().st_size), "–", "–", "Noch nicht geprüft"))
        self.result.configure(text=f"{len(self.images)} Image-Datei(en) ausgewählt. Headerprüfung noch nicht ausgeführt.")
        self._set_state("warn", "Images ausgewählt · Prüfung ausstehend")

    def inspect(self):
        if not self.images:
            messagebox.showinfo("RAID-Image-Analyse", "Bitte zuerst Image-Dateien auswählen.", parent=self)
            return
        try:
            assessment = assess_image_set(self.images)
        except Exception as exc:
            self._set_state("error", "Image-Prüfung fehlgeschlagen")
            messagebox.showerror("RAID-Image-Analyse", str(exc), parent=self)
            return
        self.assessment = assessment
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        for index, item in enumerate(assessment.images, 1):
            self.tree.insert(
                "", "end", iid=str(index),
                values=(
                    item.path.name,
                    human_bytes(item.size),
                    ", ".join(item.signatures) if item.signatures else "–",
                    item.sha256_first_mib,
                    "; ".join(item.warnings) if item.warnings else "keine",
                ),
            )
        self.result.configure(text=assessment.summary)
        self._set_state("ok" if assessment.same_size else "warn", "Image-Header geprüft")

    def save_sheet(self):
        if self.assessment is None:
            self.inspect()
        if self.assessment is None:
            return
        default = f"RAID_Arbeitsblatt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="RAID-Arbeitsblatt speichern",
            initialfile=default,
            defaultextension=".txt",
            filetypes=[("Textdatei", "*.txt")],
        )
        if not path:
            return
        content = render_worksheet(self.assessment)
        saved = save_worksheet(path, content)
        self._set_state("ok", f"Arbeitsblatt gespeichert: {saved.name}")
        messagebox.showinfo("RAID-Image-Analyse", f"Arbeitsblatt gespeichert:\n{saved}", parent=self)

    def refresh_engines(self):
        self.engines = detect_recovery_engines()
        for iid in self.engine_tree.get_children(""):
            self.engine_tree.delete(iid)
        for engine in self.engines:
            self.engine_tree.insert(
                "", "end", iid=engine.name,
                values=(engine.name, "JA" if engine.installed else "NEIN", engine.path or "–", engine.purpose),
            )

    def start_selected_engine(self):
        selection = self.engine_tree.selection()
        if not selection:
            messagebox.showinfo("Recovery-Engine", "Bitte zuerst eine Engine auswählen.", parent=self)
            return
        engine = next((e for e in self.engines if e.name == selection[0]), None)
        if not engine or not engine.installed:
            messagebox.showinfo("Recovery-Engine", "Diese Engine wurde auf dem PC nicht gefunden.", parent=self)
            return
        if not messagebox.askyesno(
            "Recovery-Engine starten",
            f"{engine.name} starten?\n\nEs wird absichtlich kein PhysicalDrive-Pfad automatisch übergeben. Arbeiten Sie bevorzugt mit den erstellten Images.",
            parent=self,
        ):
            return
        try:
            launch_engine(engine)
            self._set_state("ok", f"{engine.name} gestartet")
        except Exception as exc:
            self._set_state("error", f"{engine.name}: Startfehler")
            messagebox.showerror("Recovery-Engine", str(exc), parent=self)
