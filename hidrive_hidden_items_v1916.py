from __future__ import annotations

import posixpath
import stat as statmod


HIDDEN_LABEL = "VERSTECKT"
PROTECTED_LABEL = "GESCHÜTZT"


def _to_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _extended_hidden(attr) -> bool:
    """Best effort for non-standard SFTP/DOS hidden metadata.

    SFTP itself has no portable hidden flag. HiDrive normally exposes hidden
    Unix-style entries by a leading dot. If a server additionally supplies
    DOS/extended attributes, honour the hidden bit (0x02) as well.
    """
    for field in ("st_file_attributes", "file_attributes"):
        value = getattr(attr, field, None)
        try:
            if value is not None and int(value) & 0x02:
                return True
        except (TypeError, ValueError):
            pass

    extras = getattr(attr, "attr", None) or {}
    if not isinstance(extras, dict):
        return False

    for key, raw in extras.items():
        key_text = _to_text(key).strip().lower()
        value_text = _to_text(raw).strip().lower()
        if "hidden" in key_text and value_text not in {"", "0", "false", "no", "off"}:
            return True
        if "hidden" in value_text:
            return True
        if "dosattr" in key_text or "file_attributes" in key_text or "fileattributes" in key_text:
            token = value_text.split()[0] if value_text else ""
            try:
                number = int(token, 0)
            except ValueError:
                try:
                    number = int(token, 16)
                except ValueError:
                    number = 0
            if number & 0x02:
                return True
    return False


def hidden_info(attr, name: str) -> tuple[bool, str]:
    reasons: list[str] = []
    clean = str(name or "")
    if clean.startswith(".") and clean not in {".", ".."}:
        reasons.append("Punktname")
    if _extended_hidden(attr):
        reasons.append("Attribut")
    return bool(reasons), ", ".join(reasons)


def list_remote_all(sftp, path: str) -> list[dict]:
    """Return every SFTP directory entry and explicitly classify hidden ones."""
    rows: list[dict] = []
    for attr in sftp.listdir_attr(path):
        name = str(getattr(attr, "filename", "") or "")
        if not name or name in {".", ".."}:
            continue
        is_dir = statmod.S_ISDIR(int(getattr(attr, "st_mode", 0) or 0))
        hidden, hidden_reason = hidden_info(attr, name)
        rows.append({
            "name": name,
            "path": posixpath.join(path, name),
            "is_dir": is_dir,
            "size": 0 if is_dir else int(getattr(attr, "st_size", 0) or 0),
            "mtime": int(getattr(attr, "st_mtime", 0) or 0),
            "hidden": hidden,
            "hidden_reason": hidden_reason,
        })
    rows.sort(key=lambda x: (not x["is_dir"], x["name"].casefold()))
    return rows


def decorate_text(text: str, row: dict, protected_name: str = ".pc-backup-vault") -> str:
    if not bool(row.get("hidden")):
        return text
    raw = str(text or "")
    arrow = ""
    rest = raw
    for marker in ("▶ ", "▼ "):
        if raw.startswith(marker):
            arrow = marker
            rest = raw[len(marker):]
            break
    protected = str(row.get("name") or "") == protected_name
    badge = f"👁 [{HIDDEN_LABEL} · {PROTECTED_LABEL}]" if protected else f"👁 [{HIDDEN_LABEL}]"
    return f"{arrow}{badge} {rest}"


def decorate_values(values, row: dict, protected_name: str = ".pc-backup-vault"):
    if not bool(row.get("hidden")) or not values:
        return values
    out = list(values)
    # Main explorer: first value is the Type column. Folder picker only has
    # one timestamp value and therefore must remain untouched.
    if len(out) >= 4:
        kind = "Ordner" if bool(row.get("is_dir")) else "Datei"
        if str(row.get("name") or "") == protected_name:
            out[0] = f"Geschützt · versteckter {kind}"
        else:
            out[0] = f"Versteckter {kind}"
    return tuple(out)


def _install_insert_decorator(owner, protected_name: str):
    tree = getattr(owner, "tree", None)
    if tree is None or getattr(tree, "_pbv_hidden_insert_v1916", False):
        return
    original_insert = tree.insert

    def insert(parent, index, iid=None, **kw):
        row = None
        if iid is not None:
            row = getattr(owner, "_tree_rows", {}).get(iid)
        if row and row.get("hidden"):
            kw["text"] = decorate_text(kw.get("text", ""), row, protected_name)
            if "values" in kw:
                kw["values"] = decorate_values(kw.get("values"), row, protected_name)
        return original_insert(parent, index, iid=iid, **kw)

    tree.insert = insert
    tree._pbv_hidden_insert_v1916 = True


def _decorate_existing(owner, protected_name: str):
    tree = getattr(owner, "tree", None)
    rows = getattr(owner, "_tree_rows", {})
    if tree is None:
        return
    for iid, row in list(rows.items()):
        if not row.get("hidden"):
            continue
        try:
            text = str(tree.item(iid, "text") or "")
            if f"[{HIDDEN_LABEL}" not in text:
                tree.item(iid, text=decorate_text(text, row, protected_name))
            values = tree.item(iid, "values")
            if values:
                tree.item(iid, values=decorate_values(values, row, protected_name))
        except Exception:
            pass


def apply_hidrive_hidden_items_v1916(live_module):
    """Show and mark hidden HiDrive entries in explorer and folder picker."""
    if getattr(live_module, "_hidrive_hidden_items_v1916", False):
        return

    # Replace the directory reader rather than merely decorating the old
    # result so hidden dot entries can never be lost through UI filtering.
    live_module._list_remote = list_remote_all

    Explorer = live_module.HiDriveLiveExplorer
    Picker = live_module.RemoteFolderPicker
    original_explorer_init = Explorer.__init__
    original_picker_init = Picker.__init__
    protected_name = str(getattr(live_module, "PROTECTED_VAULT", ".pc-backup-vault"))

    def explorer_init(self, *args, **kwargs):
        original_explorer_init(self, *args, **kwargs)
        _install_insert_decorator(self, protected_name)
        _decorate_existing(self, protected_name)
        try:
            self.status_var.set((self.status_var.get() + " · Versteckte Einträge werden angezeigt").strip(" ·"))
        except Exception:
            pass

    def picker_init(self, *args, **kwargs):
        original_picker_init(self, *args, **kwargs)
        _install_insert_decorator(self, protected_name)
        _decorate_existing(self, protected_name)

    Explorer.__init__ = explorer_init
    Picker.__init__ = picker_init
    live_module._hidrive_hidden_items_v1916 = True
