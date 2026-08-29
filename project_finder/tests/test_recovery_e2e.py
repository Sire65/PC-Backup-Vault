import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_finder.recovery_branch import create_recovery_branches
from project_finder.recovery_preview import build_recovery_preview
from project_finder.recovery_upload import build_recovery_upload_plan, upload_recovery_files
from project_finder.scanner import scan


class RecoveryWorkflowE2ETests(unittest.TestCase):
    def test_preview_branch_upload_chain_never_targets_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'DP2'
            root.mkdir()
            source = root / 'app.py'
            source.write_text('print(42)\n', encoding='utf-8')
            items = scan([root], hash_only_interesting=False)
            item = items[0]
            report = {
                'schema': 'pc-backup-vault.github-compare.v2',
                'read_only': True,
                'items': [{
                    'path': item.path,
                    'repo': 'Sire65/Dienstplan',
                    'repo_path': 'app.py',
                    'state': 'LOCAL_ONLY',
                    'local_sha256': item.sha256,
                    'remote_sha256': '',
                }],
            }
            preview = build_recovery_preview(items, report)
            self.assertEqual(preview['candidate_count'], 1)
            self.assertFalse(preview['main_modified'])

            with patch('project_finder.recovery_branch._default_branch', return_value='main'), \
                 patch('project_finder.recovery_branch._branch_head_sha', return_value='abc123'), \
                 patch('project_finder.recovery_branch._create_branch_ref', return_value={}):
                branches = create_recovery_branches(preview, token='test')

            self.assertEqual(branches['branch_refs_created'], 1)
            self.assertEqual(branches['files_written'], 0)
            self.assertFalse(branches['main_modified'])
            branch_name = branches['created'][0]['branch']
            self.assertTrue(branch_name.startswith('recovery/project-finder-'))

            plan = build_recovery_upload_plan(preview, branches)
            self.assertEqual(plan['ready_count'], 1)
            self.assertEqual(plan['blocked_count'], 0)
            self.assertFalse(plan['overwrite_allowed'])
            self.assertFalse(plan['main_modified'])

            with patch('project_finder.recovery_upload._target_exists', return_value=False), \
                 patch('project_finder.recovery_upload._create_file', return_value={'commit': {'sha': 'deadbeef'}}) as create_file:
                uploaded = upload_recovery_files(plan, approved=True, token='test')

            self.assertEqual(uploaded['uploaded_count'], 1)
            self.assertFalse(uploaded['overwrite_performed'])
            self.assertFalse(uploaded['main_modified'])
            called_branch = create_file.call_args.args[1]
            self.assertTrue(called_branch.startswith('recovery/project-finder-'))
            self.assertNotIn(called_branch.lower(), {'main', 'master'})


if __name__ == '__main__':
    unittest.main()
