from __future__ import annotations

import json
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

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
class ChatFinding:
    conversation_id: str
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


def _conversation_messages(conv: dict) -> list[str]:
    out: list[str] = []
    mapping = conv.get("mapping")
    if isinstance(mapping, dict):
        for node in mapping.values():
            if not isinstance(node, dict):
                continue
            message = node.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                out.extend(_iter_text(content))
    for key in ("messages", "chat_messages"):
        if key in conv:
            out.extend(_iter_text(conv[key]))
    return [x for x in out if x]


def _project_scores(text: str) -> dict[str, int]:
    lower = text.lower()
    scores: dict[str, int] = {}
    for project, patterns in PROJECT_PATTERNS.items():
        score = sum(1 for p in patterns if re.search(p, lower, re.I))
        if score:
            scores[project] = score
    return scores


def classify_conversation(title: str, messages: list[str]) -> tuple[str, int]:
    corpus = (title + "\n" + "\n".join(messages[:200])).lower()
    project_score = sum(_project_scores(corpus).values())
    dev_score = len(DEV_PATTERNS.findall(corpus))
    score = project_score * 4 + min(dev_score, 20)
    if score >= 12:
        return "DEVELOPMENT", score
    if score >= 5:
        return "POSSIBLE_DEVELOPMENT", score
    return "OTHER", score


def analyze_conversation(conv: dict) -> dict:
    cid = str(conv.get("id") or conv.get("conversation_id") or "unknown")
    title = str(conv.get("title") or "Ohne Titel")
    timestamp = conv.get("create_time") or conv.get("update_time")
    messages = _conversation_messages(conv)
    classification, relevance_score = classify_conversation(title, messages)

    findings: list[ChatFinding] = []
    for text in messages:
        projects = _project_scores(title + "\n" + text)
        if not projects:
            continue
        project = max(projects, key=projects.get)
        kinds: list[tuple[str, re.Pattern, str]] = [
            ("OPEN_OR_ERROR", OPEN_PATTERNS, "chat-claim"),
            ("IMPLEMENTATION_CLAIM", DONE_PATTERNS, "chat-claim-unverified"),
            ("IDEA_OR_REQUIREMENT", IDEA_PATTERNS, "chat-requirement"),
            ("REJECTED_OR_REPLACED", REJECTED_PATTERNS, "chat-decision"),
        ]
        for kind, pattern, strength in kinds:
            if pattern.search(text):
                findings.append(ChatFinding(cid, title, str(timestamp) if timestamp is not None else None, project, kind, text[:2000], strength))
                break

    return {
        "conversation_id": cid,
        "title": title,
        "timestamp": timestamp,
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


def inventory_export(path: str, include_other: bool = False) -> dict:
    conversations = load_export(path)
    analyzed = [analyze_conversation(c) for c in conversations]
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
        "schema": "pc-backup-vault.chat-inventory.v1",
        "source": str(Path(path)),
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
        "rule": "Eine Chat-Aussage 'fertig/umgesetzt' ist nur eine unbestätigte Behauptung. Grün wird erst nach Code/Build/Test-Abgleich.",
    }


def save_inventory(inventory: dict, output_file: str) -> None:
    Path(output_file).write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
