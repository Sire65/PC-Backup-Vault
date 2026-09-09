from __future__ import annotations

import posixpath
import stat as statmod


def _collect_delete_manifest(sftp, rows: list[dict]) -> tuple[list[dict], list[str], int]:
    """Collect exact remote paths for safe recursive deletion."""
    files: list[dict] = []
    dirs: list[str] = []

    def walk(remote: str, is_dir: bool, size: int = 0):
        if is_dir:
            dirs.append(remote)
            for attr in sftp.listdir_attr(remote):
                name = str(getattr(attr, "filename", "") or "")
                if not name or name in {".", ".."}:
                    continue
                child = posixpath.join(remote, name)
                child_is_dir = statmod.S_ISDIR(int(getattr(attr, "st_mode", 0) or 0))
                walk(child, child_is_dir, int(getattr(attr, "st_size", 0) or 0))
        else:
            files.append({"remote": remote, "size": int(size or 0)})

    for row in rows:
        walk(str(row.get("path") or ""), bool(row.get("is_dir")), int(row.get("size") or 0))
    return files, dirs, sum(int(x["size"]) for x in files)


def apply_context_progress_safety_v1917(context_module, live_module):
    Explorer = live_module.HiDriveLiveExplorer
    if getattr(Explorer, "_context_progress_safety_v1917", False):
        return

    def move_selected(self):
        rows = self.selected_rows()
        if not rows:
            context_module.messagebox.showinfo("Verschieben", "Bitte Dateien oder Ordner auswählen.", parent=self)
            return
        paths = [str(x["path"]) for x in rows]
        if not self._confirm_protected(paths, "Verschieben"):
            return
        picker = live_module.RemoteFolderPicker(self, self.store, self._account(), self.current_path)
        self.wait_window(picker)
        dest_dir = picker.result
        if not dest_dir:
            return
        dests = [posixpath.join(dest_dir, str(x["name"])) for x in rows]
        if not self._confirm_protected(dests, "Verschieben"):
            return
        for row in rows:
            if row.get("is_dir") and live_module._within(dest_dir, str(row["path"])):
                context_module.messagebox.showwarning(
                    "Verschieben",
                    f"Ordner kann nicht in sich selbst verschoben werden:\n{row['name']}",
                    parent=self,
                )
                return
        if not context_module._confirm(
            self,
            "HiDrive verschieben",
            f"{len(rows)} Auswahl(en) wirklich nach\n{dest_dir}\nverschieben?\n\n"
            "Existierende Ziele werden aus Sicherheitsgründen nicht überschrieben.",
        ):
            return
        account = self._account()

        def worker():
            with live_module.sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                for row, dest in zip(rows, dests):
                    if str(row["path"]) == dest:
                        continue
                    if live_module._remote_exists(sftp, dest):
                        raise FileExistsError(f"Ziel existiert bereits: {dest}")
                    sftp.rename(str(row["path"]), dest)

        self._run_operation("Verschieben", worker, f"{len(rows)} Eintrag/Einträge verschoben")

    def delete_selected(self):
        rows = self.selected_rows()
        if not rows:
            context_module.messagebox.showinfo("Löschen", "Bitte Dateien oder Ordner auswählen.", parent=self)
            return
        paths = [str(r["path"]) for r in rows]
        if not self._confirm_protected(paths, "Löschen"):
            return
        names = "\n".join("• " + str(r["name"]) for r in rows[:12])
        if len(rows) > 12:
            names += f"\n… und {len(rows)-12} weitere"
        if not context_module._confirm(
            self,
            "HiDrive löschen",
            f"Diese {len(rows)} Auswahl(en) wirklich dauerhaft auf HiDrive löschen?\n\n{names}\n\n"
            "Ordner werden einschließlich ihres Inhalts gelöscht. Diese Aktion kann nicht rückgängig gemacht werden.",
        ):
            return
        account = self._account()

        def worker(report):
            with live_module.sftp_connection(self.store, str(account.get("id"))) as (sftp, _):
                files, dirs, total = _collect_delete_manifest(sftp, rows)
                if any(p == self.home for p in dirs) or any(x["remote"] == self.home for x in files):
                    raise RuntimeError("Der HiDrive-Benutzerordner selbst darf nicht gelöscht werden.")
                total_entries = len(files) + len(dirs)
                files_done = 0
                bytes_done = 0
                report(
                    phase="Löschen läuft",
                    files_done=0,
                    files_total=total_entries,
                    bytes_done=0,
                    bytes_total=total,
                )
                for item in files:
                    sftp.remove(item["remote"])
                    bytes_done += int(item["size"] or 0)
                    files_done += 1
                    report(
                        phase="Löschen läuft",
                        current_file=item["remote"],
                        files_done=files_done,
                        files_total=total_entries,
                        bytes_done=bytes_done,
                        bytes_total=total,
                    )
                for remote in sorted(dirs, key=lambda p: p.count("/"), reverse=True):
                    sftp.rmdir(remote)
                    files_done += 1
                    report(
                        phase="Löschen läuft",
                        current_file=remote,
                        files_done=files_done,
                        files_total=total_entries,
                        bytes_done=bytes_done,
                        bytes_total=total,
                    )

        self._pbv_progress_operation_v1917(
            "HiDrive löschen",
            worker,
            f"{len(rows)} Auswahl(en) gelöscht",
        )

    Explorer.move_selected = move_selected
    Explorer.delete_selected = delete_selected
    Explorer._context_progress_safety_v1917 = True
