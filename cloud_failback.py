from __future__ import annotations

"""Zero-cost cloud guard and failback routing for PC Backup Vault.

This module is intentionally additive.  The established backup engine keeps its
NEON/B2 database schema, while the B2 object-store slot becomes a routed
S3-compatible object store.  New external object keys are tagged with ``b2::``
or ``r2::``; legacy untagged keys continue to resolve to Backblaze B2.

Safety rule: an external upload is never started when the conservative
preflight would cross the configured zero-cost ceiling.  An interactive run may
then offer the configured Cloudflare R2 fallback.  The fallback is subjected to
exactly the same preflight before any upload starts.  Unattended runs never
switch providers without confirmation.
"""

from dataclasses import dataclass
import threading
import weakref
from typing import Any

import keyring

import object_store
from object_store import ObjectStoreError
from config_store import ConfigStore, SERVICE

DECIMAL_GB = 1_000_000_000
DEFAULT_FREE_GB = 10.0
DEFAULT_SAFETY_GB = 0.5
DEFAULT_SAFE_GB = DEFAULT_FREE_GB - DEFAULT_SAFETY_GB
R2_CREDENTIAL_USER = "r2_access_key_id"
R2_CREDENTIAL_SECRET = "r2_secret_access_key"

_APP_REF: weakref.ReferenceType | None = None
_PATCHED = False
_ORIGINAL_GET_B2_RUNTIME = None
_ORIGINAL_BACKUP_FILES = None


@dataclass(frozen=True)
class CapacityDecision:
    provider: str
    used_bytes: int
    planned_bytes: int
    safe_limit_bytes: int
    free_before_bytes: int
    free_after_bytes: int
    allowed: bool
    reason: str


def _decimal_bytes(gb: float) -> int:
    return max(0, int(float(gb) * DECIMAL_GB))


def safe_limit_bytes(config: dict | None) -> int:
    cfg = dict(config or {})
    free_gb = max(0.1, float(cfg.get("free_limit_gb", DEFAULT_FREE_GB)))
    configured_hard = max(0.1, float(cfg.get("hard_limit_gb", DEFAULT_SAFE_GB)))
    # Never consume the advertised free tier to the last byte.  The fixed
    # reserve also covers decimal/binary unit differences and small provider
    # accounting delays.
    provider_safe = max(0.1, free_gb - DEFAULT_SAFETY_GB)
    return _decimal_bytes(min(configured_hard, provider_safe))


def conservative_planned_bytes(paths) -> int:
    """Upper-bound style estimate used before the real backup engine starts.

    The engine may later deduplicate/compress and therefore upload less.  The
    preflight deliberately errs on the safe side because its purpose is zero
    unexpected cost, not maximum cloud utilisation.
    """
    total = 0
    files = 0
    for path in list(paths or []):
        try:
            total += int(path.stat().st_size)
            files += 1
        except Exception:
            continue
    # AES-GCM/chunk metadata overhead is small.  Two percent plus 4 KiB/file is
    # intentionally conservative and still cheap to calculate.
    return int(total * 1.02) + files * 4096


def evaluate_capacity(provider: str, used_bytes: int, planned_bytes: int, config: dict | None) -> CapacityDecision:
    limit = safe_limit_bytes(config)
    used = max(0, int(used_bytes or 0))
    planned = max(0, int(planned_bytes or 0))
    before = max(0, limit - used)
    after = limit - used - planned
    allowed = after >= 0
    if allowed:
        reason = (
            f"{provider}: Kostenfrei-Grenze eingehalten – nach der Sicherung bleiben "
            f"ca. {after / DECIMAL_GB:.2f} GB Sicherheitsreserve im freigegebenen Kontingent."
        )
    else:
        over = abs(after)
        reason = (
            f"{provider}: Sicherung blockiert. Geplant sind ca. {planned / DECIMAL_GB:.2f} GB, "
            f"kostenfrei/sicher verfügbar sind nur {before / DECIMAL_GB:.2f} GB. "
            f"Die Null-Euro-Grenze würde um ca. {over / DECIMAL_GB:.2f} GB überschritten."
        )
    return CapacityDecision(provider, used, planned, limit, before, after, allowed, reason)


