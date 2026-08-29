import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_finder.recovery_upload import build_recovery_upload_plan, upload_recovery_files
from project_finder.scanner import sha256_file


class RecoveryUploadTests(unittest.TestCase):
    def _preview_and_branch_result(self, source: Path):
        digest = sha256_file(source)
        branch = 'recovery/project-finder-dienstplan-20260829-120000'
        preview = {
            'schema': 'pc-backup-vault.recovery-preview.v1',
            'groups': [{
                'repo': 'Sire65/Dienstplan',
                'proposed_branch': branch,
                'files': [{
                    'source_path': str(source),
                    'repo_path': 'app.py',
                    'sha256': digest,
                    'blocked': False,
                }],
            }],
        }
        branch_result = {
            'created': [{
                'repo': 'Sire65/Dienstplan',
                'branch': branch,
            }],
        }
        return preview, branch_result

    def test_plan_requires_branch_to_be_confirmed_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'DP2' / 'app.py'
            source.parent.mkdir()
            source.write_text('print(42)', encoding='utf-8')
            preview, _ = self._preview_and_branch_result(source)
            plan = build_recovery_upload_plan(preview, {'created': []})
            self.assertEqual(plan['ready_count'], 0)
            self.assertIn('branch_not_confirmed_created', plan['blocked'][0]['block_reasons'])

    def test_secret_content_blocks_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'DP2' / 'app.py'
            source.parent.mkdir()
            source.write_text('CLOUDFLARE_API_TOKEN=abcdefghijklmnopqrstuvwxyz0123456789', encoding='utf-8')
            preview, branch_result = self._preview_and_branch_result(source)
            plan = build_recovery_upload_plan(preview, branch_result)
            self.assertEqual(plan['ready_count'], 0)
            self.assertIn('secret_content', plan['blocked'][0]['block_reasons'])

    def test_changed_source_blocks_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'DP2' / 'app.py'
            source.parent.mkdir()
            source.write_text('print(42)', encoding='utf-8')
            preview, branch_result = self._preview_and_branch_result(source)
            source.write_text('print(43)', encoding='utf-8')
            plan = build_recovery_upload_plan(preview, branch_result)
            self.assertIn('source_changed_since_preview', plan['blocked'][0]['block_reasons'])

    def test_upload_requires_explicit_approval(self):
        plan = {
            'schema': 'pc-backup-vault.recovery-upload-plan.v1',
            'blocked_count': 0,
            'ready': [],
        }
        with self.assertRaises(PermissionError):
            upload_recovery_files(plan, token='test')

    def test_existing_target_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'DP2' / 'app.py'
            source.parent.mkdir()
            source.write_text('print(42)', encoding='utf-8')
            preview, branch_result = self._preview_and_branch_result(source)
            plan = build_recovery_upload_plan(preview, branch_result)
            with patch('project_finder.recovery_upload._target_exists', return_value=True), \
                 patch('project_finder.recovery_upload._create_file') as create_file:
                result = upload_recovery_files(plan, approved=True, token='test')
            self.assertEqual(result['uploaded_count'], 0)
            self.assertEqual(len(result['failed']), 1)
            self.assertIn('target_already_exists_no_overwrite', result['failed'][0]['error'])
            create_file.assert_not_called()

    def test_new_file_upload_uses_recovery_branch_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'DP2' / 'app.py'
            source.parent.mkdir()
            source.write_text('print(42)', encoding='utf-8')
            preview, branch_result = self._preview_and_branch_result(source)
            plan = build_recovery_upload_plan(preview, branch_result)
            with patch('project_finder.recovery_upload._target_exists', return_value=False), \
                 patch('project_finder.recovery_upload._create_file', return_value={'commit': {'sha': 'abc'}}) as create_file:
                result = upload_recovery_files(plan, approved=True, token='test')
            self.assertEqual(result['uploaded_count'], 1)
            self.assertFalse(result['overwrite_performed'])
            self.assertFalse(result['main_modified'])
            args = create_file.call_args.args
            self.assertTrue(args[1].startswith('recovery/project-finder-'))
            self.assertNotIn(args[1].lower(), {'main', 'master'})


if __name__ == '__main__':
    unittest.main()
