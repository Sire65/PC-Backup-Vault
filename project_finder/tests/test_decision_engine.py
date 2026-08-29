import unittest
from pathlib import Path

from project_finder.decision_engine import classify_item, inventory_summary
from project_finder.scanner import ScanItem


def make_item(path, *, ext=None, size=10, score=0, duplicate_of='', sha='x'):
    p = Path(path)
    return ScanItem(
        path=str(p), name=p.name, extension=ext if ext is not None else p.suffix.lower(),
        size=size, modified=0, modified_iso='1970-01-01 00:00:00', score=score,
        category='source' if p.suffix.lower() in {'.py', '.js', '.json'} else 'other',
        sha256=sha, duplicate_of=duplicate_of,
    )


class DecisionEngineTests(unittest.TestCase):
    def test_project_source_is_git_candidate(self):
        row = classify_item(make_item(r'C:\KC\src\app.py'))
        self.assertEqual(row['git_action'], 'TO_GIT')
        self.assertEqual(row['inventory_action'], 'KEEP')

    def test_project_asset_image_is_git_candidate(self):
        row = classify_item(make_item(r'C:\KC\pos\assets\apfelpunsch.webp'))
        self.assertEqual(row['git_action'], 'TO_GIT')
        self.assertEqual(row['inventory_action'], 'KEEP')

    def test_duplicate_beats_git_candidate(self):
        row = classify_item(make_item(r'C:\KC\pos\assets\copy.webp', duplicate_of=r'C:\KC\pos\assets\original.webp'))
        self.assertEqual(row['inventory_action'], 'QUARANTINE_CANDIDATE')
        self.assertEqual(row['git_action'], 'NO')
        self.assertGreaterEqual(row['confidence'], 95)

    def test_secret_never_git(self):
        row = classify_item(make_item(r'C:\KC\src\api_token.txt', score=80))
        self.assertEqual(row['git_action'], 'NEVER')
        self.assertEqual(row['inventory_action'], 'KEEP_LOCAL')

    def test_archive_stays_local_and_needs_git_review(self):
        row = classify_item(make_item(r'C:\KC\release\KC_final.zip', score=80))
        self.assertEqual(row['inventory_action'], 'KEEP_LOCAL')
        self.assertEqual(row['git_action'], 'REVIEW')

    def test_temp_tree_not_recommended_to_git(self):
        row = classify_item(make_item(r'C:\KC\build\app.js', score=80))
        self.assertEqual(row['inventory_action'], 'REVIEW')
        self.assertEqual(row['git_action'], 'NO')

    def test_summary_counts_actions(self):
        rows = [
            make_item(r'C:\KC\src\app.py'),
            make_item(r'C:\KC\pos\assets\a.webp'),
            make_item(r'C:\KC\pos\assets\b.webp', duplicate_of=r'C:\KC\pos\assets\a.webp'),
            make_item(r'C:\KC\api_token.txt', score=80),
        ]
        summary = inventory_summary(rows)
        self.assertEqual(summary['counts']['files'], 4)
        self.assertEqual(summary['counts']['to_git'], 2)
        self.assertEqual(summary['counts']['quarantine_candidates'], 1)
        self.assertEqual(summary['counts']['never_git'], 1)


if __name__ == '__main__':
    unittest.main()
