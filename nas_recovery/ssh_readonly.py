from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class UnsafeSshCommand(ValueError):
    pass


# Exact commands only. No arbitrary shell input is accepted from the UI.
READ_ONLY_COMMANDS: tuple[tuple[str, str], ...] = (
    ("System", "uname -a"),
    ("RAID-Status", "cat /proc/mdstat"),
    ("Mounts", "mount"),
    ("Speicherbelegung", "df -h"),
    ("Partitionen", "cat /proc/partitions"),
    ("Dateisystem-IDs", "blkid"),
    ("mdadm Scan", "mdadm --detail --scan"),
)

_ALLOWED = frozenset(command for _, command in READ_ONLY_COMMANDS)


@dataclass(frozen=True)
class SshCommandResult:
    title: str
    command: str
    stdout: str
    stderr: str
    exit_status: int


@dataclass(frozen=True)
class SshReadOnlyReport:
    host: str
    port: int
    username: str
    host_key_type: str
    host_key_fingerprint: str
    results: tuple[SshCommandResult, ...]


def validate_read_only_command(command: str) -> str:
    clean = str(command or "").strip()
    if clean not in _ALLOWED:
        raise UnsafeSshCommand("SSH-Kommando ist nicht in der festen Read-only-Whitelist freigegeben.")
    return clean


def _fingerprint_sha256(key) -> str:
    import base64
    import hashlib

    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


class _SessionOnlyHostKeyPolicy:
    """Accept an unknown host key for this one diagnostic session only.

    The fingerprint is surfaced to the UI/report. Nothing is written to known_hosts.
    """

    def __init__(self):
        self.key_type = ""
        self.fingerprint = ""

    def missing_host_key(self, client, hostname, key):
        self.key_type = key.get_name()
        self.fingerprint = _fingerprint_sha256(key)
        client._host_keys.add(hostname, key.get_name(), key)


class SshReadOnlyDiagnostics:
    """Password-in-memory SSH diagnostics with an exact read-only command whitelist."""

    def __init__(self, connect_timeout: float = 6.0, command_timeout: float = 8.0):
        self.connect_timeout = float(connect_timeout)
        self.command_timeout = float(command_timeout)

    def run(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 22,
        commands: Iterable[tuple[str, str]] = READ_ONLY_COMMANDS,
        allow_legacy_dss: bool = False,
    ) -> SshReadOnlyReport:
        import paramiko

        clean_host = str(host or "").strip()
        clean_user = str(username or "").strip()
        if not clean_host:
            raise ValueError("SSH-Host fehlt.")
        if not clean_user:
            raise ValueError("SSH-Benutzername fehlt.")
        if not password:
            raise ValueError("SSH-Passwort fehlt.")

        policy = _SessionOnlyHostKeyPolicy()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(policy)

        disabled_algorithms = None
        if allow_legacy_dss:
            # Paramiko versions that still support ssh-dss may use it for this
            # single legacy session. Nothing is enabled globally.
            disabled_algorithms = {}

        try:
            client.connect(
                hostname=clean_host,
                port=int(port),
                username=clean_user,
                password=password,
                timeout=self.connect_timeout,
                banner_timeout=self.connect_timeout,
                auth_timeout=self.connect_timeout,
                look_for_keys=False,
                allow_agent=False,
                disabled_algorithms=disabled_algorithms,
            )
            results: list[SshCommandResult] = []
            for title, raw_command in tuple(commands):
                command = validate_read_only_command(raw_command)
                stdin, stdout, stderr = client.exec_command(command, timeout=self.command_timeout)
                try:
                    stdin.close()
                except Exception:
                    pass
                out = stdout.read().decode("utf-8", errors="replace")
                err = stderr.read().decode("utf-8", errors="replace")
                status = int(stdout.channel.recv_exit_status())
                results.append(SshCommandResult(str(title), command, out, err, status))

            transport = client.get_transport()
            remote_key = transport.get_remote_server_key() if transport else None
            key_type = policy.key_type or (remote_key.get_name() if remote_key else "unbekannt")
            fingerprint = policy.fingerprint or (_fingerprint_sha256(remote_key) if remote_key else "unbekannt")
            return SshReadOnlyReport(
                host=clean_host,
                port=int(port),
                username=clean_user,
                host_key_type=key_type,
                host_key_fingerprint=fingerprint,
                results=tuple(results),
            )
        finally:
            client.close()
