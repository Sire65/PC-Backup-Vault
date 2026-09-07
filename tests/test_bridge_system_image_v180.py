import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import kc_backup_client_v180 as client
import kc_backup_bridge_v180 as bridge
import system_image_v180 as simage


class DummyStore:
    def __init__(self, root):
        self.path=Path(root)/"config.json"
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.data={"filesystem_targets":[],"active_filesystem_target_id":None}


class BridgeSystemImageTests(unittest.TestCase):
    def test_client_enqueue_and_status(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ,{"PROGRAMDATA":td}):
            rid=client.request_backup("KC DP2",[r"C:\\KC\\DP2"],job_name="DP2 Backup",target_name="USB Backup",source_job_id="dp2-42")
            inbox=Path(td)/"PCBackupVault"/"kc_bridge"/"inbox"/f"{rid}.json"
            self.assertTrue(inbox.exists())
            data=json.loads(inbox.read_text(encoding="utf-8"))
            self.assertEqual(data["source_program"],"KC DP2")
            self.assertEqual(data["source_job_id"],"dp2-42")
            self.assertNotIn("password",data)
            self.assertEqual(client.backup_status(rid)["status"],"QUEUED")

    def test_bridge_rejects_secret_fields(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ,{"PROGRAMDATA":td}):
            store=DummyStore(td)
            with self.assertRaises(ValueError):
                bridge.submit_request(store,{"source_program":"KC Test","paths":[td],"password":"never"})

    def test_system_image_builds_native_wbadmin_command(self):
        target={"name":"ImageDisk","path":r"E:\\Backup"}
        completed=mock.Mock(returncode=0,stdout="OK",stderr="")
        preflight_ok={"ok":True,"checks":[{"name":"Test","ok":True,"detail":"OK"}]}
        with mock.patch.object(simage,"preflight_system_image",return_value=preflight_ok), mock.patch("system_image_v180.subprocess.run",return_value=completed) as run:
            result=simage.create_system_image(target,include_volume="C:",quiet=True)
        args=run.call_args.args[0]
        self.assertEqual(args[:3],["wbadmin","start","backup"])
        self.assertIn("-allCritical",args)
        self.assertIn("-include:C:",args)
        self.assertIn("-quiet",args)
        self.assertEqual(result["native_format"],"WindowsImageBackup")
        self.assertFalse(result["application_encrypted"])

    def test_system_image_blocks_same_source_target_volume(self):
        target={"name":"bad","path":r"C:\\ImageBackup"}
        with mock.patch.object(simage,"_is_admin",return_value=True), mock.patch("system_image_v180.os.path.exists",return_value=True), mock.patch("system_image_v180.Path.write_bytes"), mock.patch("system_image_v180.Path.unlink"):
            pre=simage.preflight_system_image(target,"C:")
        self.assertFalse(pre["ok"])
        self.assertTrue(any((not c["ok"]) and c["name"]=="Quelle/Ziel getrennt" for c in pre["checks"]))


if __name__=="__main__":
    unittest.main()
