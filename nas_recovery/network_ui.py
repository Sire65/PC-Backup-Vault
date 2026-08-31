from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from framework_core_adapters import (
    TOKENS,
    apply_design_adapter,
    bind_window_escape,
    configure_table,
    normalize_window_geometry,
    status_color,
)
from .network import NasNetworkDiagnostics, normalize_host


class NasNetworkWindow(tk.Toplevel):
    """Read-only NAS network diagnostics with prerequisite-driven controls."""

    def __init__(self, parent, diagnostics: NasNetworkDiagnostics | None = None):
        super().__init__(parent)
        self.diagnostics = diagnostics or NasNetworkDiagnostics()
        self._worker: threading.Thread | None = None
        self._basis_ok = False
        self.host_var = tk.StringVar()

        self.title("PC Backup Vault – NAS Netzwerkdiagnose")
        self.configure(bg=TOKENS.bg)
        apply_design_adapter(self)
        normalize_window_geometry(self, 980, 650, 820, 560)
        bind_window_escape(self, self._safe_close)
        self.protocol("WM_DELETE_WINDOW", self._safe_close)
        self._build()
        self.host_var.trace_add("write", lambda *_: self._host_changed())
        self._refresh_controls()

    def _safe_close(self):
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("NAS Netzwerkdiagnose", "Eine Diagnose läuft noch.", parent=self)
            return
        self.destroy()

    def _build(self):
        header = ttk.Frame(self, style="Surface.TFrame", padding=(18, 13))
        header.pack(fill="x")
        left = ttk.Frame(header, style="Surface.TFrame")
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="NAS Netzwerkdiagnose", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Nur Lesen · keine NAS-Konfiguration wird verändert", style="Muted.TLabel").pack(anchor="w")
        ttk.Button(header, text="Schließen", command=self._safe_close).pack(side="right")

        body = ttk.Frame(self, style="Vault.TFrame", padding=16)
        body.pack(fill="both", expand=True)

        target = ttk.LabelFrame(body, text="1. NAS-Ziel", padding=10)
        target.pack(fill="x")
        ttk.Label(target, text="Hostname oder IP-Adresse:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.host_entry = ttk.Entry(target, textvariable=self.host_var, width=40)
        self.host_entry.grid(row=0, column=1, sticky="ew")
        target.columnconfigure(1, weight=1)
        self.host_hint = ttk.Label(target, text="Ziel eingeben, danach wird der Basischeck freigegeben.", style="Muted.TLabel")
        self.host_hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))

        actions = ttk.Frame(body, style="Vault.TFrame")
        actions.pack(fill="x", pady=(10, 8))
        self.btn_basic = ttk.Button(actions, text="2. Basischeck starten", command=self.run_basic)
        self.btn_basic.pack(side="left", padx=(0, 6))
        self.btn_http = ttk.Button(actions, text="HTTP-Weboberfläche prüfen", command=lambda: self.run_http(False))
        self.btn_http.pack(side="left", padx=(0, 6))
        self.btn_https = ttk.Button(actions, text="HTTPS-Weboberfläche prüfen", command=lambda: self.run_http(True))
        self.btn_https.pack(side="left")

        ports = ttk.LabelFrame(body, text="Ergebnis / Dienste", padding=8)
        ports.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(ports, height=10)
        configure_table(self.tree, [
            ("service", "Dienst", 150, "w"),
            ("port", "Port", 70, "center"),
            ("state", "Status", 100, "w"),
            ("detail", "Hinweis", 500, "w"),
        ])
        sy = ttk.Scrollbar(ports, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sy.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sy.pack(side="right", fill="y")

        result = ttk.LabelFrame(body, text="Zusammenfassung", padding=8)
        result.pack(fill="x", pady=(10, 0))
        self.result_label = ttk.Label(result, text="Noch nicht geprüft.", wraplength=900, justify="left")
        self.result_label.pack(anchor="w")

        footer = ttk.Frame(self, style="Surface.TFrame", padding=(16, 8))
        footer.pack(fill="x")
        self.dot = tk.Canvas(footer, width=16, height=16, bg=TOKENS.surface, highlightthickness=0)
        self.dot.pack(side="left")
        self.dot_id = self.dot.create_oval(3, 3, 13, 13, fill=status_color("off"), outline="")
        self.state_label = ttk.Label(footer, text="Ziel fehlt", style="Muted.TLabel")
        self.state_label.pack(side="left", padx=(6, 0))

    def _host_valid(self) -> bool:
        try:
            normalize_host(self.host_var.get())
            return True
        except ValueError:
            return False

    def _host_changed(self):
        self._basis_ok = False
        self._clear_results()
        self._refresh_controls()

    def _clear_results(self):
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self.result_label.configure(text="Noch nicht geprüft.")

    def _refresh_controls(self):
        busy = bool(self._worker and self._worker.is_alive())
        host_ok = self._host_valid()
        self.btn_basic.configure(state="normal" if host_ok and not busy else "disabled")
        # Web probes depend on a successful basis check. They must never be active
        # merely because text happens to be present in the host field.
        web_state = "normal" if host_ok and self._basis_ok and not busy else "disabled"
        self.btn_http.configure(state=web_state)
        self.btn_https.configure(state=web_state)
        self.host_entry.configure(state="disabled" if busy else "normal")
        if busy:
            self._set_state("checking", "Diagnose läuft …")
        elif not host_ok:
            self._set_state("off", "Ziel fehlt oder ist ungültig")
        elif not self._basis_ok:
            self._set_state("warn", "Ziel gültig · Basischeck erforderlich")
        else:
            self._set_state("ok", "Basischeck abgeschlossen")

    def _set_state(self, level: str, text: str):
        self.dot.itemconfigure(self.dot_id, fill=status_color(level))
        self.state_label.configure(text=text)

    def _run(self, fn, done):
        if self._worker and self._worker.is_alive():
            return
        def work():
            try:
                result = fn()
            except Exception as exc:
                self.after(0, lambda: self._error(exc))
                return
            self.after(0, lambda: self._done(done, result))
        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()
        self._refresh_controls()

    def _done(self, callback, result):
        callback(result)
        self._worker = None
        self._refresh_controls()

    def _error(self, exc):
        self._worker = None
        self._basis_ok = False
        self.result_label.configure(text=f"Fehler: {exc}")
        self._set_state("error", "Diagnose fehlgeschlagen")
        self._refresh_controls()
        messagebox.showerror("NAS Netzwerkdiagnose", str(exc), parent=self)

    def run_basic(self):
        host = self.host_var.get().strip()
        self._basis_ok = False
        self._clear_results()
        def done(report):
            for port in report.ports:
                self.tree.insert("", "end", values=(port.name, port.port, "erreichbar" if port.open else "nicht erreichbar", port.detail))
            self._basis_ok = True
            open_names = [p.name for p in report.ports if p.open]
            services = ", ".join(open_names) if open_names else "keine der geprüften Standarddienste"
            self.result_label.configure(text=f"{report.host} wurde als {report.resolved_ip} aufgelöst. Erreichbar: {services}.")
        self._run(lambda: self.diagnostics.basic_report(host), done)

    def run_http(self, https: bool):
        host = self.host_var.get().strip()
        scheme = "HTTPS" if https else "HTTP"
        def done(result):
            status, server = result
            self.result_label.configure(text=f"{scheme}-Antwort erhalten: HTTP-Status {status}. Server: {server or 'nicht angegeben'}.")
        self._run(lambda: self.diagnostics.http_probe(host, https=https), done)
