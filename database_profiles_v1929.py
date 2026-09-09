from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

SUPABASE_PROJECTS = (
    {
        "name": "Supabase Hauptprojekt",
        "project_ref": "ptblnpiroqftcvlsrhac",
        "region": "eu-west-2",
        "host": "db.ptblnpiroqftcvlsrhac.supabase.co",
        "database": "postgres",
    },
    {
        "name": "Supabase Future Academy",
        "project_ref": "iddudrxuihdodnvejxcp",
        "region": "eu-central-1",
        "host": "db.iddudrxuihdodnvejxcp.supabase.co",
        "database": "postgres",
    },
)


def _profile_by_ref(store, project_ref: str):
    ref = str(project_ref or "").strip()
    return next((p for p in store.data.get("profiles", []) if str(p.get("project_ref") or "").strip() == ref), None)


def ensure_supabase_profiles(store) -> list[dict]:
    """Create/update the known Supabase projects without storing any secret."""
    touched: list[dict] = []
    changed = False
    for meta in SUPABASE_PROJECTS:
        profile = _profile_by_ref(store, meta["project_ref"])
        if profile is None:
            profile = {
                "name": meta["name"],
                "provider": "supabase",
                "host_hint": meta["host"],
                "db_host": meta["host"],
                "region": meta["region"],
                "database": meta["database"],
                "project_ref": meta["project_ref"],
                "soft_limit_mb": 350,
                "hard_limit_mb": 420,
                "enabled": True,
            }
            pid = store.add_profile(profile)
            profile = store.get_profile(pid)
            changed = True
        else:
            updates = {}
            if str(profile.get("provider") or "").lower() != "supabase":
                updates["provider"] = "supabase"
            if not str(profile.get("database") or "").strip():
                updates["database"] = meta["database"]
            if not str(profile.get("host_hint") or "").strip():
                updates["host_hint"] = meta["host"]
            if not str(profile.get("db_host") or "").strip():
                updates["db_host"] = meta["host"]
            if not str(profile.get("region") or "").strip():
                updates["region"] = meta["region"]
            if profile.get("enabled", True) is False:
                updates["enabled"] = True
            if updates:
                profile.update(updates)
                changed = True
        touched.append(profile)
    if changed:
        store.save()
    return touched


def build_supabase_dsn(profile: dict, password: str) -> str:
    ref = str(profile.get("project_ref") or "").strip()
    host = str(profile.get("db_host") or profile.get("host_hint") or "").strip()
    if not host and ref:
        host = f"db.{ref}.supabase.co"
    database = str(profile.get("database") or "postgres").strip() or "postgres"
    if not ref:
        raise ValueError("Supabase Project-Ref fehlt.")
    if not host:
        raise ValueError("Supabase Datenbank-Host fehlt.")
    if not str(password or ""):
        raise ValueError("Supabase Datenbank-Passwort fehlt.")
    def q(value: str) -> str:
        text = str(value).replace("\\", "\\\\").replace("'", "\\'")
        return "'" + text + "'"
    return (
        f"host={q(host)} port=5432 dbname={q(database)} user=postgres "
        f"password={q(str(password))} sslmode=require connect_timeout=10"
    )


def _provider_label(profile: dict) -> str:
    provider = str(profile.get("provider") or "postgresql").lower()
    return {"neon": "Neon", "supabase": "Supabase", "postgresql": "PostgreSQL"}.get(provider, provider or "Datenbank")


def _select_profile_id(window, pid: str):
    profiles = list(window.store.data.get("profiles") or [])
    idx = next((i for i, p in enumerate(profiles) if str(p.get("id")) == str(pid)), None)
    if idx is None:
        return
    try:
        window.lst.selection_clear(0, "end")
        window.lst.selection_set(idx)
        window.lst.see(idx)
        window.load_selected_profile()
    except Exception:
        pass


def _decorate_profile_list(window):
    profiles = list(window.store.data.get("profiles") or [])
    if not profiles:
        return
    try:
        selected = window.lst.curselection()
        selected_idx = selected[0] if selected else None
        window.lst.delete(0, "end")
        for p in profiles:
            ready = bool(window.store.get_dsn(str(p.get("id") or "")))
            star = "★ " if p.get("id") == window.store.data.get("active_profile_id") else ""
            state = "✓ verbunden" if ready else "⚠ Zugang fehlt"
            window.lst.insert("end", f"{star}{_provider_label(p)} · {p.get('name','')} · {state}")
        if selected_idx is not None and 0 <= selected_idx < len(profiles):
            window.lst.selection_set(selected_idx)
    except Exception:
        pass


def _update_supabase_status(window):
    label = getattr(window, "supabase_status_v1929", None)
    if label is None:
        return
    p = window.selected_profile()
    if not p:
        label.configure(text="Kein Datenbank-Ziel ausgewählt.")
        return
    provider = str(p.get("provider") or "").lower()
    if provider != "supabase":
        label.configure(text=f"{_provider_label(p)}-Ziel ausgewählt.")
        return
    ref = str(p.get("project_ref") or "–")
    host = str(p.get("db_host") or p.get("host_hint") or (f"db.{ref}.supabase.co" if ref != "–" else "–"))
    region = str(p.get("region") or "–")
    ready = "vorhanden" if window.store.get_dsn(str(p.get("id") or "")) else "FEHLT"
    label.configure(text=f"Supabase · Ref: {ref} · Region: {region} · Host: {host} · DB-Zugang im Windows-Tresor: {ready}")


