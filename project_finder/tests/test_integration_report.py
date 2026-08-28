from pathlib import Path

from project_finder.integration_report import build_integration_report, candidate_roots_from_scan
from project_finder.scanner import ScanItem


def item(path: str, name: str, score: int = 80, duplicate_of: str = '') -> ScanItem:
    return ScanItem(path=path, name=name, extension=Path(name).suffix, size=1, modified=0,
                    modified_iso='1970-01-01 00:00:00', score=score, category='source',
                    duplicate_of=duplicate_of)


def test_candidate_root_needs_multiple_reference_files():
    rows = [item('/x/app.py', 'app.py'), item('/y/ui.py', 'ui.py')]
    assert candidate_roots_from_scan(rows) == []


def test_candidate_root_is_grouped_by_parent():
    rows = [item('/x/app.py', 'app.py'), item('/x/ui.py', 'ui.py'), item('/x/schema.sql', 'schema.sql')]
    assert candidate_roots_from_scan(rows) == ['/x']


def test_empty_scan_never_allows_merge():
    report = build_integration_report([], test_state='PASS')
    assert report['recovery_state'] == 'NO_SOURCE_CANDIDATE'
    assert report['merge_ready'] is False
    assert report['safety']['automatic_merge'] is False


def test_structural_candidate_without_hashes_stays_compare_required(tmp_path):
    root = tmp_path / 'vault'; root.mkdir()
    required = ('app.py','ui.py','backup_engine.py','config_store.py','kc_communication.py','requirements.txt','schema.sql','NEU_IN_VERSION_1.7.3.txt')
    rows = []
    for name in required:
        p = root / name; p.write_text('x', encoding='utf-8')
        rows.append(item(str(p), name))
    report = build_integration_report(rows, test_state='PASS')
    assert report['recovery_state'] == 'CONTENT_COMPARE_REQUIRED'
    assert report['merge_ready'] is False


def test_duplicate_summary_is_informational_only():
    rows = [item('/x/a.zip','a.zip',score=50,duplicate_of='/x/b.zip')]
    report = build_integration_report(rows)
    assert report['scan']['duplicate_count'] == 1
    assert report['safety']['automatic_cleanup'] is False
