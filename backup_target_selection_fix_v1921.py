from __future__ import annotations

from backup_source_selection_safety_v1922 import apply_backup_source_selection_safety_v1922


def choose_effective_media(rows: list[dict], selected_id: str | None) -> dict | None:
    """Return the target for this run.

    Rules:
    - an explicitly selected, enabled row wins;
    - if the selected row is disabled (or nothing is selected) and exactly one
      medium is enabled, use that one automatically;
    - never guess when several enabled media exist.
    """
    selected = next((r for r in rows if r.get("id") == selected_id), None)
    if selected and selected.get("enabled"):
        return selected
    enabled = [r for r in rows if r.get("enabled")]
    return enabled[0] if len(enabled) == 1 else None


def apply_backup_target_selection_fix_v1921(WorkbenchClass):
    if getattr(WorkbenchClass, "_backup_target_selection_fix_v1921", False):
        return
    WorkbenchClass._backup_target_selection_fix_v1921 = True

    original_init = WorkbenchClass.__init__
    original_prepare = WorkbenchClass._prepare_selected_target

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        try:
            self.media_tree.heading("active", text="Freigabe")
        except Exception:
            pass
        try:
            parent = self.target_info.master
            import tkinter.ttk as ttk
            self.media_hint_v1921 = ttk.Label(
                parent,
                text="Haken = Medium freigegeben · blaue Zeile = Ziel dieses Backup-Laufs",
            )
            self.media_hint_v1921.pack(anchor="w", pady=(5, 0), before=self.target_info)
        except Exception:
            pass

    def _prepare_selected_target(self):
        rows = list(self._media_rows())
        selected_id = self.media_tree.selection()[0] if self.media_tree.selection() else None
        effective = choose_effective_media(rows, selected_id)
        if effective is None:
            enabled = [r.get("name") or r.get("id") for r in rows if r.get("enabled")]
            if enabled:
                raise RuntimeError(
                    "Mehrere Sicherungsmedien sind freigegeben. Bitte die gewünschte aktive Zeile anklicken.\n\n"
                    "Freigegeben: " + ", ".join(str(x) for x in enabled)
                )
            raise RuntimeError("Bitte mindestens ein Sicherungsmedium freigeben.")

        if effective.get("id") != selected_id:
            iid = str(effective.get("id") or "")
            try:
                if iid and self.media_tree.exists(iid):
                    self.media_tree.selection_set(iid)
                    self.media_tree.focus(iid)
                    self.media_tree.see(iid)
                    self._media_selected()
            except Exception:
                pass

        return original_prepare(self)

    WorkbenchClass.__init__ = __init__
    WorkbenchClass._prepare_selected_target = _prepare_selected_target
    apply_backup_source_selection_safety_v1922(WorkbenchClass)
