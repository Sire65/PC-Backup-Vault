from __future__ import annotations
import os
from pathlib import Path
from config_store import _base_dir


class InstanceLock:
    """Cross-platform process lock; on Windows this uses msvcrt byte locking."""
    def __init__(self, path: Path | None = None):
        self.path = Path(path or (_base_dir() / "pc_backup_vault.lock"))
        self._fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            fh.seek(0)
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    fh.close(); return False
            else:
                import fcntl
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    fh.close(); return False
            self._fh = fh
            try:
                fh.seek(0); fh.truncate(); fh.write(str(os.getpid()).encode("ascii")); fh.flush()
            except Exception:
                pass
            return True
        except Exception:
            try: fh.close()
            except Exception: pass
            return False

    def release(self):
        fh, self._fh = self._fh, None
        if not fh:
            return
        try:
            fh.seek(0)
            if os.name == "nt":
                import msvcrt
                try: msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError: pass
            else:
                import fcntl
                try: fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except OSError: pass
        finally:
            try: fh.close()
            except Exception: pass

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("PC Backup Vault läuft bereits in einem anderen Prozess.")
        return self

    def __exit__(self, *_):
        self.release()
