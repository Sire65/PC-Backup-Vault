from __future__ import annotations
import base64, hashlib, json, os, textwrap
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from PIL import Image, ImageDraw, ImageFont
import qrcode

BUNDLE_MAGIC = "PC_BACKUP_VAULT_RECOVERY_BUNDLE_V1"


def _derive_key(password: str, salt: bytes) -> bytes:
    if len(password) < 12:
        raise ValueError("Das Notfall-Passwort muss mindestens 12 Zeichen lang sein.")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode("utf-8"))


def recovery_fingerprint(master_key_b64: str) -> str:
    raw = base64.urlsafe_b64decode(master_key_b64.encode("ascii"))
    return hashlib.sha256(raw).hexdigest().upper()


def build_recovery_payload(store) -> dict:
    master_key = store.get_master_key()
    if not master_key:
        raise ValueError("Kein Recovery-Key vorhanden.")
    profiles = []
    dsns = {}
    for p in store.data.get("profiles", []):
        q = dict(p)
        profiles.append(q)
        dsn = store.get_dsn(p.get("id"))
        if dsn:
            dsns[p.get("id")] = dsn
    access, appkey = store.get_b2_credentials()
    return {
        "format": BUNDLE_MAGIC,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "app_version": store.data.get("app_version"),
        "active_profile_id": store.data.get("active_profile_id"),
        "profiles": profiles,
        "profile_dsns": dsns,
        "b2": dict(store.data.get("b2") or {}),
        "b2_access_key_id": access or "",
        "b2_application_key": appkey or "",
        "master_key": master_key,
        "recovery_key_fingerprint": recovery_fingerprint(master_key),
    }


def export_encrypted_bundle(store, out_path: str | Path, password: str) -> Path:
    payload = build_recovery_payload(store)
    plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(password, salt)
    cipher = AESGCM(key).encrypt(nonce, plain, BUNDLE_MAGIC.encode("ascii"))
    envelope = {
        "format": BUNDLE_MAGIC,
        "kdf": "scrypt-n32768-r8-p1",
        "salt": base64.urlsafe_b64encode(salt).decode("ascii"),
        "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
        "ciphertext": base64.urlsafe_b64encode(cipher).decode("ascii"),
    }
    out = Path(out_path)
    out.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    return out


def import_encrypted_bundle(store, bundle_path: str | Path, password: str) -> dict:
    env = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    if env.get("format") != BUNDLE_MAGIC:
        raise ValueError("Unbekanntes Notfall-Paket.")
    salt = base64.urlsafe_b64decode(env["salt"])
    nonce = base64.urlsafe_b64decode(env["nonce"])
    cipher = base64.urlsafe_b64decode(env["ciphertext"])
    key = _derive_key(password, salt)
    try:
        plain = AESGCM(key).decrypt(nonce, cipher, BUNDLE_MAGIC.encode("ascii"))
    except Exception as exc:
        raise ValueError("Notfall-Passwort falsch oder Paket beschädigt.") from exc
    payload = json.loads(plain.decode("utf-8"))
    if payload.get("format") != BUNDLE_MAGIC:
        raise ValueError("Ungültiger Paketinhalt.")

    profiles = payload.get("profiles") or []
    if profiles:
        store.data["profiles"] = profiles
        store.data["active_profile_id"] = payload.get("active_profile_id") or profiles[0].get("id")
    for pid, dsn in (payload.get("profile_dsns") or {}).items():
        if dsn:
            store.set_dsn(pid, dsn)
    if payload.get("master_key"):
        store.set_master_key(payload["master_key"])
    b2 = payload.get("b2") or {}
    if b2:
        store.data["b2"] = b2
    if payload.get("b2_access_key_id") or payload.get("b2_application_key"):
        store.set_b2_credentials(payload.get("b2_access_key_id", ""), payload.get("b2_application_key", ""))
    store.data["recovery_key_exported"] = True
    store.data["last_recovery_export"] = datetime.now().isoformat(timespec="seconds")
    store.save()
    return payload


