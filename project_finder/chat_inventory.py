from __future__ import annotations

import json
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .chat_safety import redact_text, safe_source_label

PROJECT_PATTERNS = {
    "DP2 / Dienstplan": [r"\bdp2\b", r"dienstplan", r"wunschplan", r"sollplan", r"istplan"],
    "PC Backup Vault": [r"backup vault", r"pc[- ]?backup", r"backup-programm", r"projekt[- ]?finder"],
    "KC Marktkasse / Kasse": [r"marktkasse", r"bilderkasse", r"\bkasse\b", r"pc manager"],
    "KC Verwaltung": [r"kc verwaltung", r"verwaltung"],
    "KC Futura": [r"kc futura", r"futura academy", r"futura"],
    "KC Communication": [r"kc communication", r"kommunikation", r"communication"],
    "KC Leitstand": [r"leitstand", r"infrastructure control center", r"kicc"],
    "KC Money Butler": [r"money butler", r"kassenwart butler"],
    "KC Spiele": [r"küchen[- ]?detektiv", r"kreuzworträtsel", r"tic tac toe", r"spiel"],
    "KC Website": [r"werbewebsite", r"website", r"internetseite"],
}

IDEA_PATTERNS = re.compile(r"\b(idee|wunsch|soll|muss|können wir|später|noch einbauen|vorsehen|erweitern)\b", re.I)
DONE_PATTERNS = re.compile(r"\b(fertig|eingebaut|umgesetzt|erledigt|funktioniert|geht jetzt|gelöst)\b", re.I)
OPEN_PATTERNS = re.compile(r"\b(offen|fehlt|geht nicht|funktioniert nicht|problem|fehler|rückschritt|noch nicht)\b", re.I)
REJECTED_PATTERNS = re.compile(r"\b(verworfen|nicht mehr|raus damit|nicht verwenden|ersetzen durch)\b", re.I)
DEV_PATTERNS = re.compile(r"\b(github|repo|repository|commit|branch|build|version|zip|rar|programm|code|testen|tüv|regression|supabase|neon|b2)\b", re.I)


@dataclass
class ChatMessage:
    message_id: str
    role: str
    timestamp: str | None
    text: str


@dataclass
class ChatFinding:
    conversation_id: str
    message_id: str
    role: str
    title: str
    timestamp: str | None
    project: str
    kind: str
    text: str
    evidence_strength: str


def _iter_text(value) -> Iterable[str]:
    if isinstance(value, str):
        if value.strip():
            yield value.strip()
    elif isinstance(value, list):
        for item in value:
            yield from _iter_text(item)
    elif isinstance(value, dict):
        for key in ("text", "content", "parts", "message"):
            if key in value:
                yield from _iter_text(value[key])


def _conversation_messages(conv: dict) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    mapping = conv.get("mapping")
    if isinstance(mapping, dict):
        for node_id, node in mapping.items():
            if not isinstance(node, dict):
                continue
            message = node.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            texts = list(_iter_text(content))
            author = message.get("author") if isinstance(message.get("author"), dict) else {}
            role = str(author.get("role") or message.get("role") or "unknown")
            timestamp = message.get("create_time") or message.get("update_time")
            mid = str(message.get("id") or node_id or "")
            for text in texts:
                out.append(ChatMessage(mid, role, str(timestamp) if timestamp is not None else None, text))
    for key in ("messages", "chat_messages"):
        raw = conv.get(key)
        if isinstance(raw, list):
            for idx, item in enumerate(raw):
                if isinstance(item, dict):
                    texts = list(_iter_text(item))
                    role = str(item.get("role") or (item.get("author") or {}).get("role") if isinstance(item.get("author"), dict) else item.get("role") or "unknown")
                    timestamp = item.get("create_time") or item.get("timestamp") or item.get("update_time")
                    mid = str(item.get("id") or f"{key}-{idx}")
                    for text in texts:
                        out.append(ChatMessage(mid, role, str(timestamp) if timestamp is not None else None, text))
                else:
                    for text in _iter_text(item):
                        out.append(ChatMessage(f"{key}-{idx}", "unknown", None, text))
    return [x for x in out if x.text]


def _project_scores(text: str) -> dict[str, int]:
    lower = text.lower()
    scores: dict[str, int] = {}
    for project, patterns in PROJECT_PATTERNS.items():
        score = sum(1 for p in patterns if re.search(p, lower, re.I))
        if score:
            scores[project] = score
    return scores


def classify_conversation(title: str, messages: list[ChatMessage] | list[str]) -> tuple[str, int]:
    texts = [m.text if isinstance(m, ChatMessage) else str(m) for m in messages[:200]]
    corpus = (title + "\n" + "\n".join(texts)).lower()
    project_score = sum(_project_scores(corpus).values())
    dev_score = len(DEV_PATTERNS.findall(corpus))
    score = project_score * 4 + min(dev_score, 20)
    if score >= 12:
        return "DEVELOPMENT", score
    if score >= 5:
        return "POSSIBLE_DEVELOPMENT", score
    return "OTHER", score


