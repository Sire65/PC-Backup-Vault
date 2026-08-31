from __future__ import annotations

import ipaddress
import socket
import ssl
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class PortCheck:
    port: int
    name: str
    open: bool
    detail: str


@dataclass(frozen=True)
class NetworkReport:
    host: str
    resolved_ip: str
    ports: tuple[PortCheck, ...]


def normalize_host(value: str) -> str:
    host = str(value or "").strip()
    if not host:
        raise ValueError("Bitte Hostname oder IP-Adresse eingeben.")
    if "://" in host:
        raise ValueError("Bitte nur Hostname oder IP-Adresse eingeben, keine URL.")
    if any(ch.isspace() for ch in host):
        raise ValueError("Hostname/IP darf keine Leerzeichen enthalten.")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    labels = host.rstrip(".").split(".")
    if any(not label or len(label) > 63 for label in labels):
        raise ValueError("Hostname ist ungültig.")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")
    if any(any(ch not in allowed for ch in label) or label.startswith("-") or label.endswith("-") for label in labels):
        raise ValueError("Hostname ist ungültig.")
    return host.rstrip(".")


class NasNetworkDiagnostics:
    """Read-only connectivity diagnostics. No configuration is changed on the NAS."""

    DEFAULT_PORTS = (
        (80, "HTTP"),
        (443, "HTTPS"),
        (445, "SMB"),
        (22, "SSH"),
    )

    def resolve(self, host: str) -> str:
        clean = normalize_host(host)
        return socket.gethostbyname(clean)

    def check_port(self, host: str, port: int, timeout: float = 1.5) -> PortCheck:
        clean = normalize_host(host)
        name = next((label for number, label in self.DEFAULT_PORTS if number == int(port)), str(port))
        try:
            with socket.create_connection((clean, int(port)), timeout=timeout):
                return PortCheck(int(port), name, True, "erreichbar")
        except OSError as exc:
            return PortCheck(int(port), name, False, str(exc))

    def basic_report(self, host: str) -> NetworkReport:
        clean = normalize_host(host)
        resolved = self.resolve(clean)
        ports = tuple(self.check_port(clean, port) for port, _ in self.DEFAULT_PORTS)
        return NetworkReport(clean, resolved, ports)

    def http_probe(self, host: str, https: bool = False, timeout: float = 3.0) -> tuple[int, str]:
        clean = normalize_host(host)
        scheme = "https" if https else "http"
        url = f"{scheme}://{clean}/"
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "PC-Backup-Vault-NAS-Diagnostics"})
        context = ssl.create_default_context() if https else None
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return int(getattr(response, "status", 200)), str(response.headers.get("Server") or "")
        except urllib.error.HTTPError as exc:
            # An HTTP status still proves the web endpoint answered.
            return int(exc.code), str(exc.headers.get("Server") or "")
