from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from database_profiles_v1929 import apply_database_profiles_v1929


CORE_BACKUP_BUTTONS = {
    "＋ Dateien", "+ Dateien", "＋ Ordner", "+ Ordner", "Auswahl leeren",
    "▶ Backup starten", "⚡ One-Touch",
}


def classify_action_text(text: str, source: str = "") -> str:
    t = str(text or "").casefold()
    if any(x in t for x in ("hidrive", "speicher-explorer", "speicher explorer", "cloud-ziel", "dateispeicher")):
        return "storage"
    if any(x in t for x in ("tüv", "admin", "kc kommunikation", "project finder", "inventur", "systemstatus")):
        return "system"
    if any(x in t for x in ("wiederherstell", "restore", "backup-explorer", "dashboard", "sicherung prüfen", "report", "historie", "systemabbild")):
        return "restore"
    return "restore" if source == "overview" else "system"


def _find_labelframe(root, text: str):
    for child in root.winfo_children():
        try:
            if isinstance(child, ttk.LabelFrame) and str(child.cget("text")) == text:
                return child
        except Exception:
            pass
        found = _find_labelframe(child, text)
        if found is not None:
            return found
    return None


def _all_buttons(root):
    out=[]
    for child in root.winfo_children():
        if isinstance(child, (ttk.Button, tk.Button)):
            out.append(child)
        out.extend(_all_buttons(child))
    return out


def _button_text(button) -> str:
    try: return str(button.cget("text") or "")
    except Exception: return ""


def _hide(button):
    for method in ("pack_forget", "grid_remove", "place_forget"):
        try:
            getattr(button, method)(); return
        except Exception:
            pass


def _clone_button(parent, original, text: str | None = None):
    label = text or _button_text(original)
    btn=ttk.Button(parent,text=label,command=original.invoke)
    btn.pack(side="left",padx=(0,7),pady=4)
    return btn


def apply_main_navigation_v1919(AppClass, StorageCenterWindowClass):
    """Keep the backup workspace intact and move secondary tools into tabs.

    Existing buttons are not destroyed. They are hidden and invoked by cloned
    navigation buttons, so all existing callbacks/patches remain the source of
    truth and backup/restore logic is not rewritten.
    """
    if getattr(AppClass,"_main_navigation_v1919",False): return

    # 1.9.29: central database/Supabase profiles are installed here because
    # main navigation already owns the Settings + Storage-Explorer handoff.
    # This keeps the feature additive and leaves backup/restore engines alone.
    from ui import SettingsWindow
    apply_database_profiles_v1929(AppClass, SettingsWindow, StorageCenterWindowClass)

    original_build=AppClass._build

    def build(self):
        original_build(self)
        if getattr(self,"_main_navigation_ready_v1919",False): return
        self._main_navigation_ready_v1919=True
        try:
            self.geometry("1280x800")
            self.minsize(1040,680)
        except Exception: pass

        restore=[]; storage=[]; system=[]
        seen=set()

        def collect(button, source):
            if button in seen: return
            seen.add(button)
            text=_button_text(button).strip()
            if not text: return
            bucket=classify_action_text(text,source)
            (storage if bucket=="storage" else system if bucket=="system" else restore).append((button,text))
            _hide(button)

        overview=_find_labelframe(self,"Übersicht / Wiederherstellung")
        if overview is not None:
            for btn in _all_buttons(overview): collect(btn,"overview")
            try: overview.pack_forget()
            except Exception: pass

        # The long backup row accumulated auxiliary buttons over time. Keep only
        # the actual backup controls there and move every other button to tools.
        backup_parent=getattr(getattr(self,"btn_backup",None),"master",None)
        if backup_parent is not None:
            for btn in _all_buttons(backup_parent):
                text=_button_text(btn).strip()
                if text and text not in CORE_BACKUP_BUTTONS:
                    collect(btn,"backup")

        # Project Finder was historically added to the title row; move it too.
        try:
            top=self.winfo_children()[0]
            for btn in _all_buttons(top):
                text=_button_text(btn)
                if "project finder" in text.casefold() or "inventur" in text.casefold(): collect(btn,"top")
        except Exception: pass

        reco=getattr(getattr(self,"lbl_recommend",None),"master",None)
        host=ttk.LabelFrame(self,text="Werkzeuge",padding=(8,5))
        if reco is not None:
            host.pack(fill="x",padx=12,pady=(0,6),before=reco)
        else:
            host.pack(fill="x",padx=12,pady=(0,6))
        nb=ttk.Notebook(host); nb.pack(fill="x")
        tab_restore=ttk.Frame(nb,padding=(8,4)); tab_storage=ttk.Frame(nb,padding=(8,4)); tab_system=ttk.Frame(nb,padding=(8,4))
        nb.add(tab_restore,text="♻ Wiederherstellen")
        nb.add(tab_storage,text="🗂 Speicher")
        nb.add(tab_system,text="🛠 System & Projekte")

        rrow=ttk.Frame(tab_restore); rrow.pack(fill="x")
        for original,text in restore: _clone_button(rrow,original,text)
        if not restore: ttk.Label(rrow,text="Wiederherstellungswerkzeuge werden hier gesammelt.").pack(side="left")

        srow=ttk.Frame(tab_storage); srow.pack(fill="x")
        ttk.Button(srow,text="🗂 Speicher-Explorer",command=lambda:StorageCenterWindowClass(self)).pack(side="left",padx=(0,7),pady=4)
        for original,text in storage: _clone_button(srow,original,text)
        ttk.Separator(srow,orient="vertical").pack(side="left",fill="y",padx=7,pady=4)
        ttk.Button(srow,text="Datenbank-Stammdaten",command=lambda:self.open_settings()).pack(side="left",padx=(0,7),pady=4)
        ttk.Button(srow,text="B2-Stammdaten",command=lambda:self.open_settings(tab="storage")).pack(side="left",padx=(0,7),pady=4)
        ttk.Button(srow,text="Cloud-/HiDrive-Stammdaten",command=lambda:self.open_settings(tab="cloud")).pack(side="left",padx=(0,7),pady=4)

        yrow=ttk.Frame(tab_system); yrow.pack(fill="x")
        for original,text in system: _clone_button(yrow,original,text)
        if not system: ttk.Label(yrow,text="System-, TÜV- und Projektwerkzeuge werden hier gesammelt.").pack(side="left")

        self.storage_tools_notebook_v1919=nb

    AppClass._build=build
    AppClass._main_navigation_v1919=True
