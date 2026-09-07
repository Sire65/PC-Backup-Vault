from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backup_engine import BackupControl
from crypto_box import create_key_b64
from storage_v180 import filesystem_backup
from professional_v180 import (
    list_filesystem_jobs,
    preflight_filesystem_target,
    verify_filesystem_job,
    restore_filesystem_job,
    filesystem_restore_selftest,
    prune_filesystem_retention,
)


class DummyApp:
    def __init__(self, key): self._key=key
    def master_key(self): return self._key


class ProfessionalV180Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="pcbv-prof-test-")
        self.root=Path(self.tmp.name)
        self.src=self.root/"source"; self.src.mkdir()
        (self.src/"alpha.txt").write_text("Alpha "*5000,encoding="utf-8")
        (self.src/"beta.bin").write_bytes(bytes(range(256))*300)
        self.target_path=self.root/"target"; self.target_path.mkdir()
        self.target={"id":"test","name":"Testziel","path":str(self.target_path),"kind":"ORDNER"}
        self.key=create_key_b64(); self.app=DummyApp(self.key)

    def tearDown(self): self.tmp.cleanup()

    def backup(self, name="Regression"):
        paths=[self.src/"alpha.txt",self.src/"beta.bin"]
        return filesystem_backup(self.app,paths,self.target,control=BackupControl(),plan_name=name)

    def test_backup_verify_restore_roundtrip(self):
        result=self.backup()
        jobs=list_filesystem_jobs(self.target)
        self.assertEqual(1,len(jobs)); self.assertEqual(result["job_id"],jobs[0]["job_id"])
        quick=verify_filesystem_job(self.target,jobs[0],self.key,full=False)
        full=verify_filesystem_job(self.target,jobs[0],self.key,full=True)
        self.assertEqual("PASS",quick["result"]); self.assertEqual("PASS",full["result"])
        restore=self.root/"restore"
        rr=restore_filesystem_job(self.target,jobs[0],self.key,restore)
        self.assertEqual("PASS",rr["result"]); self.assertEqual(2,rr["restored"])
        restored=list(restore.rglob("alpha.txt"))
        self.assertEqual(1,len(restored)); self.assertEqual((self.src/"alpha.txt").read_bytes(),restored[0].read_bytes())

    def test_corruption_is_detected(self):
        self.backup(); job=list_filesystem_jobs(self.target)[0]
        ref=job["files"][0]["chunks"][0]["file"]
        chunk=self.target_path/".pc-backup-vault"/"chunks"/Path(ref)
        data=bytearray(chunk.read_bytes()); data[-1]^=0x01; chunk.write_bytes(data)
        self.assertEqual("FAIL",verify_filesystem_job(self.target,job,self.key,full=False)["result"])

    def test_restore_selftest(self):
        self.backup(); st=filesystem_restore_selftest(self.target,self.key,256)
        self.assertEqual("PASS",st["status"])

    def test_preflight_blocks_source_target_overlap(self):
        nested=self.src/"backup-inside-source"; nested.mkdir()
        target={"id":"nested","name":"Nested","path":str(nested)}
        p=preflight_filesystem_target(target,[self.src],100)
        codes={x["code"]:x["ok"] for x in p["checks"]}
        self.assertFalse(codes["SOURCE_TARGET_SEPARATION"]); self.assertFalse(p["ok"])

    def test_missing_target_fails_preflight(self):
        p=preflight_filesystem_target({"path":str(self.root/"missing")},[],100)
        self.assertFalse(p["ok"])

    def test_retention_deletes_old_manifest_but_keeps_referenced_data(self):
        self.backup("R"); (self.src/"alpha.txt").write_text("Version 2",encoding="utf-8"); self.backup("R"); (self.src/"alpha.txt").write_text("Version 3",encoding="utf-8"); self.backup("R")
        jobs=list_filesystem_jobs(self.target); self.assertEqual(3,len(jobs))
        oldest=jobs[-1]; mp=Path(oldest["_manifest_path"]); doc=json.loads(mp.read_text(encoding="utf-8")); doc["created_at"]=(datetime.now(timezone.utc)-timedelta(days=400)).isoformat(); mp.write_text(json.dumps(doc),encoding="utf-8")
        out=prune_filesystem_retention(self.target,"R",keep_last=2,retention_days=90)
        self.assertEqual(1,out["deleted_manifests"]); self.assertEqual(2,len([j for j in list_filesystem_jobs(self.target) if j.get("plan_name")=="R"]))
        for job in list_filesystem_jobs(self.target): self.assertEqual("PASS",verify_filesystem_job(self.target,job,self.key,full=False)["result"])


if __name__ == "__main__": unittest.main()
