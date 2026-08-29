from pathlib import Path

from project_finder.decision_engine import classify_item, inventory_summary
from project_finder.scanner import ScanItem


def item(path, *, ext=None, size=10, score=0, duplicate_of='', sha='x'):
    p = Path(path)
    return ScanItem(
        path=str(p), name=p.name, extension=ext if ext is not None else p.suffix.lower(),
        size=size, modified=0, modified_iso='1970-01-01 00:00:00', score=score,
        category='source' if p.suffix.lower() in {'.py','.js','.json'} else 'other',
        sha256=sha, duplicate_of=duplicate_of,
    )


def test_project_source_is_git_candidate():
    row = classify_item(item(r'C:\KC\src\app.py'))
    assert row['git_action'] == 'TO_GIT'
    assert row['inventory_action'] == 'KEEP'


def test_project_asset_image_is_git_candidate():
    row = classify_item(item(r'C:\KC\pos\assets\apfelpunsch.webp'))
    assert row['git_action'] == 'TO_GIT'
    assert row['inventory_action'] == 'KEEP'


def test_duplicate_beats_git_candidate_and_only_quarantine_candidate():
    row = classify_item(item(r'C:\KC\pos\assets\copy.webp', duplicate_of=r'C:\KC\pos\assets\original.webp'))
    assert row['inventory_action'] == 'QUARANTINE_CANDIDATE'
    assert row['git_action'] == 'NO'
    assert row['confidence'] >= 95


def test_secret_never_git():
    row = classify_item(item(r'C:\KC\src\api_token.txt', score=80))
    assert row['git_action'] == 'NEVER'
    assert row['inventory_action'] == 'KEEP_LOCAL'


def test_archive_stays_local_and_needs_git_review():
    row = classify_item(item(r'C:\KC\release\KC_final.zip', score=80))
    assert row['inventory_action'] == 'KEEP_LOCAL'
    assert row['git_action'] == 'REVIEW'


def test_temp_tree_not_recommended_to_git():
    row = classify_item(item(r'C:\KC\build\app.js', score=80))
    assert row['inventory_action'] == 'REVIEW'
    assert row['git_action'] == 'NO'


def test_summary_counts_actions():
    rows = [
        item(r'C:\KC\src\app.py'),
        item(r'C:\KC\pos\assets\a.webp'),
        item(r'C:\KC\pos\assets\b.webp', duplicate_of=r'C:\KC\pos\assets\a.webp'),
        item(r'C:\KC\api_token.txt', score=80),
    ]
    s = inventory_summary(rows)
    assert s['counts']['files'] == 4
    assert s['counts']['to_git'] == 2
    assert s['counts']['quarantine_candidates'] == 1
    assert s['counts']['never_git'] == 1
