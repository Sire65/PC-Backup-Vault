from __future__ import annotations


def enable_nas_ready_in_control_center(control_center_module):
    """Promote the tested read-only NAS module without duplicating Leitstand logic."""
    if getattr(control_center_module, "_nas_ready_integration_enabled", False):
        return

    ModuleSpec = control_center_module.ModuleSpec
    updated = []
    for spec in control_center_module.MODULES:
        if spec.module_id == "nas":
            updated.append(ModuleSpec("nas", spec.title, "Read-only Diagnose, Image, RAID-Analyse und Recovery-Assistent", spec.icon, "open_nas_recovery", "ready"))
        else:
            updated.append(spec)
    control_center_module.MODULES = tuple(updated)

    original_open = control_center_module.ControlCenterWindow.open_module

    def open_module(self, spec):
        if spec.module_id == "nas":
            opener = getattr(self.app, "open_nas_recovery", None)
            if callable(opener):
                return opener()
        return original_open(self, spec)

    control_center_module.ControlCenterWindow.open_module = open_module
    control_center_module._nas_ready_integration_enabled = True
