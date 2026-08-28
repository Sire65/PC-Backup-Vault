from __future__ import annotations

import re

# Canonical names are deliberately stable: all evidence sources must converge on
# the same key before Git/local/chat reconciliation is allowed to influence status.
ALIASES = {
    "DP2 / Dienstplan": ("dp2", "dienstplan", "kc dp", "kc dp2"),
    "PC Backup Vault": ("pc backup vault", "pc-backup-vault", "backup vault"),
    "KC Marktkasse": ("kc marktkasse", "marktkasse", "bilderkasse", "kasse"),
    "KC Verwaltung": ("kc verwaltung", "kc-verwaltung", "verwaltung"),
    "KC Futura": ("kc futura", "kc-futura-academy", "futura academy", "futura"),
    "KC Communication": ("kc communication", "kc-communication", "communication"),
    "KC Leitstand": ("kc leitstand", "kc-leitstand", "leitstand"),
    "KC Money Butler": ("kc money butler", "kc-money-butler", "money butler"),
    "KC Manager": ("kc manager", "kc-manager"),
    "KC Spiele": ("kc spiele", "küchen-detektiv", "kuechen-detektiv"),
    "KC Website": ("kc website", "kc werbewebsite", "kc-werbewebsite"),
}


def _key(value: str) -> str:
    value = value.casefold().replace("_", " ").replace("/", " ")
    value = re.sub(r"[^a-z0-9äöüß]+", " ", value)
    return " ".join(value.split())


_LOOKUP = {}
for canonical, aliases in ALIASES.items():
    for name in (canonical, *aliases):
        _LOOKUP[_key(name)] = canonical


def canonical_project(value: str | None) -> str:
    raw = " ".join(str(value or "").split())
    if not raw:
        return "Unbekannt"
    key = _key(raw)
    if key in _LOOKUP:
        return _LOOKUP[key]
    # Repository-shaped values may include owner/name.
    tail = raw.rsplit("/", 1)[-1]
    return _LOOKUP.get(_key(tail), raw)
