from __future__ import annotations

from tkinter import messagebox

from database_profiles_v1929 import build_supabase_dsn


def looks_like_postgres_dsn(value: str) -> bool:
    text = str(value or "").strip()
    low = text.casefold()
    if low.startswith("postgresql://") or low.startswith("postgres://"):
        return True
    markers = ("host=", "dbname=", "database=", "user=")
    return sum(1 for marker in markers if marker in low) >= 2


def prepare_supabase_test(window) -> tuple[bool, str]:
    """Prepare the selected Supabase profile for the existing DB test.

    Returns (handled, mode). handled=False means this is not a Supabase profile.
    For Supabase the existing DSN field may contain either a complete PostgreSQL
    DSN or only the project database password. A password is converted into the
    canonical SSL DSN and persisted only in the Windows credential store.
    """
    profile = window.selected_profile()
    if not profile or str(profile.get("provider") or "").casefold() != "supabase":
        return False, "other-provider"

    pid = str(profile.get("id") or "")
    raw = str(window.vars["dsn"].get() or "").strip()
    stored = str(window.store.get_dsn(pid) or "").strip() if pid else ""

    if raw and not looks_like_postgres_dsn(raw):
        dsn = build_supabase_dsn(profile, raw)
        ref = str(profile.get("project_ref") or "").strip()
        host = str(profile.get("db_host") or profile.get("host_hint") or (f"db.{ref}.supabase.co" if ref else "")).strip()
        window.store.update_profile(pid, {
            "provider": "supabase",
            "database": str(profile.get("database") or "postgres").strip() or "postgres",
            "host_hint": host,
            "db_host": host,
            "enabled": True,
        })
        window.store.set_dsn(pid, dsn)
        window.vars["dsn"].set(dsn)
        return True, "password"

    if raw:
        return True, "dsn"

    if stored:
        window.vars["dsn"].set(stored)
        return True, "stored"

    return True, "missing"


def apply_database_profiles_runtime_fix_v1930(SettingsWindowClass):
    """Make the normal 'Verbindung testen' button work naturally for Supabase."""
    if getattr(SettingsWindowClass, "_database_profiles_runtime_v1930", False):
        return

    original_test_profile = SettingsWindowClass.test_profile

    def test_profile(self):
        profile = self.selected_profile()
        is_supabase = bool(profile and str(profile.get("provider") or "").casefold() == "supabase")
        if not is_supabase:
            return original_test_profile(self)

        try:
            label = getattr(self, "activity_label", None)
            if label is not None:
                label.config(text="Supabase-Verbindung wird vorbereitet …")
            self.update_idletasks()
        except Exception:
            pass

        try:
            _handled, mode = prepare_supabase_test(self)
        except Exception as exc:
            messagebox.showerror("PC Backup Vault", f"Supabase-Verbindung konnte nicht vorbereitet werden.\n\n{exc}", parent=self)
            return

        if mode == "missing":
            messagebox.showwarning(
                "PC Backup Vault",
                "Für dieses Supabase-Projekt fehlt das Datenbank-Passwort.\n\n"
                "Du kannst im Feld „Connection String / DSN“ einfach nur das Supabase-Datenbankpasswort eingeben "
                "und danach erneut „Verbindung testen“ klicken. PC Backup Vault baut die DSN automatisch und "
                "speichert sie ausschließlich im Windows-Anmeldetresor.",
                parent=self,
            )
            return

        return original_test_profile(self)

    SettingsWindowClass.test_profile = test_profile
    SettingsWindowClass._database_profiles_runtime_v1930 = True
