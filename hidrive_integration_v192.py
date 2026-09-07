from __future__ import annotations

import tempfile
from pathlib import Path

from cloud_targets_v191 import cloud_account, cloud_accounts, provider_name
from hidrive_sftp_v192 import test_hidrive_sftp, upload_file


def apply_hidrive_sftp_v192(cloud_module, storage_module):
    """Complete the existing cloud-target layer with direct STRATO SFTP support.

    Passwords remain in keyring via cloud_targets_v191. The existing filesystem
    backup core creates its AES-GCM encrypted vault in a temporary local staging
    directory; only encrypted chunks/manifests are uploaded to HiDrive.
    """
    if getattr(cloud_module, "_hidrive_sftp_v192", False):
        return

    original_test = cloud_module.test_cloud_account
    original_capable = cloud_module.filesystem_capable_method
    original_bridge = cloud_module.ensure_filesystem_bridge
    original_backup = storage_module.filesystem_backup

    def test_cloud_account(store, account_id, method=None):
        account = cloud_account(store, account_id)
        selected = str(method or (account or {}).get("preferred_method") or "").upper()
        if account and account.get("provider_code") == "STRATO_HIDRIVE" and selected == "SFTP":
            return test_hidrive_sftp(store, account_id)
        return original_test(store, account_id, method)

    def filesystem_capable_method(account):
        preferred = str(account.get("preferred_method") or "").upper()
        methods = [str(x).upper() for x in (account.get("methods") or [])]
        if account.get("provider_code") == "STRATO_HIDRIVE" and "SFTP" in methods:
            if preferred == "SFTP":
                return "SFTP"
        return original_capable(account) or ("SFTP" if account.get("provider_code") == "STRATO_HIDRIVE" and "SFTP" in methods else None)

    def ensure_filesystem_bridge(store, account_id):
        account = cloud_account(store, account_id)
        if account and filesystem_capable_method(account) == "SFTP":
            target_id = f"cloud-{account_id}"
            item = {
                "id": target_id,
                "name": f"Cloud · {account.get('name') or provider_name(account.get('provider_code',''))}",
                "path": f"sftp://sftp.hidrive.strato.com{account.get('root_path') or '/users/' + str(account.get('username') or '')}",
                "kind": "CLOUD-SFTP",
                "volume_hint": "CLOUD",
                "cloud_account_id": account_id,
                "cloud_method": "SFTP",
            }
            rows = store.data.setdefault("filesystem_targets", [])
            old = next((x for x in rows if x.get("id") == target_id), None)
            if old is None:
                rows.append(item)
            else:
                old.clear(); old.update(item)
            store.data["active_filesystem_target_id"] = target_id
            store.save()
            return item
        return original_bridge(store, account_id)

    def filesystem_backup(app, paths, target, control=None, progress=None, plan_name=None):
        if str(target.get("cloud_method") or "").upper() != "SFTP":
            return original_backup(app, paths, target, control=control, progress=progress, plan_name=plan_name)
        account_id = str(target.get("cloud_account_id") or "")
        if not account_id:
            raise RuntimeError("HiDrive-Ziel enthält keine Konto-ID.")
        ok, msg = test_hidrive_sftp(app.store, account_id)
        if not ok:
            raise RuntimeError(msg)
        with tempfile.TemporaryDirectory(prefix="pbv-hidrive-") as tmp:
            staging = {"id": "hidrive-stage", "name": target.get("name"), "path": tmp, "kind": "HIDRIVE-STAGE"}
            result = original_backup(app, paths, staging, control=control, progress=progress, plan_name=plan_name)
            vault = Path(tmp) / storage_module.VAULT_DIR
            files = [p for p in vault.rglob("*") if p.is_file()]
            total = sum(p.stat().st_size for p in files)
            done = 0
            for p in files:
                if control:
                    control.check()
                rel = p.relative_to(Path(tmp)).as_posix()
                size = p.stat().st_size
                def cb(sent, _total, base=done):
                    if progress:
                        metrics={"phase":"HiDrive SFTP Upload","bytes_done":base+sent,"bytes_total":total,"transfer_bytes":base+sent,"current_file":p.name}
                        try: progress(0, len(files), f"HiDrive: {p.name}", metrics)
                        except TypeError: progress(0, len(files), f"HiDrive: {p.name}")
                upload_file(app.store, account_id, p, rel, progress=cb)
                done += size
            result["target"] = target.get("path")
            result["cloud_method"] = "SFTP"
            result["cloud_account_id"] = account_id
            return result

    cloud_module.test_cloud_account = test_cloud_account
    cloud_module.filesystem_capable_method = filesystem_capable_method
    cloud_module.ensure_filesystem_bridge = ensure_filesystem_bridge
    storage_module.filesystem_backup = filesystem_backup
    cloud_module._hidrive_sftp_v192 = True
