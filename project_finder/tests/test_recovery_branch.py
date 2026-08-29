import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_finder.recovery_branch import create_recovery_branches, validate_recovery_preview


class RecoveryBranchTests(unittest.TestCase):
    def _preview(self, source: Path):
        import hashlib
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        return {
            'schema': 'pc-backup-vault.recovery-preview.v1',
            'main_modified': False,
            'groups': [{
                'repo': 'Sire65/Dienstplan',
                'proposed_branch': 'recovery/project-finder-dienstplan-20260829-120000',
                'files': [{
                    'source_path': str(source),
                    'sha256': digest,
                    'blocked': False,
                }],
            }],
        }

    def test_rejects_unsafe_branch_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'app.py'
            source.write_text('print(1)', encoding='utf-8')
            preview = self._preview(source)
            preview['groups'][0]['proposed_branch'] = 'main'
            errors = validate_recovery_preview(preview)
            self.assertTrue(any('unsafe_branch_name' in e or 'protected_branch_name' in e for e in errors))

    def test_rejects_source_changed_since_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'app.py'
            source.write_text('print(1)', encoding='utf-8')
            preview = self._preview(source)
            source.write_text('print(2)', encoding='utf-8')
            errors = validate_recovery_preview(preview)
            self.assertTrue(any(e.startswith('source_changed_since_preview:') for e in errors))

    def test_creates_only_branch_ref_and_writes_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'app.py'
            source.write_text('print(1)', encoding='utf-8')
            preview = self._preview(source)
            with patch('project_finder.recovery_branch._default_branch', return_value='main'), \
                 patch('project_finder.recovery_branch._branch_head_sha', return_value='abc123'), \
                 patch('project_finder.recovery_branch._create_branch_ref', return_value={'ref': 'refs/heads/recovery/test'}) as create_ref:
                result = create_recovery_branches(preview, token='test-token')
            self.assertEqual(result['branch_refs_created'], 1)
            self.assertEqual(result['files_written'], 0)
            self.assertFalse(result['main_modified'])
            create_ref.assert_called_once()

    def test_missing_token_blocks_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'app.py'
            source.write_text('print(1)', encoding='utf-8')
            preview = self._preview(source)
            with self.assertRaises(RuntimeError):
                create_recovery_branches(preview, token='')


if __name__ == '__main__':
    unittest.main()
