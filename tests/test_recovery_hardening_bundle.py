import json
import tempfile
import unittest
from pathlib import Path

from nas_recovery.inventory import classify_recovery_area
from nas_recovery.recovery_audit import build_recovery_audit, save_recovery_audit
from nas_recovery.recovery_plan import RecoveryPlanState, RecoveryStage
from nas_recovery.recovery_readiness import overall_recovery_status, readiness_snapshot
from nas_recovery.recovery_session import RecoverySession


class RecoveryHardeningBundleTests(unittest.TestCase):
    def test_numbered_volume_is_data_but_similar_name_is_not(self):
        self.assertEqual(classify_recovery_area('/volume1').category, 'data')
        self.assertEqual(classify_recovery_area('/volume12/photos').category, 'data')
        self.assertEqual(classify_recovery_area('/volumebad').category, 'review')

    def test_readiness_never_unlocks_recovery_early(self):
        state = RecoveryPlanState(source_identified=True, source_assessed=True, image_path='D:/disk.img', image_complete=True)
        rows = {row.stage: row for row in readiness_snapshot(state)}
        self.assertTrue(rows[RecoveryStage.VERIFY].allowed)
        self.assertFalse(rows[RecoveryStage.ANALYZE].allowed)
        self.assertFalse(rows[RecoveryStage.RECOVER].allowed)
        self.assertEqual(overall_recovery_status(state)[0], 'warn')

    def test_audit_contains_safety_evidence_and_is_atomic(self):
        session = RecoverySession(source_label='Disk 3', source_identified=True, source_assessed=True, image_path='D:/disk.img')
        audit = build_recovery_audit(session)
        self.assertFalse(audit['safety']['original_write_performed'])
        self.assertFalse(audit['safety']['filesystem_repair_performed'])
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'audit.json'
            saved = save_recovery_audit(session, target)
            self.assertEqual(saved, target)
            data = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(data['schema'], 'pc-backup-vault.recovery-audit.v1')
            self.assertFalse(target.with_suffix('.json.tmp').exists())


if __name__ == '__main__':
    unittest.main()
