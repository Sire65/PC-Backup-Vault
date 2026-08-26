from __future__ import annotations
import base64, hashlib, hmac, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "enc:v1:"

def create_key_b64() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")

def key_bytes(key_b64: str) -> bytes:
    raw = base64.urlsafe_b64decode(key_b64.encode("ascii"))
    if len(raw) != 32: raise ValueError("Recovery key is not 32 bytes.")
    return raw

def encrypt_bytes(key_b64: str, data: bytes, aad: bytes=b""):
    nonce = os.urandom(12)
    return nonce, AESGCM(key_bytes(key_b64)).encrypt(nonce, data, aad)

def decrypt_bytes(key_b64: str, nonce: bytes, cipher: bytes, aad: bytes=b""):
    return AESGCM(key_bytes(key_b64)).decrypt(nonce, cipher, aad)

def encrypt_text(key_b64: str, text: str) -> str:
    nonce, cipher = encrypt_bytes(key_b64, text.encode("utf-8"), b"meta")
    return PREFIX + base64.urlsafe_b64encode(nonce + cipher).decode("ascii")

def decrypt_text(key_b64: str, value: str) -> str:
    if not value.startswith(PREFIX): return value
    raw = base64.urlsafe_b64decode(value[len(PREFIX):].encode("ascii"))
    return decrypt_bytes(key_b64, raw[:12], raw[12:], b"meta").decode("utf-8")

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def logical_path_hmac(key_b64: str, path_text: str) -> str:
    normalized = path_text.replace("/", "\\").strip().lower().encode("utf-8")
    return hmac.new(key_bytes(key_b64), normalized, hashlib.sha256).hexdigest()
