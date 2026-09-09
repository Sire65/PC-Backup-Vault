from __future__ import annotations


def _text(value) -> str:
    return str(value or "").strip()


def _upper(value) -> str:
    return _text(value).upper()


def _is_sftp_target(target: dict) -> bool:
    return bool(
        _text(target.get("cloud_account_id"))
        and _upper(target.get("kind")) == "CLOUD-SFTP"
        and _upper(target.get("cloud_method")) == "SFTP"
    )


def _looks_like_hidrive(account: dict) -> bool:
    provider = " ".join(
        _text(account.get(key)).casefold()
        for key in ("provider_code", "provider", "provider_name", "cloud_provider")
    )
    name = _text(account.get("name")).casefold()
    endpoint = _text(account.get("endpoint")).casefold()
    root = _text(account.get("root_path")).casefold()
    return bool(
        "strato" in provider
        or "hidrive" in provider
        or "strato" in name
        or "hidrive" in name
        or "hidrive.strato" in endpoint
        or (root.startswith("/users/") and ("strato" in name or "hidrive" in name))
    )


def resolve_hidrive_runtime_accounts(store, targets_func, cloud_accounts_func):
    """Resolve HiDrive accounts from the exact runtime sources used by backup/TÜV.

    A CLOUD-SFTP target is authoritative. Older installations can contain a
    stale ``enabled=false`` on the cloud-account record while the generated
    SFTP target is still present and the real SFTP transport/TÜV works. Such a
    target-backed account must remain visible in the Live Explorer. The
    ``enabled`` flag is only respected for compatibility-only accounts that do
    not yet have a runtime SFTP target.
    """
    accounts = [dict(x or {}) for x in list(cloud_accounts_func(store) or [])]
    targets = [dict(x or {}) for x in list(targets_func(store) or [])]

    by_id = {
        _text(account.get("id")): account
        for account in accounts
        if _text(account.get("id"))
    }
    out = []
    seen = set()
    missing_ids = []
    sftp_targets = []
    stale_disabled_ids = []

    def add(account: dict, *, authoritative: bool = False):
        account_id = _text(account.get("id"))
        if account.get("enabled", True) is False:
            if not authoritative:
                return
            if account_id:
                stale_disabled_ids.append(account_id)

        key = account_id or f"{_text(account.get('name'))}|{_text(account.get('username'))}"
        if not key or key in seen:
            return
        seen.add(key)
        out.append(dict(account))

    # Authoritative path: exactly the CLOUD-SFTP targets used by backup/TÜV.
    # Do not reject these accounts because of a stale legacy enabled flag.
    for target in targets:
        if not _is_sftp_target(target):
            continue
        sftp_targets.append(target)
        account_id = _text(target.get("cloud_account_id"))
        account = by_id.get(account_id)
        if account is None:
            missing_ids.append(account_id)
            continue
        add(account, authoritative=True)

    # Compatibility path before a filesystem bridge was ever generated.
    # Here the account-level enabled switch still has its normal meaning.
    for account in accounts:
        if _looks_like_hidrive(account):
            add(account, authoritative=False)

    diagnostics = {
        "cloud_accounts": len(accounts),
        "filesystem_targets": len(targets),
        "sftp_targets": len(sftp_targets),
        "matched_accounts": len(out),
        "missing_account_ids": tuple(dict.fromkeys(missing_ids)),
        "stale_disabled_account_ids": tuple(dict.fromkeys(stale_disabled_ids)),
    }
    return out, diagnostics


def _account_names(accounts):
    return [
        _text(a.get("name")) or _text(a.get("username")) or _text(a.get("id")) or "HiDrive-Konto"
        for a in accounts
    ]


def _diagnostic_text(diag: dict, version: str) -> str:
    missing = ", ".join(diag.get("missing_account_ids") or ()) or "–"
    stale = ", ".join(diag.get("stale_disabled_account_ids") or ()) or "–"
    return (
        f"Version {version} · Cloud-Konten: {diag.get('cloud_accounts', 0)} · "
        f"CLOUD-SFTP-Ziele: {diag.get('sftp_targets', 0)} · "
        f"zugeordnete Konten: {diag.get('matched_accounts', 0)} · "
        f"fehlende Konto-IDs: {missing} · alte enabled=false: {stale}"
    )


def apply_hidrive_live_runtime_fix_v1927(live_module, storage_module, cloud_module, app_version: str) -> None:
    """Bind the explorer to the same runtime target graph as backup and TÜV."""
    if getattr(live_module, "_hidrive_live_runtime_fix_v1927", False):
        return

    def runtime_accounts(store):
        accounts, _diag = resolve_hidrive_runtime_accounts(
            store, storage_module._targets, cloud_module.cloud_accounts
        )
        return accounts

    # The normal constructor now uses the authoritative resolver directly.
    live_module._hidrive_accounts = runtime_accounts

    Explorer = live_module.HiDriveLiveExplorer
    original_init = Explorer.__init__

    def explorer_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        old_accounts = list(getattr(self, "accounts", []) or [])
        combo = getattr(self, "account_combo", None)
        old_index = combo.current() if combo is not None else -1
        old_id = ""
        if 0 <= old_index < len(old_accounts):
            old_id = _text(old_accounts[old_index].get("id"))
        old_state = _text(combo.cget("state")) if combo is not None else ""

        accounts, diag = resolve_hidrive_runtime_accounts(
            self.store, storage_module._targets, cloud_module.cloud_accounts
        )
        self._pbv_hidrive_runtime_diag_v1927 = dict(diag)
        self.accounts = accounts

        try:
            self.title(f"PC Backup Vault {app_version} – HiDrive Live-Explorer")
        except Exception:
            pass

        if combo is None:
            return

        if accounts:
            combo.configure(values=_account_names(accounts), state="readonly")
            preferred = next(
                (i for i, account in enumerate(accounts) if old_id and _text(account.get("id")) == old_id),
                -1,
            )
            if preferred < 0:
                preferred = old_index if 0 <= old_index < len(accounts) else 0
            combo.current(preferred)

            # Only repair/init when the wrapped constructor had no usable
            # account. If it already loaded normally, do not start a second
            # concurrent SFTP refresh.
            was_usable = old_state != "disabled" and 0 <= old_index < len(old_accounts)
            if not was_usable:
                self.busy = False
                self.switch_account()
        else:
            combo.configure(values=(), state="disabled")
            try:
                self.status_var.set(_diagnostic_text(diag, app_version))
            except Exception:
                pass

    Explorer.__init__ = explorer_init
    live_module._hidrive_live_runtime_fix_v1927 = True
