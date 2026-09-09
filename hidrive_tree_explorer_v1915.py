from __future__ import annotations

import hashlib
import posixpath
import threading
from datetime import datetime
from pathlib import Path


DUMMY_SUFFIX = "::pbv-dummy"
EMPTY_SUFFIX = "::pbv-empty"


def _node_id(path: str) -> str:
    """Stable Tk item id for one remote path."""
    value = str(path or "").replace("\\", "/")
    return "pbv-" + hashlib.sha1(value.encode("utf-8")).hexdigest()


def _folder_label(name: str, opened: bool = False) -> str:
    return f"{'▼ 📂' if opened else '▶ 📁'} {name}"


def _file_label(name: str) -> str:
    return f"📄 {name}"


def _parent_remote(path: str, home: str) -> str:
    path = posixpath.normpath("/" + str(path or "").replace("\\", "/").lstrip("/"))
    home = posixpath.normpath("/" + str(home or "").replace("\\", "/").lstrip("/"))
    if path == home:
        return home
    parent = posixpath.dirname(path.rstrip("/")) or home
    return parent if parent == home or parent.startswith(home.rstrip("/") + "/") else home


def _action_target(current_path: str, selected_rows: list[dict]) -> str:
    """Windows-like target: a single selected folder becomes the destination."""
    if len(selected_rows) == 1 and bool(selected_rows[0].get("is_dir")):
        return str(selected_rows[0].get("path") or current_path)
    return str(current_path)


