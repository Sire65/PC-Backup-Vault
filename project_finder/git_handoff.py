from __future__ import annotations

import hashlib
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Iterable

from project_finder.scanner import DEFAULT_EXCLUDED_DIRS, ScanItem, sha256_file

SECRET_NAMES = {'.env', '.env.local', '.env.production', '.env.development', 'credentials.json', 'secrets.json', 'service-account.json', 'id_rsa', 'id_ed25519'}
SECRET_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.jks', '.keystore'}
SECRET_RE = re.compile(r'(secret|token|password|passwd|api[_-]?key|private[_-]?key|service[_-]?account)', re.I)
REPO_HINTS = (
    (('dp2', 'dienstplan'), 'Sire65/Dienstplan'),
    (('pc-backup-vault', 'backup vault'), 'Sire65/PC-Backup-Vault'),
    (('bilderkasse', 'marktkasse', 'kc marktkasse'), 'Sire65/Kasse'),
    (('bilderrechner', 'kc-bilderrechner'), 'Sire65/KC-Bilderrechner'),
)

def _parts(path: Path) -> list[str]: return [p.lower() for p in path.parts]
def exclusion_reason(path: Path) -> str:
    parts = _parts(path)
    if any(p in {x.lower() for x in DEFAULT_EXCLUDED_DIRS} for p in parts): return 'generated_or_vendor_tree'
    low = path.name.lower()
    if low in SECRET_NAMES or path.suffix.lower() in SECRET_SUFFIXES or SECRET_RE.search(low): return 'possible_secret'
    if '.git' in parts: return 'git_metadata'
    return ''
def guess_repo(path: Path) -> tuple[str, int]:
    low = str(path).lower().replace('\\', '/')
    for words, repo in REPO_HINTS:
        if any(w in low for w in words): return repo, 90
    return '', 0
def create_git_handoff(items: Iterable[ScanItem], target_zip: str, *, allowed_statuses=('GREEN','YELLOW')) -> dict:
    target = Path(target_zip); target.parent.mkdir(parents=True, exist_ok=True)
    rows=[]; excluded=[]; seen=set()
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for item in items:
            src=Path(item.path); reason=exclusion_reason(src)
            if reason: excluded.append({'source_path':str(src),'reason':reason}); continue
            if item.status not in allowed_statuses or item.duplicate_of or item.category not in {'source','document','image_asset','binary_or_launcher'}: continue
            if not src.exists() or not src.is_file(): excluded.append({'source_path':str(src),'reason':'missing'}); continue
            digest=sha256_file(src)
            key=(digest,src.name.lower())
            if key in seen: excluded.append({'source_path':str(src),'reason':'duplicate_content'}); continue
            seen.add(key); repo,confidence=guess_repo(src)
            project=(repo.split('/',1)[-1] if repo else 'UNASSIGNED')
            safe_name=hashlib.sha256(str(src).encode('utf-8')).hexdigest()[:12]+'_'+src.name
            archive_path=f'files/{project}/{safe_name}'
            z.write(src,archive_path)
            rows.append({'source_path':str(src),'archive_path':archive_path,'sha256':digest,'size':src.stat().st_size,'category':item.category,'scanner_status':item.status,'suggested_repo':repo,'repo_confidence':confidence,'decision':'REVIEW' if not repo else 'COMPARE_WITH_GITHUB'})
        manifest={'schema':'pc-backup-vault.git-handoff.v1','created_at':time.strftime('%Y-%m-%d %H:%M:%S'),'safety':{'source_modified':False,'secrets_excluded':True,'generated_trees_excluded':True,'github_write_performed':False},'items':rows,'excluded':excluded}
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        z.writestr('README.txt','PC Backup Vault - Git-Uebergabepaket\n\nDieses Paket schreibt nichts nach GitHub. Dateien muessen anhand manifest.json mit dem Ziel-Repository verglichen werden. Secrets und generierte Laufzeit-/Build-Verzeichnisse werden ausgeschlossen. Nie blind main ueberschreiben.\n')
    return {'zip':str(target),'included':len(rows),'excluded':len(excluded),'manifest':manifest}
