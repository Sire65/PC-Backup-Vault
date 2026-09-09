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

    The filesystem target is authoritative. This intentionally does not read
    ``store.data['filesystem_targets']`` directly: callers pass the same
    ``storage_v180._targets`` function used by the professional TÜV, so future
    target wrappers/migrations cannot make the Live Explorer diverge again.
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

    def add(account: dict):
        if account.get("enabled", True) is False:
            return
        key = _text(account.get("id")) or f"{_text(account.get('name'))}|{_text(account.get('username'))}"
        if not key or key in seen:
            return
        seen.add(key)
        out.append(dict(account))

    # 1) Authoritative path: the same CLOUD-SFTP target used by backup/TÜV.
    for target in targets:
        if not _is_sftp_target(target):
            continue
        sftp_targets.append(target)
        account_id = _text(target.get("cloud_account_id"))
        account = by_id.get(account_id)
        if account is None:
            missing_ids.append(account_id)
            continue
        add(account)

    # 2) Compatibility path for a configured HiDrive account before a bridge
    # target has ever been generated.
    for account in accounts:
        if _looks_like_hidrive(account):
            add(account)

    diagnostics = {
        "cloud_accounts": len(accounts),
        "filesystem_targets": len(targets),
        "sftp_targets": len(sftp_targets),
        "matched_accounts": len(out),
        "missing_account_ids": tuple(dict.fromkeys(missing_ids)),
    }
    return out, diagnostics


def _account_names(accounts):
    return [
        _text(a.get("name")) or _text(a.get("username")) or _text(a.get("id")) or "HiDrive-Konto"
        for a in accounts
    ]


def _diagnostic_text(diag: dict, version: str) -> str:
    missing = ", ".join(diag.get("missing_account_ids") or ()) or "–"
    return (
        f"Version {version} · Cloud-Konten: {diag.get('cloud_accounts', 0)} · "
        f"CLOUD-SFTP-Ziele: {diag.get('sftp_targets', 0)} · "
        f"zugeordnete Konten: {diag.get('matched_accounts', 0)} · "
        f"fehlende Konto-IDs: {missing}"
    )


def apply_hidrive_live_runtime_fix_v1927(live_module, storage_module, cloud_module, app_version: str) -> None:
    """Bind the HiDrive Live Explorer directly to the working runtime target graph.

    This supersedes older metadata-only account filters and also repairs an
    already-built disabled combobox after the wrapped Explorer constructor has
    run. A visible runtime diagnostic remains when no usable account can be
    resolved, so this state can no longer fail silently.
    """
    if getattr(live_module, "_hidrive_live_runtime_fix_v1927", False):
        return

    def runtime_accounts(store):
        accounts, _diag = resolve_hidrive_runtime_accounts(
            store, storage_module._targets, cloud_module.cloud_accounts
        )
        return accounts

    # Make the normal constructor path use the authoritative resolver first.
    live_module._hidrive_accounts = runtime_accounts

    Explorer = live_module.HiDriveLiveExplorer
    original_init = Explorer.__init__

    def explorer_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        accounts, diag = resolve_hidrive_runtime_accounts(
            self.store, storage_module._targets, cloud_module.cloud_accounts
        )
        self._pbv_hidrive_runtime_diag_v1927 = dict(diag)
        self.accounts = accounts

        try:
            self.title(f"PC Backup Vault {app_version} – HiDrive Live-Explorer")
        except Exception:
            pass

        names = _account_names(accounts)
        combo = getattr(self, "account_combo", None)
        if combo is None:
            return

        if accounts:
            # Repair a combobox that an older wrapped constructor disabled.
            combo.configure(values=names, state="readonly")
            current = combo.current()
            if current < 0 or current >= len(accounts):
                combo.current(0)
            # Ensure home/path/list are initialized even when the wrapped
            # constructor previously saw zero accounts and skipped switch_account.
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
