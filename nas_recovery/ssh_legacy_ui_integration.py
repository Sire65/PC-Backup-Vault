from __future__ import annotations

from tkinter import ttk

from .ssh_legacy_probe import LegacySshProbe


def _find_ssh_frame(window):
    for child in window.winfo_children():
        for nested in child.winfo_children():
            try:
                if isinstance(nested, ttk.LabelFrame) and str(nested.cget("text")) == "3. SSH Read-only Systemcheck":
                    return nested
            except Exception:
                pass
    return None


def enable_legacy_ssh_probe(NasNetworkWindowClass):
    """Add a prerequisite-gated, credential-free legacy SSH banner probe.

    This integration never enables weak algorithms. It only identifies an old SSH
    server and explains whether a separate isolated compatibility path is required.
    """
    if getattr(NasNetworkWindowClass, "_legacy_ssh_probe_enabled", False):
        return NasNetworkWindowClass

    original_build = NasNetworkWindowClass._build
    original_refresh = NasNetworkWindowClass._refresh_controls
    original_host_changed = NasNetworkWindowClass._host_changed

    def run_legacy_probe(self):
        if not (getattr(self, "_basis_ok", False) and getattr(self, "_ssh_reachable", False)):
            return
        host = self.host_var.get().strip()
        probe = getattr(self, "_legacy_ssh_probe", None) or LegacySshProbe()
        self._legacy_ssh_probe = probe

        def done(profile):
            lines = [
                "SSH-Kompatibilitätsprofil",
                f"Banner: {profile.banner}",
                f"Legacy-Hinweis: {'ja' if profile.looks_legacy else 'nein'}",
                f"ssh-dss in aktueller Laufzeit verfügbar: {'ja' if profile.dss_runtime_available else 'nein'}",
                "",
                profile.recommendation,
            ]
            self.result_label.configure(text="\n".join(lines))
            if profile.looks_legacy:
                self.ssh_hint.configure(text="Legacy-Hinweis erkannt. Keine schwache SSH-Option wurde automatisch aktiviert.")
            else:
                self.ssh_hint.configure(text="Kein eindeutiger Legacy-Hinweis. Standard-Read-only-SSH kann verwendet werden.")

        self._run(lambda: probe.profile(host), done)

    def wrapped_build(self, *args, **kwargs):
        result = original_build(self, *args, **kwargs)
        frame = _find_ssh_frame(self)
        if frame is not None:
            self.btn_legacy_probe = ttk.Button(
                frame,
                text="Legacy-SSH-Profil prüfen",
                command=lambda: run_legacy_probe(self),
                state="disabled",
            )
            self.btn_legacy_probe.grid(row=3, column=0, columnspan=2, sticky="w", pady=(7, 0))
            ttk.Label(
                frame,
                text="Ohne Anmeldung: nur SSH-Banner lesen. Schwache Algorithmen werden nicht automatisch freigeschaltet.",
                style="Muted.TLabel",
            ).grid(row=3, column=2, columnspan=3, sticky="w", padx=(8, 0), pady=(7, 0))
        return result

    def wrapped_refresh(self, *args, **kwargs):
        result = original_refresh(self, *args, **kwargs)
        button = getattr(self, "btn_legacy_probe", None)
        if button is not None:
            worker = getattr(self, "_worker", None)
            busy = bool(worker and worker.is_alive())
            enabled = bool(
                getattr(self, "_basis_ok", False)
                and getattr(self, "_ssh_reachable", False)
                and not busy
            )
            button.configure(state="normal" if enabled else "disabled")
        return result

    def wrapped_host_changed(self, *args, **kwargs):
        result = original_host_changed(self, *args, **kwargs)
        button = getattr(self, "btn_legacy_probe", None)
        if button is not None:
            button.configure(state="disabled")
        return result

    NasNetworkWindowClass._build = wrapped_build
    NasNetworkWindowClass._refresh_controls = wrapped_refresh
    NasNetworkWindowClass._host_changed = wrapped_host_changed
    NasNetworkWindowClass.run_legacy_probe = run_legacy_probe
    NasNetworkWindowClass._legacy_ssh_probe_enabled = True
    return NasNetworkWindowClass
