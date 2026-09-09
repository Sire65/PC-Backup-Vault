from __future__ import annotations


def eligible_hidrive_accounts(store, cloud_accounts_func) -> list[dict]:
    """Return every active STRATO HiDrive account, independent of legacy method flags.

    The live explorer always uses the dedicated SFTP transport when an account is
    selected. Older account records may not contain ``methods=['SFTP']`` even
    though username/password and the STRATO SFTP endpoint are valid. Filtering
    those records by the methods field therefore hides otherwise usable accounts.
    """
    out: list[dict] = []
    for raw in cloud_accounts_func(store):
        account = dict(raw or {})
        if str(account.get("provider_code") or "").upper() != "STRATO_HIDRIVE":
            continue
        if account.get("enabled", True) is False:
            continue
        out.append(account)
    return out


def apply_hidrive_account_list_fix_v1918(live_module) -> None:
    """Patch only the HiDrive Live-Explorer account enumeration."""
    if getattr(live_module, "_hidrive_account_list_fix_v1918", False):
        return

    def _hidrive_accounts(store):
        return eligible_hidrive_accounts(store, live_module.cloud_accounts)

    live_module._hidrive_accounts = _hidrive_accounts
    live_module._hidrive_account_list_fix_v1918 = True
