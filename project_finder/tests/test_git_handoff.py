import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from project_finder.git_handoff import create_git_handoff, exclusion_reason, guess_repo
from project_finder.scanner import scan

class GitHandoffTests(unittest.TestCase):
    def test_secret_and_generated_paths_are_rejected(self):
        self.assertEqual(exclusion_reason(Path('DP2/.env')), 'possible_secret')
        self.assertEqual(exclusion_reason(Path('DP2/node_modules/a.js')), 'generated_or_vendor_tree')
        self.assertEqual(exclusion_reason(Path('PC-Backup-Vault/_internal/tcl/init.tcl')), 'generated_or_vendor_tree')

    def test_known_repo_mapping(self):
        self.assertEqual(guess_repo(Path('D:/Entwicklung/DP2/app.py'))[0], 'Sire65/Dienstplan')
        self.assertEqual(guess_repo(Path('D:/KC Bilderrechner/app.py'))[0], 'Sire65/KC-Bilderrechner')

    def test_package_contains_real_file_hash_and_manifest_but_no_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'DP2'; root.mkdir(); source=root/'app.py'; source.write_text('print(42)',encoding='utf-8'); secret=root/'.env'; secret.write_text('TOKEN=secret',encoding='utf-8')
            rows=scan([root],hash_only_interesting=False,include_hidden=True); target=Path(tmp)/'handoff.zip'; result=create_git_handoff(rows,str(target))
            self.assertEqual(result['included'],1)
            with zipfile.ZipFile(target) as z:
                manifest=json.loads(z.read('manifest.json'))
                self.assertEqual(manifest['items'][0]['suggested_repo'],'Sire65/Dienstplan')
                self.assertTrue(manifest['items'][0]['sha256']); self.assertNotIn('.env',' '.join(z.namelist()))

if __name__=='__main__': unittest.main()
