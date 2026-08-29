from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from kc_backup_program_registry import KCProgramDefinition, KCProgramRegistry, SourceKind, resolve_program_scope
from kc_backup_program_store import save_program_registry


class KCProgramsWindow(tk.Toplevel):
    def __init__(self, master, *, registry: KCProgramRegistry, store_path: str | Path, on_backup=None):
        super().__init__(master)
        self.registry = registry
        self.store_path = Path(store_path)
        self.on_backup = on_backup
        self.title("Backup Central – KC Programme")
        self.geometry("1120x720")
        self.minsize(900, 600)
        self._build()
        self.refresh()

    def _build(self):
        head = ttk.Frame(self, padding=12); head.pack(fill="x")
        ttk.Label(head, text="KC Programme", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(head, text="Sicherungsumfang konfigurieren · prüfen · One-Touch starten").pack(side="left", padx=16)

        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        left = ttk.Frame(body, padding=6); right = ttk.Frame(body, padding=6)
        body.add(left, weight=2); body.add(right, weight=3)

        self.program_tree = ttk.Treeview(left, columns=("status", "sources", "missing"), show="tree headings", height=18)
        self.program_tree.heading("#0", text="Programm"); self.program_tree.column("#0", width=190)
        self.program_tree.heading("status", text="Status"); self.program_tree.column("status", width=90)
        self.program_tree.heading("sources", text="Bereiche"); self.program_tree.column("sources", width=80)
        self.program_tree.heading("missing", text="Fehlt"); self.program_tree.column("missing", width=70)
        self.program_tree.pack(fill="both", expand=True)
        self.program_tree.bind("<<TreeviewSelect>>", lambda _e: self._render_sources())

        self.title_label = ttk.Label(right, text="Programm wählen", font=("Segoe UI", 14, "bold")); self.title_label.pack(anchor="w")
        self.note_label = ttk.Label(right, text="", wraplength=610); self.note_label.pack(anchor="w", pady=(4, 8))
        self.source_tree = ttk.Treeview(right, columns=("required", "kind", "path"), show="tree headings", height=14)
        self.source_tree.heading("#0", text="Sicherungsbereich"); self.source_tree.column("#0", width=220)
        self.source_tree.heading("required", text="Pflicht"); self.source_tree.column("required", width=70)
        self.source_tree.heading("kind", text="Typ"); self.source_tree.column("kind", width=110)
        self.source_tree.heading("path", text="Quelle"); self.source_tree.column("path", width=360)
        self.source_tree.pack(fill="both", expand=True)

        buttons = ttk.Frame(right); buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Quelle wählen", command=self._choose_source).pack(side="left")
        ttk.Button(buttons, text="Quelle löschen", command=self._clear_source).pack(side="left", padx=6)
        ttk.Button(buttons, text="Probelauf", command=self._preflight).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Jetzt sicher sichern", command=self._backup).pack(side="right")
        self.status = ttk.Label(self, text="", padding=(12, 6)); self.status.pack(fill="x")

    def _selected_program(self) -> KCProgramDefinition | None:
        selection = self.program_tree.selection()
        if not selection: return None
        return self.registry.get(selection[0])

    def _selected_source_id(self) -> str | None:
        selection = self.source_tree.selection()
        return selection[0] if selection else None

    def refresh(self):
        selected = self.program_tree.selection()[0] if self.program_tree.selection() else None
        self.program_tree.delete(*self.program_tree.get_children())
        for program in self.registry.all():
            missing = len(program.missing_required_sources())
            status = "BEREIT" if program.ready else "OFFEN"
            self.program_tree.insert("", "end", iid=program.program_id, text=program.display_name,
                                     values=(status, len(program.sources), missing))
        if selected and self.program_tree.exists(selected): self.program_tree.selection_set(selected)
        self._render_sources()

    def _render_sources(self):
        self.source_tree.delete(*self.source_tree.get_children())
        program = self._selected_program()
        if not program:
            self.title_label.config(text="Programm wählen"); self.note_label.config(text=""); return
        self.title_label.config(text=program.display_name)
        self.note_label.config(text=program.notes or "")
        for source in program.sources:
            self.source_tree.insert("", "end", iid=source.source_id, text=source.label,
                                    values=("Ja" if source.requirement.value == "REQUIRED" else "Nein", source.kind.value,
                                            source.configured_path or "nicht konfiguriert"))
        scope = resolve_program_scope(program)
        self.status.config(text=("Bereit für Probelauf und Sicherung." if scope.ready else f"Nicht bereit: {len(scope.blockers)} Blocker") +
                                (f" · {len(scope.warnings)} Hinweis(e)" if scope.warnings else ""))

    def _replace_program(self, updated: KCProgramDefinition):
        self.registry = KCProgramRegistry(updated if p.program_id == updated.program_id else p for p in self.registry.all())
        save_program_registry(self.store_path, self.registry)
        self.refresh()
        if self.program_tree.exists(updated.program_id): self.program_tree.selection_set(updated.program_id); self._render_sources()

    def _choose_source(self):
        program = self._selected_program(); source_id = self._selected_source_id()
        if not program or not source_id: return
        source = next(s for s in program.sources if s.source_id == source_id)
        if source.kind in {SourceKind.FOLDER, SourceKind.DOCUMENTS}:
            chosen = filedialog.askdirectory(title=f"Quelle wählen – {source.label}", parent=self)
        else:
            chosen = filedialog.askopenfilename(title=f"Exportdatei wählen – {source.label}", parent=self)
        if not chosen: return
        sources = tuple(replace(s, configured_path=chosen) if s.source_id == source_id else s for s in program.sources)
        try: self._replace_program(replace(program, sources=sources))
        except Exception as exc: messagebox.showerror("KC Programme", f"Quelle konnte nicht gespeichert werden:\n{exc}", parent=self)

    def _clear_source(self):
        program = self._selected_program(); source_id = self._selected_source_id()
        if not program or not source_id: return
        sources = tuple(replace(s, configured_path=None) if s.source_id == source_id else s for s in program.sources)
        try: self._replace_program(replace(program, sources=sources))
        except Exception as exc: messagebox.showerror("KC Programme", f"Änderung konnte nicht gespeichert werden:\n{exc}", parent=self)

    def _preflight(self):
        program = self._selected_program()
        if not program: return
        scope = resolve_program_scope(program)
        if scope.ready:
            text = f"Probelauf für {program.display_name}: BEREIT\n\n{len(scope.paths)} Quelle(n) freigegeben."
            if scope.warnings: text += "\n\nHinweise:\n" + "\n".join(f"• {w}" for w in scope.warnings)
            messagebox.showinfo("KC Programme – Probelauf", text, parent=self)
        else:
            messagebox.showwarning("KC Programme – Probelauf", "Es wurde nichts gestartet.\n\n" + "\n".join(f"• {b}" for b in scope.blockers), parent=self)

    def _backup(self):
        program = self._selected_program()
        if not program: return
        scope = resolve_program_scope(program)
        if not scope.ready:
            self._preflight(); return
        if self.on_backup is None:
            messagebox.showinfo("KC Programme", "Sicherungsumfang ist bereit; es ist noch kein Ausführungsadapter verbunden.", parent=self); return
        self.on_backup(program, scope)
