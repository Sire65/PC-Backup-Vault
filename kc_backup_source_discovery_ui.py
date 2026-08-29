from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from kc_backup_program_registry import KCProgramRegistry
from kc_backup_program_store import save_program_registry
from kc_backup_source_adoption import prepare_candidate_adoption
from kc_backup_source_discovery import SourceCandidate, discover_candidates


class SourceDiscoveryWindow(tk.Toplevel):
    """Read-only discovery plus explicitly confirmed, guarded source adoption."""

    def __init__(self, master, *, registry: KCProgramRegistry, store_path: str | Path):
        super().__init__(master)
        self.registry = registry
        self.store_path = Path(store_path)
        self._candidates: dict[str, SourceCandidate] = {}
        self.title("Backup Central – KC Quellen finden")
        self.geometry("1160x700")
        self.minsize(920, 570)
        self._build()

    def _build(self):
        head = ttk.Frame(self, padding=12)
        head.pack(fill="x")
        ttk.Label(head, text="KC Quellen finden", font=("Segoe UI", 17, "bold")).pack(side="left")
        ttk.Label(head, text="Vorschläge · Übernahme nur nach Bestätigung").pack(side="left", padx=16)
        ttk.Button(head, text="Suchordner wählen …", command=self._choose_root).pack(side="right")

        info = ttk.Label(
            self,
            text=("Die Suche liest nur Dateinamen und Ordnerstrukturen unter dem gewählten Stammordner. "
                  "Ein Treffer wird niemals automatisch übernommen. Mit 'Als Quelle übernehmen' bestätigen Sie genau einen "
                  "markierten Kandidaten; danach erfolgt sofort eine read-only Prüfung."),
            wraplength=1080,
            padding=(12, 0, 12, 10),
        )
        info.pack(fill="x")

        self.tree = ttk.Treeview(
            self,
            columns=("source", "score", "path", "reason"),
            show="tree headings",
            height=23,
        )
        for key, text, width in (
            ("#0", "Programm", 150),
            ("source", "Sicherungsbereich", 190),
            ("score", "Treffer", 70),
            ("path", "Vorschlag", 440),
            ("reason", "Warum gefunden", 260),
        ):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.tree.bind("<Double-1>", lambda _e: self._copy_selected())

        bottom = ttk.Frame(self, padding=(12, 0, 12, 12))
        bottom.pack(fill="x")
        self.status = ttk.Label(bottom, text="Noch kein Suchordner gewählt.")
        self.status.pack(side="left")
        ttk.Button(bottom, text="Als Quelle übernehmen", command=self._adopt_selected).pack(side="right")
        ttk.Button(bottom, text="Pfad kopieren", command=self._copy_selected).pack(side="right", padx=(0, 8))

    def _choose_root(self):
        root = filedialog.askdirectory(title="Stammordner für read-only KC-Quellensuche wählen", parent=self)
        if not root:
            return
        self.status.config(text="Suche läuft …")
        self.update_idletasks()
        try:
            candidates = discover_candidates(root, self.registry.all())
        except Exception as exc:
            self.status.config(text="Suche fehlgeschlagen.")
            messagebox.showerror("KC Quellen finden", str(exc), parent=self)
            return
        self.tree.delete(*self.tree.get_children())
        self._candidates.clear()
        by_program = {p.program_id: p for p in self.registry.all()}
        source_labels = {
            (p.program_id, s.source_id): s.label
            for p in self.registry.all()
            for s in p.sources
        }
        for index, item in enumerate(candidates):
            iid = f"candidate-{index}"
            self._candidates[iid] = item
            program = by_program[item.program_id]
            self.tree.insert(
                "", "end", iid=iid, text=program.display_name,
                values=(source_labels.get((item.program_id, item.source_id), item.source_id),
                        f"{item.score}%", str(item.path), item.reason),
            )
        self.status.config(
            text=(f"{len(candidates)} Vorschlag/Vorschläge gefunden unter: {root}"
                  if candidates else f"Keine ausreichend sicheren Vorschläge gefunden unter: {root}")
        )

    def _selected_candidate(self) -> SourceCandidate | None:
        selected = self.tree.selection()
        if not selected:
            return None
        return self._candidates.get(selected[0])

    def _copy_selected(self):
        candidate = self._selected_candidate()
        if candidate is None:
            return
        path = str(candidate.path)
        self.clipboard_clear()
        self.clipboard_append(path)
        self.status.config(text=f"Pfad kopiert: {path}")

    def _adopt_selected(self):
        candidate = self._selected_candidate()
        if candidate is None:
            messagebox.showinfo("KC Quellen finden", "Bitte zuerst einen Vorschlag markieren.", parent=self)
            return
        try:
            updated_registry, preview = prepare_candidate_adoption(self.registry, candidate)
            program = self.registry.get(candidate.program_id)
        except Exception as exc:
            messagebox.showerror("Quelle übernehmen", f"Quelle kann nicht übernommen werden:\n{exc}", parent=self)
            return

        confirm = messagebox.askyesno(
            "Quelle übernehmen – Bestätigung",
            f"Programm: {program.display_name}\n"
            f"Sicherungsbereich: {preview.source_label}\n"
            f"Quelle: {preview.path}\n\n"
            "Diese Quelle jetzt in das KC-Programmregister eintragen?\n\n"
            "Es wird keine Sicherung gestartet. Direkt danach erfolgt nur ein read-only Probelauf.",
            parent=self,
        )
        if not confirm:
            return

        old_registry = self.registry
        try:
            save_program_registry(self.store_path, updated_registry)
            # Re-evaluate the already validated in-memory result. No backup is started.
            if not preview.source_ok:
                raise RuntimeError(preview.source_message)
            self.registry = updated_registry
        except Exception as exc:
            try:
                save_program_registry(self.store_path, old_registry)
            except Exception as rollback_exc:
                messagebox.showerror(
                    "Quelle übernehmen – Rollbackfehler",
                    f"Übernahme fehlgeschlagen: {exc}\n\n"
                    f"Auch das Zurückschreiben des vorherigen Registers ist fehlgeschlagen: {rollback_exc}",
                    parent=self,
                )
                return
            messagebox.showerror(
                "Quelle übernehmen",
                f"Übernahme wurde zurückgerollt.\n\n{exc}",
                parent=self,
            )
            return

        if preview.program_ready_after:
            result = "GESAMTPROGRAMM BEREIT"
            detail = "Alle Pflichtbereiche sind jetzt konfiguriert und vorhanden."
        else:
            result = "EINZELQUELLE OK – GESAMTPROGRAMM NOCH NICHT BEREIT"
            detail = "Verbleibende Blocker:\n" + "\n".join(f"• {item}" for item in preview.remaining_blockers)
        if preview.warnings:
            detail += "\n\nHinweise:\n" + "\n".join(f"• {item}" for item in preview.warnings)

        self.status.config(text=f"Quelle übernommen: {program.display_name} / {preview.source_label}")
        messagebox.showinfo(
            "Quelle übernommen – Probelauf",
            f"{preview.source_message}\n\n{result}\n\n{detail}",
            parent=self,
        )
