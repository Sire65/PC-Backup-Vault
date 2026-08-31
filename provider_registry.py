from __future__ import annotations

"""Cloud provider registry UI for PC Backup Vault.

Purpose: keep all backup/mirror/object-storage providers visible in one place
without ever exposing secret credentials in the table.  Secrets remain in the
Windows credential store; the registry shows only whether credentials exist.

The current production routing supports B2 and Cloudflare R2.  OCI is listed as
an immediately configurable reserve provider; upload routing is only marked
READY after the provider adapter is enabled in the failback layer.
"""

from dataclasses import dataclass
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import keyring

from config_store import ConfigStore, SERVICE
from object_store import B2Store

try:
    from cloud_failback import get_r2_runtime_config, DECIMAL_GB
except Exception:
    DECIMAL_GB = 1_000_000_000
    get_r2_runtime_config = None


@dataclass
class ProviderRow:
    provider_id: str
    name: str
    kind: str
    enabled: bool
    credentials: str
    free_limit_gb: float | None
    used_bytes: int | None
    free_bytes: int | None
    priority: int
    routing: str
    status: str


def _fmt_gb_bytes(value: int | None) -> str:
    if value is None:
        return "–"
    return f"{max(0, int(value)) / DECIMAL_GB:.2f} GB"


def _fmt_gb(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{float(value):.1f} GB"


def _store_for(cfg: dict):
    if not cfg.get("configured"):
        return None
    return B2Store(
        bucket=str(cfg.get("bucket") or "").strip(),
        endpoint_url=str(cfg.get("endpoint_url") or "").strip(),
        region=str(cfg.get("region") or "").strip(),
        prefix=str(cfg.get("prefix") or "pc-backup-vault").strip(),
        access_key_id=str(cfg.get("access_key_id") or "").strip(),
        application_key=str(cfg.get("application_key") or "").strip(),
    )


def _usage(cfg: dict) -> tuple[int | None, str]:
    store = _store_for(cfg)
    if store is None:
        return None, "nicht eingerichtet"
    try:
        sizes = store.list_prefix_sizes()
        return sum(int(v or 0) for v in sizes.values()), "OK"
    except Exception as exc:
        return None, f"Fehler: {exc}"


def _oci_runtime(store: ConfigStore) -> dict:
    meta = dict((store.data.get("cloud_providers") or {}).get("OCI") or {})
    meta.setdefault("enabled", False)
    meta.setdefault("name", "Oracle OCI Object Storage")
    meta.setdefault("kind", "Backup / Failback")
    meta.setdefault("bucket", "")
    meta.setdefault("endpoint_url", "")
    meta.setdefault("region", "")
    meta.setdefault("prefix", "pc-backup-vault-oci")
    meta.setdefault("free_limit_gb", 20.0)
    meta.setdefault("priority", 2)
    access = keyring.get_password(SERVICE, "oci_access_key_id") or ""
    secret = keyring.get_password(SERVICE, "oci_secret_access_key") or ""
    meta["access_key_id"] = access
    meta["application_key"] = secret
    meta["configured"] = bool(meta.get("enabled") and meta.get("bucket") and meta.get("endpoint_url") and access and secret)
    return meta


def _rows(store: ConfigStore, live: bool = True) -> list[ProviderRow]:
    b2 = dict(store.get_b2_runtime_config())
    b2.setdefault("free_limit_gb", 10.0)
    b2_used, b2_status = _usage(b2) if live else (None, "–")
    b2_limit = float(b2.get("free_limit_gb") or 10.0)
    b2_free = None if b2_used is None else max(0, int(b2_limit * DECIMAL_GB) - b2_used)

    r2 = get_r2_runtime_config(store) if get_r2_runtime_config else {}
    r2 = dict(r2 or {})
    r2.setdefault("free_limit_gb", 10.0)
    r2_used, r2_status = _usage(r2) if live else (None, "–")
    r2_limit = float(r2.get("free_limit_gb") or 10.0)
    r2_free = None if r2_used is None else max(0, int(r2_limit * DECIMAL_GB) - r2_used)

    oci = _oci_runtime(store)
    oci_used, oci_status = _usage(oci) if live and oci.get("configured") else (None, "vorbereitet")
    oci_limit = float(oci.get("free_limit_gb") or 20.0)
    oci_free = None if oci_used is None else max(0, int(oci_limit * DECIMAL_GB) - oci_used)

    return [
        ProviderRow(
            "B2", "Backblaze B2", "Backup / Primär", bool(b2.get("enabled")),
            "hinterlegt" if b2.get("configured") else "fehlt",
            b2_limit, b2_used, b2_free, 1, "AKTIV ROUTBAR", b2_status,
        ),
        ProviderRow(
            "OCI", str(oci.get("name") or "Oracle OCI Object Storage"), str(oci.get("kind") or "Backup / Failback"),
            bool(oci.get("enabled")), "hinterlegt" if oci.get("configured") else "fehlt",
            oci_limit, oci_used, oci_free, int(oci.get("priority") or 2), "RESERVE / ADAPTER FOLGT", oci_status,
        ),
        ProviderRow(
            "R2", "Cloudflare R2", "Backup / Failback", bool(r2.get("enabled")),
            "hinterlegt" if r2.get("configured") else "fehlt",
            r2_limit, r2_used, r2_free, 3, "AKTIV ROUTBAR", r2_status,
        ),
    ]


class ProviderRegistryWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.store = app.store
        self.title("Cloud-Anbieter / Speicherregister")
        self.geometry("1180x560")
        self.minsize(980, 480)
        self._build()
        self.refresh(live=True)

    def _build(self):
        head = ttk.Frame(self, padding=12); head.pack(fill="x")
        ttk.Label(head, text="Cloud-Anbieter / Speicherregister", font=("Segoe UI", 17, "bold")).pack(side="left")
        ttk.Button(head, text="↻ Live prüfen", command=lambda: self.refresh(live=True)).pack(side="right")

        ttk.Label(
            self,
            text=("Zugangsdaten werden hier nie angezeigt. Die Tabelle zeigt nur, ob sie im Windows-Anmeldetresor hinterlegt sind. "
                  "Kostenfreie Kontingente sind Sicherheitsgrenzen und werden vor jedem Upload erneut geprüft."),
            wraplength=1120, padding=(12, 0, 12, 8),
        ).pack(fill="x")

        frame = ttk.Frame(self, padding=(12, 0, 12, 8)); frame.pack(fill="both", expand=True)
        cols = ("id", "name", "kind", "enabled", "credentials", "free", "used", "left", "priority", "routing", "status")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=13)
        spec = [
            ("id", "ID", 60), ("name", "Anbieter", 190), ("kind", "Art", 145), ("enabled", "Aktiv", 60),
            ("credentials", "Zugang", 90), ("free", "Kostenlos", 90), ("used", "Benutzt", 90),
            ("left", "Frei", 90), ("priority", "Prio", 55), ("routing", "Umschaltung", 150), ("status", "Status", 170),
        ]
        for key, title, width in spec:
            self.tree.heading(key, text=title); self.tree.column(key, width=width, anchor="w")
        y = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        x = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); y.grid(row=0, column=1, sticky="ns"); x.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)

        actions = ttk.Frame(self, padding=(12, 0, 12, 12)); actions.pack(fill="x")
        ttk.Button(actions, text="Anbieter konfigurieren", command=self.configure_selected).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Aktivieren / deaktivieren", command=self.toggle_selected).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Verbindung testen", command=self.test_selected).pack(side="left")
        ttk.Button(actions, text="Schließen", command=self.destroy).pack(side="right")
        self.info = ttk.Label(actions, text="B2 und R2 sind direkt routbar; OCI ist als Reserveplatz vorbereitet.")
        self.info.pack(side="right", padx=(0, 14))

    def _selected_id(self):
        sel = self.tree.selection()
        if not sel:
            return None
        vals = self.tree.item(sel[0], "values")
        return str(vals[0]) if vals else None

    def refresh(self, live=False):
        self.tree.delete(*self.tree.get_children())
        self.info.config(text="Speicherstände werden abgefragt …" if live else "Tabelle aktualisiert.")

        def work():
            rows = _rows(self.store, live=live)
            def done():
                for row in rows:
                    self.tree.insert("", "end", values=(
                        row.provider_id, row.name, row.kind, "JA" if row.enabled else "NEIN", row.credentials,
                        _fmt_gb(row.free_limit_gb), _fmt_gb_bytes(row.used_bytes), _fmt_gb_bytes(row.free_bytes),
                        row.priority, row.routing, row.status,
                    ))
                self.info.config(text="Live-Kapazitäten geprüft." if live else "Tabelle aktualisiert.")
            self.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def configure_selected(self):
        pid = self._selected_id()
        if not pid:
            messagebox.showinfo("Cloud-Anbieter", "Bitte zuerst einen Anbieter markieren.", parent=self); return
        if pid in {"B2", "R2"}:
            try:
                self.destroy(); self.app.open_settings(tab="storage")
            except Exception:
                messagebox.showinfo("Cloud-Anbieter", "Bitte Zahnrad → Dateispeicher öffnen.", parent=self)
            return
        OciConfigWindow(self, self.store, on_saved=lambda: self.refresh(live=True))

    def toggle_selected(self):
        pid = self._selected_id()
        if not pid:
            messagebox.showinfo("Cloud-Anbieter", "Bitte zuerst einen Anbieter markieren.", parent=self); return
        if pid == "B2":
            cfg = self.store.data.setdefault("b2", {})
        elif pid == "R2":
            cfg = self.store.data.setdefault("r2", {})
        else:
            cfg = self.store.data.setdefault("cloud_providers", {}).setdefault("OCI", {})
        cfg["enabled"] = not bool(cfg.get("enabled", False))
        self.store.save(); self.refresh(live=True)

    def test_selected(self):
        pid = self._selected_id()
        if not pid:
            messagebox.showinfo("Cloud-Anbieter", "Bitte zuerst einen Anbieter markieren.", parent=self); return
        if pid == "B2": cfg = self.store.get_b2_runtime_config()
        elif pid == "R2": cfg = get_r2_runtime_config(self.store) if get_r2_runtime_config else {}
        else: cfg = _oci_runtime(self.store)
        store = _store_for(cfg)
        if store is None:
            messagebox.showwarning("Cloud-Anbieter", f"{pid} ist noch nicht vollständig eingerichtet.", parent=self); return
        self.info.config(text=f"{pid} wird geprüft …")
        def work():
            ok, msg = store.test()
            self.after(0, lambda: (self.info.config(text=msg), (messagebox.showinfo if ok else messagebox.showerror)("Cloud-Anbieter", msg, parent=self)))
        threading.Thread(target=work, daemon=True).start()


