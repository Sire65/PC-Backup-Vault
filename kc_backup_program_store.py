from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile

from kc_backup_program_registry import KCProgramDefinition, KCProgramRegistry

STORE_VERSION = 1


def apply_source_config(registry: KCProgramRegistry, config: dict) -> KCProgramRegistry:
    programs = []
    raw_programs = dict(config.get("programs") or {})
    for program in registry.all():
        program_cfg = dict(raw_programs.get(program.program_id) or {})
        raw_sources = dict(program_cfg.get("sources") or {})
        sources = tuple(
            replace(source, configured_path=(str(raw_sources.get(source.source_id)).strip() or None) if raw_sources.get(source.source_id) is not None else source.configured_path)
            for source in program.sources
        )
        programs.append(replace(program, sources=sources))
    return KCProgramRegistry(programs)


def load_program_registry(path: str | Path, base_registry: KCProgramRegistry) -> KCProgramRegistry:
    source = Path(path)
    if not source.exists():
        return base_registry
    raw = json.loads(source.read_text(encoding="utf-8"))
    if int(raw.get("store_version", 0)) != STORE_VERSION:
        raise ValueError("Unbekannte KC-Programmregister-Speicherversion")
    return apply_source_config(base_registry, raw)


def save_program_registry(path: str | Path, registry: KCProgramRegistry) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    programs = {}
    for program in registry.all():
        programs[program.program_id] = {
            "sources": {
                source.source_id: source.configured_path
                for source in program.sources
                if source.configured_path
            }
        }
    payload = {"store_version": STORE_VERSION, "programs": programs}
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False, prefix=target.name + ".", suffix=".tmp") as tmp:
        tmp.write(text)
        tmp.flush()
        temp_path = Path(tmp.name)
    temp_path.replace(target)