def _font(size: int, bold: bool = False):
    candidates = [
        "C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def export_safe_pass_png(store, out_path: str | Path, bundle_filename: str = "") -> Path:
    master = store.get_master_key()
    if not master:
        raise ValueError("Kein Recovery-Key vorhanden.")
    p = store.get_profile() or {}
    b2 = store.data.get("b2") or {}
    fp = recovery_fingerprint(master)
    created = datetime.now().strftime("%d.%m.%Y %H:%M")

    safe_payload = {
        "type": "PCBackupVaultSafePass",
        "version": 1,
        "project": p.get("project_ref", ""),
        "database": p.get("database", ""),
        "b2_bucket": b2.get("bucket", ""),
        "b2_endpoint": b2.get("endpoint_url", ""),
        "b2_region": b2.get("region", ""),
        "b2_prefix": b2.get("prefix", ""),
        "fingerprint": fp[:24],
    }
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=5, border=3)
    qr.add_data(json.dumps(safe_payload, separators=(",", ":")))
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_img = qr_img.resize((290, 290))

    w, h = 1180, 760
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    title = _font(36, True); head = _font(22, True); body = _font(19, False); small = _font(15, False)
    d.text((48, 38), "PC Backup Vault – Notfall-Pass", font=title, fill="black")
    d.text((48, 90), "Dieser Pass enthält KEINE geheimen Zugangsdaten.", font=head, fill="black")
    d.rectangle((46, 130, 740, 548), outline="black", width=2)

    rows = [
        ("Erstellt", created),
        ("Neon-Projekt", str(p.get("project_ref", "–"))),
        ("Datenbank", str(p.get("database", "–"))),
        ("B2-Bucket", str(b2.get("bucket", "–"))),
        ("B2-Endpoint", str(b2.get("endpoint_url", "–"))),
        ("B2-Region", str(b2.get("region", "–"))),
        ("B2-Prefix", str(b2.get("prefix", "–"))),
        ("Recovery-Fingerprint", fp[:24]),
        ("Notfall-Paket", bundle_filename or "separat aufbewahren"),
    ]
    y = 155
    for label, value in rows:
        d.text((70, y), f"{label}:", font=head, fill="black")
        wrapped = textwrap.wrap(value or "–", width=43) or ["–"]
        for j, line in enumerate(wrapped[:2]):
            d.text((315, y + j * 24), line, font=body, fill="black")
        y += 42 if len(wrapped) == 1 else 62

    img.paste(qr_img, (820, 145))
    d.text((802, 445), "QR: sichere Wiederherstellungs-Metadaten", font=small, fill="black")
    d.text((802, 470), "Keine Passwörter / Schlüssel im QR.", font=small, fill="black")

    instructions = [
        "Notfall-Wiederherstellung:",
        "1. PC Backup Vault auf neuem PC installieren.",
        "2. Verschlüsseltes .pvr-Notfall-Paket importieren.",
        "3. Eigenes Notfall-Passwort eingeben.",
        "4. Neon- und B2-Verbindung prüfen.",
        "5. Backup-Explorer öffnen und Dateien/Ordner wiederherstellen.",
    ]
    y = 585
    for i, line in enumerate(instructions):
        d.text((48, y), line, font=head if i == 0 else body, fill="black")
        y += 31
    out = Path(out_path)
    img.save(out, format="PNG", optimize=True)
    return out


def export_readme(out_path: str | Path, bundle_filename: str, pass_filename: str) -> Path:
    text = f"""PC BACKUP VAULT – NOTFALLWIEDERHERSTELLUNG\n\n1. PC Backup Vault installieren.\n2. '{bundle_filename}' bereithalten.\n3. Im Programm: Einstellungen > Sicherheit / Core > Notfall-Paket importieren.\n4. Das persönliche Notfall-Passwort eingeben.\n5. Datenbank- und B2-Verbindung testen.\n6. Backup-Explorer öffnen und Dateien/Ordner wiederherstellen.\n\n'{pass_filename}' ist der sichere Backup-Pass für Handy/Print und enthält keine Passwörter.\nDas .pvr-Paket ist verschlüsselt und darf auf Handy, USB-Stick oder in einem anderen sicheren Speicher liegen.\nDas Notfall-Passwort wird NICHT im Paket und NICHT im Programm gespeichert.\n"""
    out = Path(out_path)
    out.write_text(text, encoding="utf-8")
    return out