def analyze_conversation(conv: dict, *, redact: bool = True) -> dict:
    cid = str(conv.get("id") or conv.get("conversation_id") or "unknown")
    raw_title = str(conv.get("title") or "Ohne Titel")
    title = redact_text(raw_title) if redact else raw_title
    conv_timestamp = conv.get("create_time") or conv.get("update_time")
    messages = _conversation_messages(conv)
    classification, relevance_score = classify_conversation(raw_title, messages)

    findings: list[ChatFinding] = []
    kinds: list[tuple[str, re.Pattern, str]] = [
        ("OPEN_OR_ERROR", OPEN_PATTERNS, "chat-claim"),
        ("IMPLEMENTATION_CLAIM", DONE_PATTERNS, "chat-claim-unverified"),
        ("IDEA_OR_REQUIREMENT", IDEA_PATTERNS, "chat-requirement"),
        ("REJECTED_OR_REPLACED", REJECTED_PATTERNS, "chat-decision"),
    ]
    for msg in messages:
        projects = _project_scores(raw_title + "\n" + msg.text)
        if not projects:
            continue
        project = max(projects, key=projects.get)
        emitted: set[str] = set()
        for kind, pattern, strength in kinds:
            if kind not in emitted and pattern.search(msg.text):
                findings.append(ChatFinding(
                    cid, msg.message_id, msg.role, title,
                    msg.timestamp or (str(conv_timestamp) if conv_timestamp is not None else None),
                    project, kind, redact_text(msg.text[:2000]) if redact else msg.text[:2000], strength,
                ))
                emitted.add(kind)

    return {
        "conversation_id": cid,
        "title": title,
        "timestamp": conv_timestamp,
        "classification": classification,
        "relevance_score": relevance_score,
        "message_count": len(messages),
        "findings": [asdict(x) for x in findings],
    }


def _load_json_from_zip(path: Path) -> list[dict]:
    conversations: list[dict] = []
    with zipfile.ZipFile(path, "r") as zf:
        candidates = [n for n in zf.namelist() if re.search(r"(^|/)conversations(?:-\d+)?\.json$", n, re.I)]
        for name in candidates:
            with zf.open(name) as fh:
                payload = json.load(fh)
                if isinstance(payload, list):
                    conversations.extend(x for x in payload if isinstance(x, dict))
                elif isinstance(payload, dict):
                    data = payload.get("conversations")
                    if isinstance(data, list):
                        conversations.extend(x for x in data if isinstance(x, dict))
    return conversations


def load_export(path: str) -> list[dict]:
    p = Path(path)
    if p.suffix.lower() == ".zip":
        return _load_json_from_zip(p)
    payload = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("conversations"), list):
        return [x for x in payload["conversations"] if isinstance(x, dict)]
    raise ValueError("Kein unterstützter ChatGPT-Export erkannt.")


def inventory_export(path: str, include_other: bool = False, *, anonymize_source: bool = True, redact: bool = True) -> dict:
    conversations = load_export(path)
    analyzed = [analyze_conversation(c, redact=redact) for c in conversations]
    selected = [x for x in analyzed if include_other or x["classification"] != "OTHER"]
    findings = [f for x in selected for f in x["findings"]]
    by_project: dict[str, dict[str, int]] = {}
    for f in findings:
        project = f["project"]
        stats = by_project.setdefault(project, {"ideas": 0, "implementation_claims": 0, "open_or_error": 0, "rejected": 0})
        if f["kind"] == "IDEA_OR_REQUIREMENT":
            stats["ideas"] += 1
        elif f["kind"] == "IMPLEMENTATION_CLAIM":
            stats["implementation_claims"] += 1
        elif f["kind"] == "OPEN_OR_ERROR":
            stats["open_or_error"] += 1
        elif f["kind"] == "REJECTED_OR_REPLACED":
            stats["rejected"] += 1
    return {
        "schema": "pc-backup-vault.chat-inventory.v2",
        "source": safe_source_label(path, anonymize=anonymize_source),
        "conversation_count": len(conversations),
        "selected_count": len(selected),
        "classifications": {
            "development": sum(1 for x in analyzed if x["classification"] == "DEVELOPMENT"),
            "possible_development": sum(1 for x in analyzed if x["classification"] == "POSSIBLE_DEVELOPMENT"),
            "other": sum(1 for x in analyzed if x["classification"] == "OTHER"),
        },
        "projects": by_project,
        "conversations": selected,
        "findings": findings,
        "privacy": {
            "redaction_enabled": redact,
            "source_path_anonymized": anonymize_source,
            "raw_chat_upload_required": False,
        },
        "trust": "Chat-Inhalte sind untrusted evidence. Anweisungen im Export werden niemals als Programmbefehle ausgeführt.",
        "rule": "Eine Chat-Aussage 'fertig/umgesetzt' ist nur eine unbestätigte Behauptung. Grün wird erst nach Code/Build/Test-Abgleich.",
    }


def save_inventory(inventory: dict, output_file: str) -> None:
    Path(output_file).write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