def _r2_meta(store: ConfigStore) -> dict:
    cfg = dict(store.data.get("r2") or {})
    cfg.setdefault("enabled", False)
    cfg.setdefault("bucket", "")
    cfg.setdefault("endpoint_url", "")
    cfg.setdefault("region", "auto")
    cfg.setdefault("prefix", "pc-backup-vault-r2")
    cfg.setdefault("free_limit_gb", DEFAULT_FREE_GB)
    cfg.setdefault("hard_limit_gb", DEFAULT_SAFE_GB)
    cfg.setdefault("soft_limit_gb", 8.0)
    cfg.setdefault("upload_workers", 4)
    return cfg


def get_r2_runtime_config(store: ConfigStore) -> dict:
    cfg = _r2_meta(store)
    access = keyring.get_password(SERVICE, R2_CREDENTIAL_USER) or ""
    secret = keyring.get_password(SERVICE, R2_CREDENTIAL_SECRET) or ""
    cfg["access_key_id"] = access
    cfg["application_key"] = secret
    cfg["configured"] = bool(
        cfg.get("enabled") and cfg.get("bucket") and cfg.get("endpoint_url") and access and secret
    )
    cfg["provider_code"] = "R2"
    cfg["provider_name"] = "Cloudflare R2"
    return cfg


def save_r2_config(store: ConfigStore, cfg: dict, access_key_id: str, secret_access_key: str) -> None:
    meta = dict(cfg or {})
    meta.pop("access_key_id", None)
    meta.pop("application_key", None)
    meta.pop("configured", None)
    meta.pop("provider_code", None)
    meta.pop("provider_name", None)
    meta["free_limit_gb"] = DEFAULT_FREE_GB
    # Zero-cost mode does not permit moving the hard limit into the provider's
    # billable range.
    meta["hard_limit_gb"] = min(DEFAULT_SAFE_GB, max(0.1, float(meta.get("hard_limit_gb", DEFAULT_SAFE_GB))))
    store.data["r2"] = meta
    if access_key_id.strip():
        keyring.set_password(SERVICE, R2_CREDENTIAL_USER, access_key_id.strip())
    if secret_access_key.strip():
        keyring.set_password(SERVICE, R2_CREDENTIAL_SECRET, secret_access_key.strip())
    store.save()


def clear_r2_credentials() -> None:
    for name in (R2_CREDENTIAL_USER, R2_CREDENTIAL_SECRET):
        try:
            keyring.delete_password(SERVICE, name)
        except Exception:
            pass


def _plain_store(cfg: dict | None):
    data = dict(cfg or {})
    if not data.get("configured"):
        return None
    return object_store.B2Store(
        bucket=str(data.get("bucket") or "").strip(),
        endpoint_url=str(data.get("endpoint_url") or "").strip(),
        region=str(data.get("region") or "").strip(),
        prefix=str(data.get("prefix") or "pc-backup-vault").strip(),
        access_key_id=str(data.get("access_key_id") or "").strip(),
        application_key=str(data.get("application_key") or "").strip(),
    )