def _configure_supabase_password(window):
    p = window.selected_profile()
    if not p or str(p.get("provider") or "").lower() != "supabase":
        messagebox.showwarning("PC Backup Vault", "Bitte zuerst ein Supabase-Datenbankziel auswählen.", parent=window)
        return
    password = simpledialog.askstring(
        "Supabase Datenbank-Passwort",
        "Datenbank-Passwort des ausgewählten Supabase-Projekts eingeben.\n\n"
        "Es wird ausschließlich im Windows-Anmeldetresor gespeichert.",
        show="*",
        parent=window,
    )
    if password is None:
        return
    try:
        dsn = build_supabase_dsn(p, password)
        ref = str(p.get("project_ref") or "").strip()
        host = str(p.get("db_host") or p.get("host_hint") or f"db.{ref}.supabase.co").strip()
        window.store.update_profile(p["id"], {
            "provider": "supabase",
            "database": str(p.get("database") or "postgres").strip() or "postgres",
            "host_hint": host,
            "db_host": host,
            "enabled": True,
        })
        window.store.set_dsn(p["id"], dsn)
        window.vars["dsn"].set(dsn)
        window.load_profiles()
        _select_profile_id(window, p["id"])
        _decorate_profile_list(window)
        _update_supabase_status(window)
        window.test_profile()
    except Exception as exc:
        messagebox.showerror("PC Backup Vault", str(exc), parent=window)


def _refresh_supabase_profiles(window):
    current = window.selected_profile()
    current_id = current.get("id") if current else None
    ensure_supabase_profiles(window.store)
    window.load_profiles()
    if current_id:
        _select_profile_id(window, current_id)
    _decorate_profile_list(window)
    _update_supabase_status(window)
    messagebox.showinfo(
        "PC Backup Vault",
        "Supabase-Projektstammdaten wurden abgeglichen.\n\n"
        "Projektname, Project-Ref, Region, Host und Datenbank sind vorbereitet. "
        "Geheime Datenbank-Passwörter werden absichtlich nicht aus Supabase übernommen.",
        parent=window,
    )


def _open_selected_in_storage(window, StorageCenterWindowClass):
    p = window.selected_profile()
    if not p:
        return
    explorer = StorageCenterWindowClass(window.app)
    pid = str(p.get("id") or "")
    for idx, target in enumerate(explorer.targets):
        if target.get("kind") == "POSTGRES" and str(target.get("profile_id") or "") == pid:
            explorer.target_combo.current(idx)
            explorer.switch_target()
            return


def apply_database_profiles_v1929(AppClass, SettingsWindowClass, StorageCenterWindowClass):
    """Seed Supabase DB profiles and add a clean quick-start manager to Settings."""
    if getattr(SettingsWindowClass, "_database_profiles_v1929", False):
        return

    original_app_init = AppClass.__init__
    def app_init(self, *args, **kwargs):
        original_app_init(self, *args, **kwargs)
        ensure_supabase_profiles(self.store)
    AppClass.__init__ = app_init

    original_settings_init = SettingsWindowClass.__init__
    def settings_init(self, app, *args, **kwargs):
        ensure_supabase_profiles(app.store)
        original_settings_init(self, app, *args, **kwargs)
        _decorate_profile_list(self)
        _update_supabase_status(self)
    SettingsWindowClass.__init__ = settings_init

    original_build_db = SettingsWindowClass._build_db
    def build_db(self):
        original_build_db(self)
        try:
            right = self.dbtab.winfo_children()[1]
        except Exception:
            right = self.dbtab
        box = ttk.LabelFrame(right, text="Supabase Schnellstart / Datenbankverwaltung", padding=10)
        box.pack(fill="x", pady=(8, 0))
        self.supabase_status_v1929 = ttk.Label(box, text="Supabase-Projekte werden vorbereitet …", wraplength=760)
        self.supabase_status_v1929.pack(anchor="w", pady=(0, 8))
        row = ttk.Frame(box); row.pack(fill="x")
        ttk.Button(row, text="↻ Supabase-Projekte abgleichen", command=lambda: _refresh_supabase_profiles(self)).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="🔑 DB-Passwort setzen & testen", command=lambda: _configure_supabase_password(self)).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="🗂 Im Speicher-Explorer öffnen", command=lambda: _open_selected_in_storage(self, StorageCenterWindowClass)).pack(side="left")
        ttk.Label(
            box,
            text="Vorbelegt werden ausschließlich nicht-geheime Projektdaten. Das Datenbank-Passwort bleibt ausschließlich im Windows-Anmeldetresor.",
            foreground="#475569",
            wraplength=760,
        ).pack(anchor="w", pady=(8, 0))
    SettingsWindowClass._build_db = build_db

    original_load_profiles = SettingsWindowClass.load_profiles
    def load_profiles(self):
        original_load_profiles(self)
        _decorate_profile_list(self)
        _update_supabase_status(self)
    SettingsWindowClass.load_profiles = load_profiles

    original_load_selected = SettingsWindowClass.load_selected_profile
    def load_selected_profile(self):
        original_load_selected(self)
        _update_supabase_status(self)
    SettingsWindowClass.load_selected_profile = load_selected_profile

    SettingsWindowClass._database_profiles_v1929 = True
