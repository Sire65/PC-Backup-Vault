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
from .ssh_readonly import SshReadOnlyDiagnostics


class NasNetworkWindow(tk.Toplevel):
    """Read-only NAS network diagnostics with prerequisite-driven controls."""

    def __init__(
        self,
        parent,
        diagnostics: NasNetworkDiagnostics | None = None,
        ssh_diagnostics: SshReadOnlyDiagnostics | None = None,
    ):
        super().__init__(parent)
        self.diagnostics = diagnostics or NasNetworkDiagnostics()
        self.ssh_diagnostics = ssh_diagnostics or SshReadOnlyDiagnostics()
        self._worker: threading.Thread | None = None
        self._basis_ok = False
        self._ssh_reachable = False
        self.host_var = tk.StringVar()
        self.user_var = tk.StringVar()
        self.password_var = tk.StringVar()

        self.title("PC Backup Vault – NAS Netzwerkdiagnose")
        self.configure(bg=TOKENS.bg)
        apply_design_adapter(self)
        normalize_window_geometry(self, 1060, 790, 900, 650)
        bind_window_escape(self, self._safe_close)
        self.protocol("WM_DELETE_WINDOW", self._safe_close)
        self._build()
        self.host_var.trace_add("write", lambda *_: self._host_changed())
        self.user_var.trace_add("write", lambda *_: self._refresh_controls())
        self.password_var.trace_add("write", lambda *_: self._refresh_controls())
        self._refresh_controls()

    def _safe_close(self):
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("NAS Netzwerkdiagnose", "Eine Diagnose läuft noch.", parent=self)
            return
        self.password_var.set("")
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
        self.tree = ttk.Treeview(ports, height=7)
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

        ssh = ttk.LabelFrame(body, text="3. SSH Read-only Systemcheck", padding=10)
        ssh.pack(fill="x", pady=(10, 0))
        ttk.Label(
            ssh,
            text="Nur feste Diagnose-Kommandos. Passwort bleibt nur im Arbeitsspeicher und wird beim Schließen gelöscht.",
            style="Muted.TLabel",
        ).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 7))
        ttk.Label(ssh, text="Benutzer:").grid(row=1, column=0, sticky="w")
        self.user_entry = ttk.Entry(ssh, textvariable=self.user_var, width=20)
        self.user_entry.grid(row=1, column=1, sticky="ew", padx=(6, 14))
        ttk.Label(ssh, text="Passwort:").grid(row=1, column=2, sticky="w")
        self.password_entry = ttk.Entry(ssh, textvariable=self.password_var, show="•", width=24)
        self.password_entry.grid(row=1, column=3, sticky="ew", padx=(6, 14))
        self.btn_ssh = ttk.Button(ssh, text="SSH-Systemcheck starten", command=self.run_ssh)
        self.btn_ssh.grid(row=1, column=4, sticky="e")
        ssh.columnconfigure(1, weight=1)
        ssh.columnconfigure(3, weight=1)
        self.ssh_hint = ttk.Label(ssh, text="Zuerst Basischeck; SSH muss auf Port 22 erreichbar sein.", style="Muted.TLabel")
        self.ssh_hint.grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))

        result = ttk.LabelFrame(body, text="Zusammenfassung", padding=8)
        result.pack(fill="x", pady=(10, 0))
        self.result_label = ttk.Label(result, text="Noch nicht geprüft.", wraplength=980, justify="left")
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
        self._ssh_reachable = False
        self.password_var.set("")
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
        web_state = "normal" if host_ok and self._basis_ok and not busy else "disabled"
        self.btn_http.configure(state=web_state)
        self.btn_https.configure(state=web_state)
        ssh_ready = (
            host_ok
            and self._basis_ok
            and self._ssh_reachable
            and bool(self.user_var.get().strip())
            and bool(self.password_var.get())
            and not busy
        )
        self.btn_ssh.configure(state="normal" if ssh_ready else "disabled")
        entry_state = "disabled" if busy else "normal"
        self.host_entry.configure(state=entry_state)
        self.user_entry.configure(state=entry_state)
        self.password_entry.configure(state=entry_state)
        if busy:
            self._set_state("checking", "Diagnose läuft …")
        elif not host_ok:
            self._set_state("off", "Ziel fehlt oder ist ungültig")
        elif not self._basis_ok:
            self._set_state("warn", "Ziel gültig · Basischeck erforderlich")
        elif not self._ssh_reachable:
            self._set_state("warn", "Basischeck abgeschlossen · SSH nicht erreichbar")
        else:
            self._set_state("ok", "Basischeck abgeschlossen · SSH erreichbar")

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
        self.result_label.configure(text=f"Fehler: {exc}")
        self._set_state("error", "Diagnose fehlgeschlagen")
        self._refresh_controls()
        messagebox.showerror("NAS Netzwerkdiagnose", str(exc), parent=self)

    def run_basic(self):
        host = self.host_var.get().strip()
        self._basis_ok = False
        self._ssh_reachable = False
        self.password_var.set("")
        self._clear_results()

        def done(report):
            for port in report.ports:
                self.tree.insert("", "end", values=(port.name, port.port, "erreichbar" if port.open else "nicht erreichbar", port.detail))
            self._basis_ok = True
            self._ssh_reachable = any(p.port == 22 and p.open for p in report.ports)
            open_names = [p.name for p in report.ports if p.open]
            services = ", ".join(open_names) if open_names else "keine der geprüften Standarddienste"
            self.result_label.configure(text=f"{report.host} wurde als {report.resolved_ip} aufgelöst. Erreichbar: {services}.")
            self.ssh_hint.configure(
                text=("SSH erreichbar. Benutzer und Passwort eingeben." if self._ssh_reachable else "SSH ist auf Port 22 nicht erreichbar; Systemcheck bleibt gesperrt.")
            )

        self._run(lambda: self.diagnostics.basic_report(host), done)

    def run_http(self, https: bool):
        host = self.host_var.get().strip()
        scheme = "HTTPS" if https else "HTTP"

        def done(result):
            status, server = result
            self.result_label.configure(text=f"{scheme}-Antwort erhalten: HTTP-Status {status}. Server: {server or 'nicht angegeben'}.")

        self._run(lambda: self.diagnostics.http_probe(host, https=https), done)

    def run_ssh(self):
        if not self._ssh_reachable:
            return
        host = self.host_var.get().strip()
        username = self.user_var.get().strip()
        password = self.password_var.get()
        # Keep only this local reference during the worker call. It is never placed
        # in a command line, file, log or report.

        def done(report):
            lines = [
                f"SSH Read-only Systemcheck: {report.host}:{report.port} als {report.username}",
                f"Host-Key: {report.host_key_type} · {report.host_key_fingerprint}",
            ]
            for item in report.results:
                state = "OK" if item.exit_status == 0 else f"Exit {item.exit_status}"
                text = item.stdout.strip() or item.stderr.strip() or "keine Ausgabe"
                lines.append(f"\n[{item.title}] {state}\n{text}")
            self.result_label.configure(text="\n".join(lines))
            self.password_var.set("")
            self.ssh_hint.configure(text="Systemcheck abgeschlossen. Passwort wurde aus der Eingabe gelöscht.")

        def job():
            return self.ssh_diagnostics.run(host, username, password)

        self._run(job, done)
