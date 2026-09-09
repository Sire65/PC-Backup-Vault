from __future__ import annotations


def _norm_hint(value: object) -> str:
    return str(value or "").strip().casefold()


def _looks_like_strato_hidrive(account: dict) -> bool:
    provider = " ".join(
        _norm_hint(account.get(key))
        for key in ("provider_code", "provider", "provider_name", "cloud_provider")
    )
    name = _norm_hint(account.get("name"))
    endpoint = _norm_hint(account.get("endpoint"))
    root = _norm_hint(account.get("root_path"))

    if "strato" in provider or "hidrive" in provider:
        return True
    if "strato" in name or "hidrive" in name:
        return True
    if "hidrive.strato" in endpoint or "strato.com" in endpoint and "hidrive" in endpoint:
        return True
    if root.startswith("/users/") and ("strato" in name or "hidrive" in name):
        return True
    return False


def _sftp_target_account_ids(store) -> set[str]:
    ids: set[str] = set()
    data = getattr(store, "data", {}) or {}
    for target in data.get("filesystem_targets") or []:
        method = str((target or {}).get("cloud_method") or "").upper()
        kind = str((target or {}).get("kind") or "").upper()
        account_id = str((target or {}).get("cloud_account_id") or "").strip()
        if account_id and (method == "SFTP" or kind == "CLOUD-SFTP"):
            ids.add(account_id)
    return ids


def eligible_hidrive_accounts(store, cloud_accounts_func) -> list[dict]:
    """Return every active account that the existing HiDrive SFTP transport can open.

    Modern and legacy STRATO/HiDrive metadata remain valid signals. In addition,
    an account referenced by an existing CLOUD-SFTP filesystem target is an
    authoritative runtime signal because the TÜV and backup transport resolve
    that same ``cloud_account_id`` through ``sftp_connection``. This keeps the
    Live Explorer consistent with connections that are already proven to work.
    """
    sftp_target_ids = _sftp_target_account_ids(store)
    out: list[dict] = []
    seen: set[str] = set()

    for raw in cloud_accounts_func(store):
        account = dict(raw or {})
        if account.get("enabled", True) is False:
            continue

        account_id = str(account.get("id") or "").strip()
        provider_code = str(account.get("provider_code") or "").upper()
        explicit_strato = provider_code == "STRATO_HIDRIVE"
        legacy_strato = _looks_like_strato_hidrive(account)
        has_live_sftp_target = bool(account_id and account_id in sftp_target_ids)

        # Keep the explorer aligned with the runtime/TÜV path: a CLOUD-SFTP
        # target already proves that this account is handled by the SFTP bridge.
        eligible = explicit_strato or legacy_strato or has_live_sftp_target
        if not eligible:
            continue

        key = account_id or f"{account.get('name')}|{account.get('username')}"
        if key in seen:
            continue
        seen.add(key)
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