def apply_hidrive_tree_explorer_v1915(live_module):
    """
    Add a lazy, hierarchical Windows-Explorer-style tree to the existing
    HiDrive Live-Explorer. Backup/restore transport and archive logic are not
    modified.
    """
    if getattr(live_module, "_hidrive_tree_explorer_v1915", False):
        return

    Explorer = live_module.HiDriveLiveExplorer
    Picker = live_module.RemoteFolderPicker

    original_explorer_init = Explorer.__init__
    original_picker_init = Picker.__init__

    def _format_modified(row: dict) -> str:
        stamp = int(row.get("mtime") or 0)
        return datetime.fromtimestamp(stamp).strftime("%d.%m.%Y %H:%M") if stamp else "–"

    def _row_values(row: dict) -> tuple[str, str, str, str]:
        is_dir = bool(row.get("is_dir"))
        return (
            "Ordner" if is_dir else "Datei",
            "–" if is_dir else live_module._format_size(int(row.get("size") or 0)),
            _format_modified(row),
            str(row.get("path") or ""),
        )

    def _capture_expanded(self) -> set[str]:
        out: set[str] = set()
        tree = getattr(self, "tree", None)
        rows = getattr(self, "_tree_rows", {})
        if tree is None:
            return out
        for iid, row in list(rows.items()):
            try:
                if row.get("is_dir") and bool(tree.item(iid, "open")):
                    out.add(str(row.get("path") or ""))
            except Exception:
                pass
        return out

    def _insert_row(self, parent_iid: str, row: dict):
        path = live_module._norm_remote(str(row.get("path") or ""))
        row = dict(row)
        row["path"] = path
        iid = _node_id(path)
        if self.tree.exists(iid):
            self.tree.delete(iid)
        self._tree_rows[iid] = row
        is_dir = bool(row.get("is_dir"))
        reopen = is_dir and path in getattr(self, "_tree_reopen_paths", set())
        text = _folder_label(str(row.get("name") or ""), reopen) if is_dir else _file_label(str(row.get("name") or ""))
        self.tree.insert(parent_iid, "end", iid=iid, text=text, values=_row_values(row), open=reopen)
        if is_dir:
            self.tree.insert(iid, "end", iid=iid + DUMMY_SUFFIX, text="Wird beim Aufklappen geladen …", values=("", "", "", ""))
            if reopen:
                self.after_idle(lambda item=iid: self._tree_expand(item))
        return iid

    def _tree_render_root(self, rows: list[dict], path: str, epoch: int):
        if not self.winfo_exists() or epoch != getattr(self, "_tree_epoch", -1):
            return
        self.tree.delete(*self.tree.get_children())
        self._tree_rows = {}
        self._tree_loaded = set()
        self._tree_loading = set()
        for row in rows:
            _insert_row(self, "", row)
        self._set_busy(False, f"{len(rows)} Einträge · Baumansicht · {path}")

    def _tree_children_loaded(self, iid: str, path: str, rows: list[dict], epoch: int):
        if not self.winfo_exists() or epoch != getattr(self, "_tree_epoch", -1) or not self.tree.exists(iid):
            return
        for child in self.tree.get_children(iid):
            self.tree.delete(child)
        for row in rows:
            _insert_row(self, iid, row)
        if not rows:
            self.tree.insert(iid, "end", iid=iid + EMPTY_SUFFIX, text="(leer)", values=("", "", "", ""))
        self._tree_loaded.add(path)
        self._tree_loading.discard(path)
        row = self._tree_rows.get(iid)
        if row:
            self.tree.item(iid, text=_folder_label(str(row.get("name") or ""), True), open=True)

    def _tree_children_failed(self, iid: str, path: str, exc, epoch: int):
        if epoch != getattr(self, "_tree_epoch", -1):
            return
        self._tree_loading.discard(path)
        if self.tree.exists(iid):
            for child in self.tree.get_children(iid):
                self.tree.delete(child)
            self.tree.insert(iid, "end", iid=iid + EMPTY_SUFFIX, text=f"Lesefehler: {exc}", values=("", "", "", ""))
            row = self._tree_rows.get(iid)
            if row:
                self.tree.item(iid, text=_folder_label(str(row.get("name") or ""), True), open=True)
        self.status_var.set(f"Unterordner konnten nicht geladen werden: {path}")

    def _tree_expand(self, iid: str):
        row = self._tree_rows.get(iid)
        if not row or not row.get("is_dir") or not self.tree.exists(iid):
            return
        path = str(row.get("path") or "")
        self.tree.item(iid, text=_folder_label(str(row.get("name") or ""), True), open=True)
        if path in self._tree_loaded or path in self._tree_loading:
            return
        account = self._account()
        if not account:
            return
        self._tree_loading.add(path)
        epoch = self._tree_epoch
        children = self.tree.get_children(iid)
        if children:
            try:
                self.tree.item(children[0], text="Wird geladen …")
            except Exception:
                pass

        def work():
            try:
                with live_module.sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                    rows = live_module._list_remote(sftp, path)
                self.after(0, lambda: _tree_children_loaded(self, iid, path, rows, epoch))
            except Exception as exc:
                self.after(0, lambda e=exc: _tree_children_failed(self, iid, path, e, epoch))

        threading.Thread(target=work, name="pbv-hidrive-tree-expand", daemon=True).start()

    def _tree_on_open(self, _event=None):
        iid = self.tree.focus()
        if iid:
            self.after_idle(lambda item=iid: self._tree_expand(item))

    def _tree_on_close(self, _event=None):
        iid = self.tree.focus()
        row = self._tree_rows.get(iid)
        if row and row.get("is_dir") and self.tree.exists(iid):
            self.tree.item(iid, text=_folder_label(str(row.get("name") or ""), False))

    def _tree_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        row = self._tree_rows.get(iid)
        if not row or not row.get("is_dir"):
            return
        opened = bool(self.tree.item(iid, "open"))
        if opened:
            self.tree.item(iid, open=False, text=_folder_label(str(row.get("name") or ""), False))
        else:
            self.tree.item(iid, open=True, text=_folder_label(str(row.get("name") or ""), True))
            self._tree_expand(iid)
        return "break"

    def explorer_init(self, *args, **kwargs):
        self._tree_rows = {}
        self._tree_loaded = set()
        self._tree_loading = set()
        self._tree_reopen_paths = set()
        self._tree_epoch = 0
        original_explorer_init(self, *args, **kwargs)
        self.tree.heading("#0", text="Name / Ordnerstruktur")
        self.tree.column("#0", width=520, minwidth=280, stretch=True)
        try:
            self.tree.column("path", width=400)
        except Exception:
            pass
        self.tree.unbind("<Double-1>")
        self.tree.bind("<Double-1>", self._tree_double_click)
        self.tree.bind("<<TreeviewOpen>>", self._tree_on_open)
        self.tree.bind("<<TreeviewClose>>", self._tree_on_close)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._selection_status())

    def refresh(self):
        if getattr(self, "busy", False):
            return
        account = self._account()
        if not account:
            return
        path = live_module._norm_remote(self.current_path)
        if not live_module._within(path, self.home):
            path = self.home
        self.current_path = path
        self.path_var.set(path)
        self._tree_reopen_paths = {
            p for p in _capture_expanded(self)
            if live_module._within(p, path)
        }
        self._tree_epoch += 1
        epoch = self._tree_epoch
        self._set_busy(True, f"Lade Baumansicht {path} …")

        def work():
            try:
                with live_module.sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                    rows = live_module._list_remote(sftp, path)
                self.after(0, lambda: _tree_render_root(self, rows, path, epoch))
            except Exception as exc:
                self.after(0, lambda e=exc: self._load_failed(e))

        threading.Thread(target=work, name="pbv-hidrive-tree-root", daemon=True).start()

    def selected_rows(self) -> list[dict]:
        return [self._tree_rows[x] for x in self.tree.selection() if x in self._tree_rows]

    def selection_status(self):
        rows = self.selected_rows()
        if not rows:
            return
        if len(rows) == 1:
            self.status_var.set(f"1 ausgewählt · {rows[0]['path']}")
        else:
            self.status_var.set(f"{len(rows)} ausgewählt · Baumansicht ab {self.current_path}")

    def open_selected(self):
        rows = self.selected_rows()
        if len(rows) != 1 or not rows[0].get("is_dir"):
            return
        iid = _node_id(str(rows[0].get("path") or ""))
        if not self.tree.exists(iid):
            return
        opened = bool(self.tree.item(iid, "open"))
        self.tree.item(iid, open=not opened, text=_folder_label(str(rows[0].get("name") or ""), not opened))
        if not opened:
            self._tree_expand(iid)

    def new_folder(self):
        rows = self.selected_rows()
        target = live_module._norm_remote(_action_target(self.current_path, rows))
        name = live_module.simpledialog.askstring("Neuer HiDrive-Ordner", f"Neuer Ordner in:\n{target}\n\nName:", parent=self)
        name = str(name or "").strip()
        if not name:
            return
        if "/" in name or "\\" in name or name in (".", ".."):
            live_module.messagebox.showwarning("HiDrive", "Bitte nur einen Ordnernamen ohne Pfadtrenner eingeben.", parent=self)
            return
        remote = posixpath.join(target, name)
        if not self._confirm_protected([remote], "Ordner anlegen"):
            return
        account = self._account()
        self._run_operation("Ordner anlegen", lambda: self._mkdir(account, remote), f"Ordner {name} angelegt")

    def rename_selected(self):
        rows = self.selected_rows()
        if len(rows) != 1:
            live_module.messagebox.showinfo("Umbenennen", "Bitte genau eine Datei oder einen Ordner auswählen.", parent=self)
            return
        row = rows[0]
        if not self._confirm_protected([row["path"]], "Umbenennen"):
            return
        new_name = live_module.simpledialog.askstring("Umbenennen", "Neuer Name:", initialvalue=row["name"], parent=self)
        new_name = str(new_name or "").strip()
        if not new_name or new_name == row["name"]:
            return
        if "/" in new_name or "\\" in new_name or new_name in (".", ".."):
            live_module.messagebox.showwarning("HiDrive", "Bitte nur einen Namen ohne Pfadtrenner eingeben.", parent=self)
            return
        parent = _parent_remote(str(row["path"]), self.home)
        dest = posixpath.join(parent, new_name)
        if not self._confirm_protected([dest], "Umbenennen"):
            return
        account = self._account()
        self._run_operation("Umbenennen", lambda: self._rename(account, row["path"], dest), f"{row['name']} wurde umbenannt")

    def upload_files(self):
        rows = self.selected_rows()
        target = live_module._norm_remote(_action_target(self.current_path, rows))
        files = live_module.filedialog.askopenfilenames(parent=self, title="Dateien für HiDrive auswählen")
        if not files:
            return
        account = self._account()
        remotes = [posixpath.join(target, Path(x).name) for x in files]
        if not self._confirm_protected(remotes, "Hochladen"):
            return
        if not live_module.messagebox.askyesno(
            "HiDrive hochladen",
            f"Ausgewählte Dateien nach\n{target}\nhochladen?\n\nExistierende Dateien mit gleichem Namen werden überschrieben.",
            parent=self,
        ):
            return

        def worker():
            with live_module.sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                for local, remote in zip(files, remotes):
                    sftp.put(str(local), remote)

        self._run_operation("Hochladen", worker, f"{len(files)} Datei(en) hochgeladen")

    # --- Folder picker: same expandable hierarchy for move destinations. ---
    def picker_insert(self, parent_iid: str, row: dict):
        path = live_module._norm_remote(str(row.get("path") or ""))
        iid = _node_id("picker:" + path)
        data = dict(row)
        data["path"] = path
        self._tree_rows[iid] = data
        self.tree.insert(parent_iid, "end", iid=iid, text=_folder_label(str(data.get("name") or ""), False), values=(_format_modified(data),))
        self.tree.insert(iid, "end", iid=iid + DUMMY_SUFFIX, text="Wird beim Aufklappen geladen …", values=("",))
        return iid

    def picker_load(self):
        self.tree.delete(*self.tree.get_children())
        self._tree_rows = {}
        self._tree_loaded = set()
        self.path_var.set(self.current)
        try:
            with live_module.sftp_connection(self.store, str(self.account.get("id"))) as (sftp, _):
                rows = [r for r in live_module._list_remote(sftp, self.current) if r.get("is_dir")]
            for row in rows:
                picker_insert(self, "", row)
        except Exception as exc:
            live_module.messagebox.showerror("HiDrive", f"Ordner konnten nicht geladen werden.\n\n{exc}", parent=self)

    def picker_expand(self, iid: str):
        row = self._tree_rows.get(iid)
        if not row or not self.tree.exists(iid):
            return
        path = str(row.get("path") or "")
        self.tree.item(iid, text=_folder_label(str(row.get("name") or ""), True), open=True)
        if path in self._tree_loaded:
            return
        try:
            with live_module.sftp_connection(self.store, str(self.account.get("id"))) as (sftp, _):
                rows = [r for r in live_module._list_remote(sftp, path) if r.get("is_dir")]
            for child in self.tree.get_children(iid):
                self.tree.delete(child)
            for child_row in rows:
                picker_insert(self, iid, child_row)
            if not rows:
                self.tree.insert(iid, "end", iid=iid + EMPTY_SUFFIX, text="(leer)", values=("",))
            self._tree_loaded.add(path)
        except Exception as exc:
            live_module.messagebox.showerror("HiDrive", f"Unterordner konnten nicht geladen werden.\n\n{exc}", parent=self)

    def picker_open_event(self, _event=None):
        iid = self.tree.focus()
        if iid:
            self.after_idle(lambda item=iid: picker_expand(self, item))

    def picker_close_event(self, _event=None):
        iid = self.tree.focus()
        row = self._tree_rows.get(iid)
        if row and self.tree.exists(iid):
            self.tree.item(iid, text=_folder_label(str(row.get("name") or ""), False))

    def picker_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        row = self._tree_rows.get(iid)
        if not row:
            return
        opened = bool(self.tree.item(iid, "open"))
        if opened:
            self.tree.item(iid, open=False, text=_folder_label(str(row.get("name") or ""), False))
        else:
            self.tree.item(iid, open=True, text=_folder_label(str(row.get("name") or ""), True))
            picker_expand(self, iid)
        return "break"

    def picker_init(self, *args, **kwargs):
        self._tree_rows = {}
        self._tree_loaded = set()
        original_picker_init(self, *args, **kwargs)
        self.tree.heading("#0", text="Ordnerstruktur")
        self.tree.column("#0", width=520, minwidth=300)
        self.tree.unbind("<Double-1>")
        self.tree.bind("<Double-1>", self._tree_double_click_v1915)
        self.tree.bind("<<TreeviewOpen>>", self._tree_open_v1915)
        self.tree.bind("<<TreeviewClose>>", self._tree_close_v1915)

    def picker_choose(self):
        sel = self.tree.selection()
        if sel and sel[0] in self._tree_rows:
            self.result = str(self._tree_rows[sel[0]]["path"])
        else:
            self.result = self.current
        self.destroy()

    Explorer.__init__ = explorer_init
    Explorer.refresh = refresh
    Explorer.selected_rows = selected_rows
    Explorer._selection_status = selection_status
    Explorer.open_selected = open_selected
    Explorer.new_folder = new_folder
    Explorer.rename_selected = rename_selected
    Explorer.upload_files = upload_files
    Explorer._tree_expand = _tree_expand
    Explorer._tree_on_open = _tree_on_open
    Explorer._tree_on_close = _tree_on_close
    Explorer._tree_double_click = _tree_double_click

    Picker.__init__ = picker_init
    Picker.load = picker_load
    Picker.choose = picker_choose
    Picker._tree_expand_v1915 = picker_expand
    Picker._tree_open_v1915 = picker_open_event
    Picker._tree_close_v1915 = picker_close_event
    Picker._tree_double_click_v1915 = picker_double_click

    live_module._hidrive_tree_explorer_v1915 = True
