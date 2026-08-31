from __future__ import annotations


def enable_nas_control_center_bridge():
    """Route the Leitstand NAS card to the protected NAS module.

    This bridge is intentionally tiny. It exists only while the Leitstand itself
    still marks NAS v5.6 as an integration-stage module. Business logic remains
    inside nas_recovery.service and never enters control_center.py.
    """
    import control_center

    cls = control_center.ControlCenterWindow
    if getattr(cls, "_nas_recovery_bridge_enabled", False):
        return cls

    original_open_module = cls.open_module

    def open_module(self, spec):
        if getattr(spec, "module_id", None) == "nas":
            opener = getattr(self.app, "open_nas_recovery", None)
            if callable(opener):
                try:
                    return opener()
                except Exception as exc:
                    from tkinter import messagebox

                    messagebox.showerror(
                        "NAS & RAID Recovery",
                        f"Das geschützte NAS-Modul konnte nicht geöffnet werden.\n\n{exc}",
                        parent=self,
                    )
                    return None
        return original_open_module(self, spec)

    cls.open_module = open_module
    cls._nas_recovery_bridge_enabled = True
    return cls
