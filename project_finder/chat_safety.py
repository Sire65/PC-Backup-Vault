from __future__ import annotations

import re
from pathlib import Path

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s()./-]{7,}\d)(?!\w)")
TOKEN_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:ghp|github_pat|glpat)-?[A-Za-z0-9_\-]{16,}\b", re.I),
    re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
]
ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b(api[_ -]?key|secret|password|passwort|token|authorization|bearer)\b\s*[:=]\s*([^\s,;]+)"
)
WINDOWS_USER_RE = re.compile(r"(?i)\b([A-Z]:\\Users\\)([^\\/]+)")
UNIX_HOME_RE = re.compile(r"(?i)(/home/)([^/\s]+)")


def redact_text(text: str) -> str:
    value = str(text or "")
    value = EMAIL_RE.sub("[EMAIL]", value)
    value = PHONE_RE.sub("[TELEFON]", value)
    for pattern in TOKEN_PATTERNS:
        value = pattern.sub("[SECRET]", value)
    value = ASSIGNMENT_SECRET_RE.sub(lambda m: f"{m.group(1)}=[SECRET]", value)
    value = WINDOWS_USER_RE.sub(r"\1[USER]", value)
    value = UNIX_HOME_RE.sub(r"\1[USER]", value)
    return value


def safe_source_label(path: str, anonymize: bool = True) -> str:
    if not path:
        return ""
    p = Path(path)
    return p.name if anonymize else str(p)


def sanitize_finding(row: dict) -> dict:
    clean = dict(row)
    clean["text"] = redact_text(str(clean.get("text") or ""))
    clean["title"] = redact_text(str(clean.get("title") or ""))
    return clean