class RoutingObjectStore:
    """Route legacy/new external object keys between B2 and R2."""

    def __init__(self, config: dict):
        cfg = dict(config or {})
        self.config = cfg
        self.active_provider_code = str(cfg.get("active_provider") or "B2").upper()
        self._stores = {
            "B2": _plain_store(cfg),
            "R2": _plain_store(cfg.get("fallback_r2") or {}),
        }
        if self.active_provider_code not in self._stores:
            self.active_provider_code = "B2"

    @property
    def active(self):
        return self._stores.get(self.active_provider_code)

    def has_provider(self, code: str) -> bool:
        return self._stores.get(str(code or "").upper()) is not None

    def provider_config(self, code: str) -> dict:
        return dict(self.config if str(code).upper() == "B2" else (self.config.get("fallback_r2") or {}))

    def provider_store(self, code: str):
        return self._stores.get(str(code or "").upper())

    def _route(self, key: str):
        raw = str(key or "")
        if raw.startswith("r2::"):
            return "R2", raw[4:]
        if raw.startswith("b2::"):
            return "B2", raw[4:]
        # Legacy PC Backup Vault objects were stored without a route marker.
        return "B2", raw

    def object_key(self, sha256: str, chunk_no: int) -> str:
        store = self.active
        if store is None:
            raise ObjectStoreError(f"{self.active_provider_code} ist nicht vollständig eingerichtet.")
        physical = store.object_key(sha256, chunk_no)
        return f"{self.active_provider_code.lower()}::{physical}"

    def ping(self):
        if self.active is None:
            return False, f"{self.active_provider_code} ist nicht vollständig eingerichtet."
        return self.active.ping()

    def test(self):
        if self.active is None:
            return False, f"{self.active_provider_code} ist nicht vollständig eingerichtet."
        return self.active.test()

    def put(self, key: str, data: bytes, cipher_sha256: str) -> str:
        code, physical = self._route(key)
        store = self._stores.get(code)
        if store is None:
            raise ObjectStoreError(f"{code}-Zugang fehlt; Objekt kann nicht geschrieben werden.")
        return store.put(physical, data, cipher_sha256)

    def get(self, key: str) -> bytes:
        code, physical = self._route(key)
        store = self._stores.get(code)
        if store is None:
            raise ObjectStoreError(f"{code}-Zugang fehlt; Objekt kann nicht gelesen werden.")
        return store.get(physical)

    def head(self, key: str) -> dict:
        code, physical = self._route(key)
        store = self._stores.get(code)
        if store is None:
            raise ObjectStoreError(f"{code}-Zugang fehlt; Objekt kann nicht geprüft werden.")
        return store.head(physical)

    def delete(self, key: str):
        code, physical = self._route(key)
        store = self._stores.get(code)
        if store is None:
            raise ObjectStoreError(f"{code}-Zugang fehlt; Objekt kann nicht gelöscht werden.")
        return store.delete(physical)

    def list_prefix_sizes(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for code, store in self._stores.items():
            if store is None:
                continue
            for physical, size in store.list_prefix_sizes().items():
                out[f"{code.lower()}::{physical}"] = int(size)
                if code == "B2":
                    # Required for verification/restores of pre-routing backups.
                    out.setdefault(physical, int(size))
        return out

    def provider_usage_bytes(self, code: str) -> int:
        store = self.provider_store(code)
        if store is None:
            raise ObjectStoreError(f"{code} ist nicht vollständig eingerichtet.")
        return sum(int(v or 0) for v in store.list_prefix_sizes().values())


def make_routing_store(config: dict | None):
    cfg = dict(config or {})
    if not cfg.get("configured") and not (cfg.get("fallback_r2") or {}).get("configured"):
        return None
    router = RoutingObjectStore(cfg)
    if router.active is None:
        return None
    return router


def _combined_runtime_config(store: ConfigStore, active_provider: str = "B2") -> dict:
    primary = dict(_ORIGINAL_GET_B2_RUNTIME(store))
    primary["fallback_r2"] = get_r2_runtime_config(store)
    primary["active_provider"] = str(active_provider or "B2").upper()
    primary["zero_cost_mode"] = True
    # The legacy engine's B2 hard-limit is based on all external DB rows and
    # cannot distinguish B2 from R2.  The authoritative per-provider remote
    # preflight below replaces that legacy aggregate check.  Set a high internal
    # ceiling only after the zero-cost preflight has passed.
    primary["legacy_aggregate_hard_limit_gb"] = primary.get("hard_limit_gb", 10)
    return primary


def _provider_cfg(combined: dict, code: str) -> dict:
    return dict(combined if code == "B2" else (combined.get("fallback_r2") or {}))


def _format_gb(value: int) -> str:
    return f"{max(0, int(value or 0)) / DECIMAL_GB:.2f} GB"


def _preflight(combined: dict, provider: str, paths) -> CapacityDecision:
    cfg = _provider_cfg(combined, provider)
    if not cfg.get("configured"):
        return CapacityDecision(provider, 0, conservative_planned_bytes(paths), safe_limit_bytes(cfg), 0, -1, False,
                                f"{provider} ist nicht vollständig eingerichtet.")
    routed = RoutingObjectStore({**combined, "active_provider": provider})
    used = routed.provider_usage_bytes(provider)
    planned = conservative_planned_bytes(paths)
    name = "Backblaze B2" if provider == "B2" else "Cloudflare R2"
    return evaluate_capacity(name, used, planned, cfg)


def _ask_user(title: str, message: str) -> bool:
    app = _APP_REF() if _APP_REF else None
    if app is None:
        return False
    event = threading.Event()
    answer = {"value": False}

    def ask():
        try:
            from tkinter import messagebox
            answer["value"] = bool(messagebox.askyesno(title, message, parent=app))
        finally:
            event.set()

    try:
        app.after(0, ask)
    except Exception:
        return False
    event.wait()
    return bool(answer["value"])


def _show_info(title: str, message: str):
    app = _APP_REF() if _APP_REF else None
    if app is None:
        return
    def show():
        try:
            from tkinter import messagebox
            messagebox.showinfo(title, message, parent=app)
        except Exception:
            pass
    try:
        app.after(0, show)
    except Exception:
        pass


def _protected_backup_files(*args, **kwargs):
    """Drop-in wrapper around backup_engine.backup_files.

    For external payloads this performs the mandatory zero-cost preflight.  If
    B2 is too full, an interactive backup can explicitly switch to R2.  The R2
    preflight is then run from scratch before the original engine is called.
    """
    payload = str(kwargs.get("payload_target") or "AUTO").upper()
    combined = dict(kwargs.get("object_store_config") or {})
    paths = kwargs.get("paths")
    if paths is None and len(args) >= 5:
        paths = args[4]
    paths = list(paths or [])

    # AUTO uses B2 whenever it is configured in the established engine.
    external = payload == "B2" or (payload == "AUTO" and combined.get("configured"))
    if not external:
        return _ORIGINAL_BACKUP_FILES(*args, **kwargs)

    b2 = _preflight(combined, "B2", paths)
    if b2.allowed:
        run_cfg = dict(combined)
        run_cfg["active_provider"] = "B2"
        # Aggregate legacy limit is not provider-aware; remote preflight above
        # is.  Prevent the old combined counter from falsely blocking R2/B2.
        run_cfg["hard_limit_gb"] = 100000
        kwargs["object_store_config"] = run_cfg
        result = _ORIGINAL_BACKUP_FILES(*args, **kwargs)
        if isinstance(result, dict):
            result["cloud_provider"] = "B2"
            result["zero_cost_preflight"] = True
        return result

    r2_cfg = _provider_cfg(combined, "R2")
    fallback_ready = bool(r2_cfg.get("configured"))
    if not fallback_ready:
        from backup_engine import LimitBlocked
        raise LimitBlocked(
            b2.reason + "\n\nEs wurden keine Cloud-Daten übertragen. "
            "Cloudflare R2 ist als kostenloser Ersatz noch nicht vollständig eingerichtet."
        )

    prompt = (
        "BACKBLAZE B2 – KOSTENSCHUTZ\n\n"
        f"Belegt: {_format_gb(b2.used_bytes)}\n"
        f"Geplante Sicherung (Sicherheitswert): {_format_gb(b2.planned_bytes)}\n"
        f"Sicheres Restkontingent: {_format_gb(b2.free_before_bytes)}\n\n"
        "Mit Backblaze würde die eingestellte Null-Euro-Grenze überschritten. "
        "Es wurde noch nichts hochgeladen.\n\n"
        "Cloudflare R2 ist als Ersatz eingerichtet. Soll R2 jetzt verwendet werden?\n\n"
        "Wichtig: Vor dem Upload wird R2 vollständig neu auf Verbindung, belegten Speicher, "
        "kostenfreies Limit und Größe dieser Sicherung geprüft."
    )
    if not _ask_user("Kostenfreier Ersatzspeicher verfügbar", prompt):
        from backup_engine import LimitBlocked
        raise LimitBlocked(b2.reason + "\n\nDer Benutzer hat den Wechsel zum Ersatzspeicher nicht freigegeben.")

    r2 = _preflight(combined, "R2", paths)
    if not r2.allowed:
        from backup_engine import LimitBlocked
        raise LimitBlocked(
            "Auch der Ersatzspeicher wurde aus Kostenschutzgründen blockiert.\n\n"
            + r2.reason
            + "\n\nEs wurden keine Cloud-Daten übertragen. Bitte lokales/NAS-Ziel verwenden oder Speicher freigeben."
        )

    _show_info(
        "Failback freigegeben",
        "Cloudflare R2 hat die zweite Sicherheitsprüfung bestanden.\n\n"
        f"Belegt: {_format_gb(r2.used_bytes)}\n"
        f"Geplant: {_format_gb(r2.planned_bytes)}\n"
        f"Sicher verbleibend: {_format_gb(max(0, r2.free_after_bytes))}\n\n"
        "Die Sicherung startet jetzt auf dem Ersatzspeicher."
    )
    run_cfg = dict(combined)
    run_cfg["active_provider"] = "R2"
    run_cfg["hard_limit_gb"] = 100000
    kwargs["object_store_config"] = run_cfg
    # Keep payload_target=B2 because the current DB schema names its external
    # object-store slot B2.  Routed object keys preserve the real provider.
    kwargs["payload_target"] = "B2"
    result = _ORIGINAL_BACKUP_FILES(*args, **kwargs)
    if isinstance(result, dict):
        result["cloud_provider"] = "R2"
        result["zero_cost_preflight"] = True
        result["failback_from"] = "B2"
    return result


def _open_r2_setup(app):
    import tkinter as tk
    from tkinter import ttk, messagebox

    cfg = _r2_meta(app.store)
    runtime = get_r2_runtime_config(app.store)
    win = tk.Toplevel(app)
    win.title("Cloud-Failback – Cloudflare R2")
    win.geometry("780x560")
    win.minsize(700, 520)
    win.transient(app)

    body = ttk.Frame(win, padding=14)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Cloud-Failback / Null-Euro-Schutz", font=("Segoe UI", 17, "bold")).pack(anchor="w")
    ttk.Label(
        body,
        text=(
            "Backblaze B2 bleibt Haupt-Cloud. Wenn die sichere kostenlose Grenze nicht reicht, "
            "kann PC Backup Vault nach Bestätigung auf Cloudflare R2 ausweichen. R2 wird vor jedem "
            "Failback erneut geprüft. Es erfolgt niemals automatisch ein kostenpflichtiger Upload."
        ),
        wraplength=730,
    ).pack(anchor="w", pady=(4, 12))

    enabled = tk.BooleanVar(value=bool(cfg.get("enabled")))
    bucket = tk.StringVar(value=str(cfg.get("bucket") or ""))
    endpoint = tk.StringVar(value=str(cfg.get("endpoint_url") or ""))
    region = tk.StringVar(value=str(cfg.get("region") or "auto"))
    prefix = tk.StringVar(value=str(cfg.get("prefix") or "pc-backup-vault-r2"))
    access = tk.StringVar(value=str(runtime.get("access_key_id") or ""))
    secret = tk.StringVar(value=str(runtime.get("application_key") or ""))

    frm = ttk.LabelFrame(body, text="Cloudflare R2 – Ersatzspeicher", padding=10)
    frm.pack(fill="x")
    ttk.Checkbutton(frm, text="R2 als kostenfreien Failback-Ersatz aktivieren", variable=enabled).grid(row=0, column=0, columnspan=2, sticky="w", pady=4)
    fields = [
        ("Bucket", bucket, False),
        ("S3 Endpoint", endpoint, False),
        ("Region", region, False),
        ("Ordner/Prefix", prefix, False),
        ("Access Key ID", access, True),
        ("Secret Access Key", secret, True),
    ]
    for row, (label, var, secret_field) in enumerate(fields, start=1):
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(frm, textvariable=var, show="*" if secret_field else "", width=70).grid(row=row, column=1, sticky="ew", pady=4)
    frm.columnconfigure(1, weight=1)

    safety = ttk.LabelFrame(body, text="Fest eingestellter Kostenschutz", padding=10)
    safety.pack(fill="x", pady=(10, 0))
    ttk.Label(safety, text="R2 Free Tier (Standard Storage): 10,0 GB-Monat").pack(anchor="w")
    ttk.Label(safety, text="PC Backup Vault Hardlimit: 9,5 GB (0,5 GB Sicherheitsreserve)").pack(anchor="w", pady=(2, 0))
    ttk.Label(safety, text="Kostenpflichtiges Überschreiten: GESPERRT – keine automatische Freigabe", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(2, 0))

    status = ttk.Label(body, text="R2-Status: eingerichtet" if runtime.get("configured") else "R2-Status: noch nicht eingerichtet")
    status.pack(anchor="w", pady=(10, 4))

    buttons = ttk.Frame(body)
    buttons.pack(fill="x", pady=(8, 0))

    def form_cfg():
        data = {
            "enabled": bool(enabled.get()),
            "bucket": bucket.get().strip(),
            "endpoint_url": endpoint.get().strip().rstrip("/"),
            "region": region.get().strip() or "auto",
            "prefix": prefix.get().strip().strip("/") or "pc-backup-vault-r2",
            "free_limit_gb": DEFAULT_FREE_GB,
            "soft_limit_gb": 8.0,
            "hard_limit_gb": DEFAULT_SAFE_GB,
            "upload_workers": 4,
        }
        if data["enabled"] and (not data["bucket"] or not data["endpoint_url"] or not access.get().strip() or not secret.get().strip()):
            raise ValueError("Für aktiviertes R2 müssen Bucket, S3 Endpoint, Access Key ID und Secret Access Key ausgefüllt sein.")
        return data

    def save():
        try:
            data = form_cfg()
            save_r2_config(app.store, data, access.get(), secret.get())
            status.config(text="R2-Status: eingerichtet" if get_r2_runtime_config(app.store).get("configured") else "R2-Status: deaktiviert/unvollständig")
            messagebox.showinfo("Cloud-Failback", "R2-Failback-Einstellungen wurden gespeichert. Zugangsdaten liegen nur im Windows-Anmeldetresor.", parent=win)
        except Exception as exc:
            messagebox.showerror("Cloud-Failback", str(exc), parent=win)

    def test():
        try:
            data = form_cfg()
            temp = dict(data)
            temp["access_key_id"] = access.get().strip()
            temp["application_key"] = secret.get().strip()
            temp["configured"] = bool(data["enabled"] and data["bucket"] and data["endpoint_url"] and temp["access_key_id"] and temp["application_key"])
            combined = dict(_ORIGINAL_GET_B2_RUNTIME(app.store))
            combined["fallback_r2"] = temp
            combined["active_provider"] = "R2"
            router = RoutingObjectStore(combined)
            ok, msg = router.test()
            if not ok:
                raise RuntimeError(msg)
            used = router.provider_usage_bytes("R2")
            decision = evaluate_capacity("Cloudflare R2", used, 0, temp)
            status.config(text=f"R2-Status: OK · belegt {_format_gb(used)} · sicher frei {_format_gb(decision.free_before_bytes)}")
            messagebox.showinfo("Cloud-Failback", msg + "\n\n" + decision.reason, parent=win)
        except Exception as exc:
            status.config(text="R2-Status: FEHLER")
            messagebox.showerror("Cloud-Failback", str(exc), parent=win)

    def clear():
        if not messagebox.askyesno("Cloud-Failback", "R2-Zugangsdaten aus dem Windows-Anmeldetresor löschen?", parent=win):
            return
        clear_r2_credentials()
        access.set("")
        secret.set("")
        status.config(text="R2-Status: Zugangsdaten gelöscht")

    ttk.Button(buttons, text="Speichern", command=save).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="R2 vollständig testen", command=test).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Zugangsdaten löschen", command=clear).pack(side="left")
    ttk.Button(buttons, text="Schließen", command=win.destroy).pack(side="right")


