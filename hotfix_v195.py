from __future__ import annotations

import json
import threading
import urllib.error
from tkinter import messagebox, ttk

import auto_updater


def release_from_payload(current_version: str, release: dict):
    """Parse one GitHub latest-release response without hiding connectivity errors."""
    if release.get("draft") or release.get("prerelease"):
        return None
    tag = str(release.get("tag_name") or "").strip()
    candidate = tag[1:] if tag.lower().startswith("v") else tag
    try:
        if not auto_updater.is_newer_version(current_version, candidate):
            return None
    except ValueError:
        return None

    setup_name = f"PC_Backup_Vault_{candidate}_Setup.exe"
    sha_name = setup_name + ".sha256"
    assets = {str(a.get("name") or ""): a for a in release.get("assets", [])}
    setup = assets.get(setup_name)
    checksum = assets.get(sha_name)
    if not setup or not checksum:
        return None
    setup_url = str(setup.get("browser_download_url") or "")
    sha_url = str(checksum.get("browser_download_url") or "")
    if not setup_url.startswith("https://github.com/") or not sha_url.startswith("https://github.com/"):
        return None
    return auto_updater.ReleaseInfo(
        version=candidate,
        tag=tag,
        setup_name=setup_name,
        setup_url=setup_url,
        setup_size=int(setup.get("size") or 0),
        sha256_name=sha_name,
        sha256_url=sha_url,
        release_url=str(release.get("html_url") or ""),
        notes=str(release.get("body") or ""),
    )


def fetch_latest_release_strict(current_version: str):
    """Like the production updater check, but distinguish 'no update' from connection failure."""
    try:
        payload = auto_updater._get_json(auto_updater.LATEST_RELEASE_URL)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Update-Server konnte nicht erreicht werden: {exc}") from exc
    return release_from_payload(current_version, payload)


def configure_primary_backup_entry(app, workbench_class):
    """Route the established primary Backup button into the 1.9.4 workbench."""
    button = getattr(app, "btn_backup", None)
    if button is None:
        return False
    button.configure(text="⇄ Sichern & Wiederherstellen", command=lambda: workbench_class(app))
    # v1.9.4 added a second workbench button. Remove only that duplicate UI control;
    # no backup/restore functionality is removed.
    try:
        parent = button.master
        for child in list(parent.winfo_children()):
            if child is button or not isinstance(child, ttk.Button):
                continue
            try:
                if str(child.cget("text")) == "⇄ Sichern & Wiederherstellen":
                    child.destroy()
            except Exception:
                pass
    except Exception:
        pass
    return True


def apply_hotfix_v195(AppClass, workbench_class, current_version: str):
    if getattr(AppClass, "_hotfix_v195", False):
        return
    original_build = AppClass._build

    def _build(self):
        original_build(self)
        configure_primary_backup_entry(self, workbench_class)

    def check_for_updates(self, *, manual: bool = False):
        if getattr(self, "_update_check_running", False):
            return
        self._update_check_running = True
        if manual:
            try:
                self._write_start_protocol("UPDATE_CHECK", "Manuelle Update-Prüfung")
            except Exception:
                pass

        def worker():
            try:
                info = fetch_latest_release_strict(current_version)
                error = None
            except Exception as exc:
                info = None
                error = str(exc)

            def finish():
                self._update_check_running = False
                if error:
                    if manual:
                        messagebox.showerror(
                            "PC Backup Vault – Update",
                            "Die Update-Prüfung konnte nicht abgeschlossen werden.\n\n"
                            + error
                            + "\n\nEs wurde nicht behauptet, dass die installierte Version aktuell ist.",
                            parent=self,
                        )
                    return
                if info:
                    self._show_update_window(info)
                elif manual:
                    messagebox.showinfo(
                        "PC Backup Vault – Update",
                        f"Version {current_version} ist aktuell.",
                        parent=self,
                    )
            self.after(0, finish)

        threading.Thread(target=worker, name="pbv-update-check-v195", daemon=True).start()

    AppClass._build = _build
    AppClass.check_for_updates = check_for_updates
    AppClass._hotfix_v195 = True
