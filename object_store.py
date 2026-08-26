from __future__ import annotations
from dataclasses import dataclass, field
import threading

from status_bus import activity, state


class ObjectStoreError(RuntimeError):
    pass


@dataclass
class B2Store:
    bucket: str
    endpoint_url: str
    region: str
    prefix: str
    access_key_id: str
    application_key: str
    _cached_client: object | None = field(default=None, init=False, repr=False)
    _client_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _client(self):
        try:
            import boto3
            from botocore.config import Config
        except Exception as e:
            raise ObjectStoreError("Backblaze-B2-Unterstützung fehlt. Bitte STARTEN.bat einmal ausführen, damit boto3 installiert wird.") from e
        if self._cached_client is not None:
            return self._cached_client
        with self._client_lock:
            if self._cached_client is None:
                self._cached_client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint_url.rstrip("/"),
                    region_name=(self.region or None),
                    aws_access_key_id=self.access_key_id,
                    aws_secret_access_key=self.application_key,
                    config=Config(
                        signature_version="s3v4",
                        retries={"max_attempts": 4, "mode": "standard"},
                        max_pool_connections=16,
                        connect_timeout=12,
                        read_timeout=120,
                    ),
                )
            return self._cached_client

    def object_key(self, sha256: str, chunk_no: int) -> str:
        prefix = (self.prefix or "pc-backup-vault").strip("/")
        return f"{prefix}/chunks/{sha256[:2]}/{sha256}/{chunk_no:06d}.bin"

    def ping(self) -> tuple[bool, str]:
        """Leichter Verbindungstest ohne Schreibzugriff."""
        try:
            prefix = (self.prefix or "pc-backup-vault").strip("/") + "/"
            activity("b2", "list", prefix)
            self._client().list_objects_v2(Bucket=self.bucket, Prefix=prefix, MaxKeys=1)
            state("b2", "ok", f"Bucket {self.bucket} erreichbar")
            return True, f"Backblaze B2 – Bucket '{self.bucket}' erreichbar"
        except Exception as e:
            state("b2", "error", str(e))
            return False, str(e)

    def test(self) -> tuple[bool, str]:
        """Prüft den konfigurierten Prefix und die für Backup nötigen Rechte.

        Backblaze verweigert ListObjectsV2 bei einem namePrefix-beschränkten
        App-Key, wenn der Request keinen mindestens ebenso restriktiven Prefix
        enthält. Deshalb wird ausschließlich innerhalb unseres Vault-Prefixes
        getestet. Zusätzlich wird ein winziges Probeobjekt geschrieben,
        gelesen und wieder gelöscht, damit Backup UND Restore geprüft sind.
        """
        import hashlib
        import os
        import time
        try:
            client = self._client()
            prefix = (self.prefix or "pc-backup-vault").strip("/") + "/"
            activity("b2", "list", prefix)
            client.list_objects_v2(Bucket=self.bucket, Prefix=prefix, MaxKeys=1)

            probe = os.urandom(32)
            probe_key = f"{prefix}_health/connection-{int(time.time() * 1000)}.bin"
            expected = hashlib.sha256(probe).hexdigest()
            activity("b2", "write", probe_key)
            client.put_object(
                Bucket=self.bucket,
                Key=probe_key,
                Body=probe,
                ContentType="application/octet-stream",
                Metadata={"purpose": "pc-backup-vault-connection-test", "sha256": expected},
            )
            activity("b2", "read", probe_key)
            response = client.get_object(Bucket=self.bucket, Key=probe_key)
            actual = response["Body"].read()
            if hashlib.sha256(actual).hexdigest() != expected:
                raise ObjectStoreError("B2-Verbindungstest: gelesene Testdaten stimmen nicht mit den geschriebenen Daten überein.")
            activity("b2", "delete", probe_key)
            client.delete_object(Bucket=self.bucket, Key=probe_key)
            state("b2", "ok", f"Bucket {self.bucket} vollständig geprüft")
            return True, f"Backblaze B2 – Bucket '{self.bucket}' vollständig OK (Liste/Schreiben/Lesen/Löschen)"
        except Exception as e:
            state("b2", "error", str(e))
            return False, str(e)


    def list_prefix_sizes(self) -> dict[str, int]:
        """Return object sizes below the configured vault prefix with paginated listing."""
        try:
            client = self._client()
            prefix = (self.prefix or "pc-backup-vault").strip("/") + "/"
            token = None
            out: dict[str, int] = {}
            while True:
                kwargs = {"Bucket": self.bucket, "Prefix": prefix, "MaxKeys": 1000}
                if token:
                    kwargs["ContinuationToken"] = token
                activity("b2", "list", prefix)
                response = client.list_objects_v2(**kwargs)
                for item in response.get("Contents", []) or []:
                    key = str(item.get("Key") or "")
                    if key:
                        out[key] = int(item.get("Size") or 0)
                if not response.get("IsTruncated"):
                    break
                token = response.get("NextContinuationToken")
                if not token:
                    break
            return out
        except Exception as e:
            raise ObjectStoreError(f"B2-Objektliste fehlgeschlagen: {e}") from e

    def head(self, key: str) -> dict:
        try:
            activity("b2", "head", key)
            response = self._client().head_object(Bucket=self.bucket, Key=key)
            return {
                "size": int(response.get("ContentLength") or 0),
                "etag": str(response.get("ETag") or "").strip('"'),
                "metadata": dict(response.get("Metadata") or {}),
            }
        except Exception as e:
            raise ObjectStoreError(f"B2-Objektprüfung fehlgeschlagen: {e}") from e

    def put(self, key: str, data: bytes, cipher_sha256: str) -> str:
        try:
            activity("b2", "write", key)
            response = self._client().put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType="application/octet-stream",
                Metadata={"cipher-sha256": cipher_sha256},
            )
            return str(response.get("ETag") or "").strip('"')
        except Exception as e:
            raise ObjectStoreError(f"B2-Upload fehlgeschlagen: {e}") from e

    def get(self, key: str) -> bytes:
        try:
            activity("b2", "read", key)
            response = self._client().get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except Exception as e:
            raise ObjectStoreError(f"B2-Download fehlgeschlagen: {e}") from e

    def delete(self, key: str):
        try:
            activity("b2", "delete", key)
            self._client().delete_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            raise ObjectStoreError(f"B2-Löschen fehlgeschlagen: {e}") from e


def make_b2_store(config: dict | None) -> B2Store | None:
    cfg = dict(config or {})
    if not cfg.get("configured"):
        return None
    return B2Store(
        bucket=str(cfg.get("bucket") or "").strip(),
        endpoint_url=str(cfg.get("endpoint_url") or "").strip(),
        region=str(cfg.get("region") or "").strip(),
        prefix=str(cfg.get("prefix") or "pc-backup-vault").strip(),
        access_key_id=str(cfg.get("access_key_id") or "").strip(),
        application_key=str(cfg.get("application_key") or "").strip(),
    )
