from __future__ import annotations

import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class LegacySshProfile:
    host: str
    port: int
    banner: str
    looks_legacy: bool
    dss_runtime_available: bool
    recommendation: str


def classify_ssh_banner(banner: str) -> bool:
    """Classify whether an SSH banner looks old enough to need legacy review.

    This is intentionally conservative and does not enable weak algorithms.
    It only decides whether the operator should see a compatibility warning.
    """
    text = str(banner or "").strip().lower()
    if not text:
        return False
    legacy_markers = (
        "openssh_3.",
        "openssh_4.",
        "openssh_5.",
        "dropbear_0.",
        "dropbear_2011",
        "dropbear_2012",
        "dropbear_2013",
        "dropbear_2014",
        "dropbear_2015",
    )
    return any(marker in text for marker in legacy_markers)


def runtime_supports_ssh_dss() -> bool:
    """Report support only; never modifies Paramiko/global crypto policy."""
    try:
        import paramiko

        preferred = tuple(getattr(paramiko.Transport, "_preferred_keys", ()) or ())
        return "ssh-dss" in preferred
    except Exception:
        return False


class LegacySshProbe:
    """Credential-free SSH banner probe for old NAS compatibility assessment.

    The probe performs only a TCP connect and reads the server identification line.
    It never authenticates, executes commands, or changes algorithm policy.
    """

    def __init__(self, timeout: float = 4.0, max_banner_bytes: int = 512):
        self.timeout = float(timeout)
        self.max_banner_bytes = int(max_banner_bytes)

    def read_banner(self, host: str, port: int = 22) -> str:
        clean_host = str(host or "").strip()
        if not clean_host:
            raise ValueError("SSH-Host fehlt.")
        with socket.create_connection((clean_host, int(port)), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            data = b""
            while len(data) < self.max_banner_bytes and b"\n" not in data:
                chunk = sock.recv(min(128, self.max_banner_bytes - len(data)))
                if not chunk:
                    break
                data += chunk
        banner = data.splitlines()[0].decode("ascii", errors="replace").strip() if data else ""
        if not banner.startswith("SSH-"):
            raise ValueError("Port 22 antwortet, aber es wurde kein gültiger SSH-Banner erkannt.")
        return banner

    def profile(self, host: str, port: int = 22) -> LegacySshProfile:
        banner = self.read_banner(host, port=port)
        legacy = classify_ssh_banner(banner)
        dss_available = runtime_supports_ssh_dss()
        if legacy and not dss_available:
            recommendation = (
                "Altes SSH-System erkannt. Die aktuelle sichere Laufzeit bietet ssh-dss nicht an. "
                "Legacy-Verbindung bleibt gesperrt; zuerst gerätespezifischen, isolierten Kompatibilitätsweg prüfen."
            )
        elif legacy:
            recommendation = (
                "Altes SSH-System erkannt. Legacy-Verbindung darf nur gerätespezifisch, isoliert und read-only freigegeben werden."
            )
        else:
            recommendation = "Kein eindeutiger Legacy-Hinweis im SSH-Banner; Standard-Read-only-SSH verwenden."
        return LegacySshProfile(
            host=str(host).strip(),
            port=int(port),
            banner=banner,
            looks_legacy=legacy,
            dss_runtime_available=dss_available,
            recommendation=recommendation,
        )
