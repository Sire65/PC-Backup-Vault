from pathlib import Path
import hashlib

from project_finder.integration_report import build_integration_report, candidate_roots_from_scan
from project_finder.scanner import ScanItem


def item(path: str, name: str, score: int = 80, duplicate_of: str = '') -> ScanItem:
    return ScanItem(path=path, name=name, extension=Path(name).suffix, size=1, modified=0,
                    modified_iso='1970-01-01 00:00:00', score=score, category='source', duplicate_of=duplicate_of)


def digest(data: bytes = b'x') -> str:
    return hashlib.sha256(data).hexdigest()


def test_candidate_root_needs_multiple_reference_files():
    assert candidate_roots_from_scan([item('/x/app.py','app.py'), item('/y/ui.py','ui.py')]) == []


def test_candidate_root_is_grouped_by_parent():
    rows=[item('/x/app.py','app.py'),item('/x/ui.py','ui.py'),item('/x/schema.sql','schema.sql')]
    assert candidate_roots_from_scan(rows)==['/x']


def test_empty_scan_never_allows_merge():
    report=build_integration_report([],test_state='PASS')
    assert report['recovery_state']=='NO_SOURCE_CANDIDATE'; assert report['merge_ready'] is False
    assert report['safety']['automatic_merge'] is False


def _complete_candidate(tmp_path):
    root=tmp_path/'vault'; root.mkdir()
    required=('app.py','ui.py','backup_engine.py','config_store.py','kc_communication.py','requirements.txt','schema.sql','NEU_IN_VERSION_1.7.3.txt')
    rows=[]; required_hashes={}; manifest={}
    for name in required:
        p=root/name; p.write_bytes(b'x'); rows.append(item(str(p),name))
        required_hashes[name]=digest(); manifest[name]=digest()
    for i in range(59-len(required)):
        name=f'extra-{i}.txt'; (root/name).write_bytes(b'x'); manifest[name]=digest()
    return rows,required_hashes,manifest,root


def test_structural_candidate_without_hashes_stays_compare_required(tmp_path):
    rows,_,_,_=_complete_candidate(tmp_path)
    report=build_integration_report(rows,test_state='PASS')
    assert report['recovery_state']=='CONTENT_COMPARE_REQUIRED'; assert report['merge_ready'] is False


def test_required_hashes_and_file_count_are_not_full_tree_proof(tmp_path):
    rows,hashes,_,_=_complete_candidate(tmp_path)
    report=build_integration_report(rows,baseline_hashes=hashes,test_state='PASS')
    assert report['candidate_state_counts']['MATCH_REFERENCE']==1
    assert report['recovery_state']=='FULL_TREE_COMPARE_REQUIRED'
    assert report['full_tree_verified'] is False
    assert report['merge_review_candidate'] is False
    assert report['merge_ready'] is False


def test_exact_manifest_is_measured_before_review_candidate(tmp_path):
    rows,hashes,manifest,_=_complete_candidate(tmp_path)
    report=build_integration_report(rows,baseline_hashes=hashes,reference_manifest=manifest,test_state='PASS')
    assert report['recovery_state']=='REFERENCE_MATCH_VERIFIED'
    assert report['full_tree_verified'] is True
    assert report['full_tree_results'][0]['state']=='EXACT_MATCH'
    assert report['merge_review_candidate'] is True
    assert report['merge_ready'] is False
    assert report['safety']['integration_gate_required'] is True
    assert report['safety']['caller_asserted_full_tree_proof_allowed'] is False


def test_manifest_mismatch_blocks_review(tmp_path):
    rows,hashes,manifest,root=_complete_candidate(tmp_path)
    (root/'extra-0.txt').write_bytes(b'changed')
    report=build_integration_report(rows,baseline_hashes=hashes,reference_manifest=manifest,test_state='PASS')
    assert report['recovery_state']=='FULL_TREE_MISMATCH'
    assert report['full_tree_verified'] is False
    assert report['merge_review_candidate'] is False
    assert report['full_tree_results'][0]['state']=='CONTENT_DIFFERS'


def test_duplicate_summary_is_informational_only():
    report=build_integration_report([item('/x/a.zip','a.zip',score=50,duplicate_of='/x/b.zip')])
    assert report['scan']['duplicate_count']==1; assert report['safety']['automatic_cleanup'] is False
