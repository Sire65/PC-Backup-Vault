import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from project_finder.git_handoff import create_git_handoff, exclusion_reason, guess_repo, secret_content_reason
from project_finder.scanner import scan


class GitHandoffTests(unittest.TestCase):
    def test_secret_and_generated_paths_are_rejected(self):
        self.assertEqual(exclusion_reason(Path('DP2/.env')), 'possible_secret')
        self.assertEqual(exclusion_reason(Path('DP2/node_modules/a.js')), 'generated_or_vendor_tree')
        self.assertEqual(exclusion_reason(Path('PC-Backup-Vault/_internal/tcl/init.tcl')), 'generated_or_vendor_tree')

    def test_known_repo_mapping(self):
        self.assertEqual(guess_repo(Path('D:/Entwicklung/DP2/app.py'))[0], 'Sire65/Dienstplan')
        self.assertEqual(guess_repo(Path('D:/KC Bilderrechner/app.py'))[0], 'Sire65/KC-Bilderrechner')

    def test_secret_content_detection_is_high_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = root / 'config.py'
            key.write_text('PRIVATE_KEY=abcdefghijklmnopqrstuvwxyz0123456789', encoding='utf-8')
            self.assertEqual(secret_content_reason(key), 'secret_content')

            env_ref = root / 'safe.py'
            env_ref.write_text("import os\nvalue=os.getenv('SUPABASE_SERVICE_ROLE_KEY')\n", encoding='utf-8')
            self.assertEqual(secret_content_reason(env_ref), '')

            private_key = root / 'key.txt'
            private_key.write_text('-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----', encoding='utf-8')
            self.assertEqual(secret_content_reason(private_key), 'secret_content')

    def test_package_contains_real_file_hash_and_manifest_but_no_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'DP2'
            root.mkdir()
            source = root / 'app.py'
            source.write_text('print(42)', encoding='utf-8')
            secret = root / '.env'
            secret.write_text('TOKEN=secret', encoding='utf-8')
            rows = scan([root], hash_only_interesting=False, include_hidden=True)
            target = Path(tmp) / 'handoff.zip'
            result = create_git_handoff(rows, str(target))
            self.assertEqual(result['included'], 1)
            with zipfile.ZipFile(target) as z:
                manifest = json.loads(z.read('manifest.json'))
                self.assertEqual(manifest['schema'], 'pc-backup-vault.git-handoff.v2')
                self.assertEqual(manifest['items'][0]['suggested_repo'], 'Sire65/Dienstplan')
                self.assertEqual(manifest['items'][0]['git_action'], 'TO_GIT')
                self.assertTrue(manifest['items'][0]['sha256'])
                self.assertTrue(manifest['safety']['secret_content_scanned'])
                self.assertNotIn('.env', ' '.join(z.namelist()))

    def test_literal_secret_in_source_is_never_packaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'DP2'
            root.mkdir()
            source = root / 'app.py'
            source.write_text('CLOUDFLARE_API_TOKEN=abcdefghijklmnopqrstuvwxyz0123456789', encoding='utf-8')
            rows = scan([root], hash_only_interesting=False)
            target = Path(tmp) / 'handoff.zip'
            result = create_git_handoff(rows, str(target))
            self.assertEqual(result['included'], 0)
            self.assertTrue(any(x['reason'] == 'secret_content' for x in result['manifest']['excluded']))


if __name__ == '__main__':
    unittest.main()