def _open_cloud_status(app):
    import threading as _threading
    import tkinter as tk
    from tkinter import ttk

    win = tk.Toplevel(app)
    win.title("Cloud-Kostenschutz – Status")
    win.geometry("720x430")
    body = ttk.Frame(win, padding=14)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Cloud-Kostenschutz", font=("Segoe UI", 17, "bold")).pack(anchor="w")
    text = tk.Text(body, height=16, wrap="word")
    text.pack(fill="both", expand=True, pady=(10, 8))
    text.insert("1.0", "Speicher werden geprüft …")
    text.config(state="disabled")
    ttk.Button(body, text="Schließen", command=win.destroy).pack(anchor="e")

    def work():
        combined = _combined_runtime_config(app.store)
        lines = ["NULL-EURO-MODUS: AKTIV", "Kostenpflichtige Cloud-Uploads werden vor dem Start blockiert.", ""]
        for code, name in (("B2", "Backblaze B2"), ("R2", "Cloudflare R2 (Failback)")):
            cfg = _provider_cfg(combined, code)
            if not cfg.get("configured"):
                lines.append(f"{name}: nicht vollständig eingerichtet")
                continue
            try:
                router = RoutingObjectStore({**combined, "active_provider": code})
                used = router.provider_usage_bytes(code)
                decision = evaluate_capacity(name, used, 0, cfg)
                lines.append(f"{name}: OK")
                lines.append(f"  Belegt: {_format_gb(used)}")
                lines.append(f"  Sichere Null-Euro-Grenze: {_format_gb(decision.safe_limit_bytes)}")
                lines.append(f"  Sicher frei: {_format_gb(decision.free_before_bytes)}")
            except Exception as exc:
                lines.append(f"{name}: FEHLER – {exc}")
            lines.append("")
        def done():
            if not win.winfo_exists():
                return
            text.config(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", "\n".join(lines))
            text.config(state="disabled")
        app.after(0, done)
    _threading.Thread(target=work, daemon=True).start()


def _install_menu(app):
    import tkinter as tk
    try:
        menu = app.nametowidget(app.cget("menu")) if app.cget("menu") else None
    except Exception:
        menu = None
    if menu is None:
        menu = tk.Menu(app)
        app.config(menu=menu)
    cloud = tk.Menu(menu, tearoff=False)
    cloud.add_command(label="Cloud-Kostenschutz Status", command=lambda: _open_cloud_status(app))
    cloud.add_command(label="Cloudflare R2 Ersatzspeicher einrichten", command=lambda: _open_r2_setup(app))
    menu.add_cascade(label="Cloud-Schutz", menu=cloud)


def enable_cloud_failback(App) -> None:
    """Install the additive failback layer before the first App instance."""
    global _PATCHED, _ORIGINAL_GET_B2_RUNTIME, _ORIGINAL_BACKUP_FILES
    if _PATCHED:
        return
    _PATCHED = True

    import backup_engine
    import ui
    import verification
    try:
        import plan_runner
    except Exception:
        plan_runner = None

    _ORIGINAL_GET_B2_RUNTIME = ConfigStore.get_b2_runtime_config
    _ORIGINAL_BACKUP_FILES = backup_engine.backup_files

    def patched_get_b2_runtime(self):
        return _combined_runtime_config(self, "B2")

    ConfigStore.get_b2_runtime_config = patched_get_b2_runtime

    # Route every existing external-object-store consumer through the same
    # provider-aware resolver.  This keeps restore and verification compatible
    # with both legacy B2 keys and new b2:: / r2:: keys.
    object_store.make_b2_store = make_routing_store
    backup_engine.make_b2_store = make_routing_store
    verification.make_b2_store = make_routing_store
    ui.make_b2_store = make_routing_store
    for module_name in ("tuev", "dashboard_window", "history_window", "reporting"):
        try:
            module = __import__(module_name)
            if hasattr(module, "make_b2_store"):
                setattr(module, "make_b2_store", make_routing_store)
        except Exception:
            pass

    backup_engine.backup_files = _protected_backup_files
    ui.backup_files = _protected_backup_files
    if plan_runner is not None and hasattr(plan_runner, "backup_files"):
        plan_runner.backup_files = _protected_backup_files

    original_init = App.__init__

    def init_with_failback(self, *args, **kwargs):
        global _APP_REF
        original_init(self, *args, **kwargs)
        _APP_REF = weakref.ref(self)
        self.store.data.setdefault("r2", _r2_meta(self.store))
        self.store.save()
        _install_menu(self)

    App.__init__ = init_with_failback