class OciConfigWindow(tk.Toplevel):
    def __init__(self, parent, store: ConfigStore, on_saved=None):
        super().__init__(parent)
        self.store = store; self.on_saved = on_saved
        cfg = _oci_runtime(store)
        self.title("Oracle OCI Object Storage konfigurieren")
        self.geometry("760x470"); self.resizable(True, False)
        self.enabled = tk.BooleanVar(value=bool(cfg.get("enabled")))
        self.bucket = tk.StringVar(value=str(cfg.get("bucket") or ""))
        self.endpoint = tk.StringVar(value=str(cfg.get("endpoint_url") or ""))
        self.region = tk.StringVar(value=str(cfg.get("region") or ""))
        self.prefix = tk.StringVar(value=str(cfg.get("prefix") or "pc-backup-vault-oci"))
        self.access = tk.StringVar(value=str(cfg.get("access_key_id") or ""))
        self.secret = tk.StringVar(value=str(cfg.get("application_key") or ""))
        body = ttk.Frame(self, padding=14); body.pack(fill="both", expand=True)
        ttk.Checkbutton(body, text="Oracle OCI als Reserve-Anbieter aktivieren", variable=self.enabled).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0,8))
        fields = [("Bucket", self.bucket, False), ("S3-kompatibler Endpoint", self.endpoint, False), ("Region", self.region, False),
                  ("Prefix", self.prefix, False), ("Access Key ID", self.access, True), ("Secret Access Key", self.secret, True)]
        for i, (label, var, secret) in enumerate(fields, start=1):
            ttk.Label(body, text=label).grid(row=i, column=0, sticky="w", padx=(0,10), pady=5)
            ttk.Entry(body, textvariable=var, show="*" if secret else "", width=70).grid(row=i, column=1, sticky="ew", pady=5)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="Kostenloses Plan-Limit im Register: 20 GB. Der Null-Euro-Schutz verwendet zusätzlich eine Sicherheitsreserve.", wraplength=690).grid(row=7,column=0,columnspan=2,sticky="w",pady=(8,4))
        ttk.Label(body, text="Hinweis: OCI ist derzeit als konfigurierbare Reserve vorbereitet; die automatische Failback-Routingstufe wird erst nach erfolgreichem Adapter-TÜV freigeschaltet.", wraplength=690).grid(row=8,column=0,columnspan=2,sticky="w",pady=(4,10))
        ar = ttk.Frame(body); ar.grid(row=9,column=0,columnspan=2,sticky="ew")
        ttk.Button(ar,text="Speichern",command=self.save).pack(side="left")
        ttk.Button(ar,text="Abbrechen",command=self.destroy).pack(side="right")

    def save(self):
        meta = self.store.data.setdefault("cloud_providers", {}).setdefault("OCI", {})
        meta.update({
            "enabled": bool(self.enabled.get()), "name": "Oracle OCI Object Storage", "kind": "Backup / Failback",
            "bucket": self.bucket.get().strip(), "endpoint_url": self.endpoint.get().strip().rstrip("/"),
            "region": self.region.get().strip(), "prefix": self.prefix.get().strip().strip("/") or "pc-backup-vault-oci",
            "free_limit_gb": 20.0, "priority": 2,
        })
        if self.access.get().strip(): keyring.set_password(SERVICE, "oci_access_key_id", self.access.get().strip())
        if self.secret.get().strip(): keyring.set_password(SERVICE, "oci_secret_access_key", self.secret.get().strip())
        self.store.save()
        if self.on_saved: self.on_saved()
        messagebox.showinfo("Oracle OCI", "OCI-Konfiguration gespeichert. Zugangsschlüssel liegen nur im Windows-Anmeldetresor.", parent=self)
        self.destroy()


def enable_provider_registry(AppClass):
    """Add a compact registry entry point to the existing app without replacing UI modules."""
    if getattr(AppClass, "_provider_registry_enabled", False):
        return
    original_build = AppClass._build

    def wrapped_build(self, *args, **kwargs):
        result = original_build(self, *args, **kwargs)
        # Add a stable button in the existing top header if it can be found.
        try:
            top = next((w for w in self.winfo_children() if isinstance(w, ttk.Frame)), None)
            if top is not None:
                ttk.Button(top, text="☁ Cloud-Anbieter", command=lambda: ProviderRegistryWindow(self)).pack(side="right", padx=(0,6))
        except Exception:
            pass
        return result

    AppClass._build = wrapped_build
    AppClass.open_provider_registry = lambda self: ProviderRegistryWindow(self)
    AppClass._provider_registry_enabled = True
