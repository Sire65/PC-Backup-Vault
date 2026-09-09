from __future__ import annotations


def apply_hidrive_live_safety_v1914(live_module):
    """Harden mutable Live-Explorer actions without touching the backup/restore engine."""
    if getattr(live_module, "_hidrive_live_safety_v1914", False):
        return

    original_accounts = live_module._hidrive_accounts

    def _is_protected(path: str, home: str) -> bool:
        path = live_module._norm_remote(path)
        home = live_module._norm_remote(home)
        if not live_module._within(path, home):
            return False
        parts = [part.casefold() for part in path.split("/") if part]
        return str(live_module.PROTECTED_VAULT).casefold() in parts

    def _hidrive_accounts(store):
        return [a for a in original_accounts(store) if bool(a.get("enabled", True))]

    live_module._is_protected = _is_protected
    live_module._hidrive_accounts = _hidrive_accounts
    live_module._hidrive_live_safety_v1914 = True
